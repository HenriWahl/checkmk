#!/usr/bin/env python3
# Copyright (C) 2019 Checkmk GmbH - License: GNU General Public License v2
# This file is part of Checkmk (https://checkmk.com). It is subject to the terms and
# conditions defined in the file COPYING, which is part of this source code package.
"""Tries to connect to an IMAP or POP3 server and returns OK if successfull."""

import argparse
import base64
import logging
import os
import re
import socket
import time
from email.message import Message as POPIMAPMessage
from pathlib import Path
from typing import assert_never

from exchangelib import Message as EWSMessage

from cmk.plugins.emailchecks.lib.ac_args import parse_trx_arguments, Scope
from cmk.plugins.emailchecks.lib.connections import (
    CleanupMailboxError,
    ConnectError,
    EWS,
    IMAP,
    MailMessages,
    make_fetch_connection,
)
from cmk.plugins.emailchecks.lib.utils import (
    active_check_main,
    Args,
    CheckResult,
    fetch_mails,
    ForwardToECError,
)


def create_argument_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--forward-ec", action="store_true", help="Forward matched mails to the event console (EC)"
    )
    parser.add_argument(
        "--forward-method",
        type=str,
        metavar="METHOD",
        help=(
            "Configure how to connect to the event console to forward"
            "\nthe messages to. Can be configured to:"
            "\n    udp,<ADDR>,<PORT>        - Connect to remove EC via UDP"
            "\n    tcp,<ADDR>,<PORT>        - Connect to remove EC via TCP"
            "\n    spool:                   - Write to site local spool directory"
            "\n    spool:/path/to/spooldir  - Spool to given directory"
            "\n    /path/to/pipe            - Write to given EC event pipe"
            "\nDefaults to use the event console of the local OMD sites."
        ),
    )
    parser.add_argument(
        "--forward-facility",
        type=int,
        default=2,
        metavar="F",
        help="Syslog facility to use for forwarding (Defaults to '2' -> mail)",
    )
    parser.add_argument(
        "--forward-app",
        type=str,
        metavar="APP",
        help=(
            "Specify which string to use for the syslog application field "
            "when forwarding to the event console. "
            "\nYou can specify macros like \\1 or \\2 when you specified "
            '"--match-subject" with regex groups.'
            "\nDefaults to use the whole subject of the e mail"
        ),
    )
    parser.add_argument(
        "--forward-host", type=str, metavar="HOST", help="Hostname to use for the generated events"
    )
    parser.add_argument(
        "--body-limit",
        type=int,
        metavar="SIZE",
        default=1000,
        help=("Limit the number of characters of the body to forward (default=1000)"),
    )
    parser.add_argument(
        "--match-subject",
        type=str,
        metavar="REGEX",
        help="Use this option to not process all messages found in the inbox, "
        "but only the whones whose subject matches the given regular expression.",
    )
    parser.add_argument(
        "--cleanup",
        type=str,
        metavar="METHOD",
        help="Delete processed messages (see --match-subject) or move to subfolder "
        "a matching the given path. This is configured with the following "
        "METHOD: "
        "\n   delete             - Simply delete mails"
        "\n   path/to/subfolder  - Move to this folder (Only supported with IMAP)"
        "\nBy default the mails are not cleaned up, which might make your "
        "mailbox grow when you not clean it up manually.",
    )
    return parser


def syslog_time(localtime: time.struct_time = time.localtime()) -> str:
    """
    >>> syslog_time(time.strptime("Sep 22 21:20:19", "%b %d %H:%M:%S"))
    'Sep 22 21:20:19'
    """
    return time.strftime("%b %d %H:%M:%S", localtime)


def _get_imap_or_pop_log_line(msg: POPIMAPMessage, body_limit: int) -> str:
    subject = msg.get("Subject", "None")
    encoding = msg.get("Content-Transfer-Encoding", "None")
    payload = str(msg.get_payload())

    # Add the body to the event
    if msg.is_multipart():
        # only care for the first text/plain element
        for part in msg.walk():
            content_type = part.get_content_type()
            disposition = str(part.get("Content-Disposition"))
            encoding = part.get("Content-Transfer-Encoding", "None")
            if content_type == "text/plain" and "attachment" not in disposition:
                payload = str(part.get_payload())

    if encoding == "base64":
        # bytes -> str conversion with str() is brutal...
        payload = str(base64.b64decode(payload))
    return subject + " | " + payload[:body_limit]


def prepare_messages_for_ec(args: Args, mails: MailMessages) -> list[str]:
    # create syslog message from each mail
    # <128> Oct 24 10:44:27 Klappspaten /var/log/syslog: Oct 24 10:44:27 Klappspaten logger: asdasdad as
    # <facility+priority> timestamp hostname application: message
    messages: list[str] = []
    cur_time = syslog_time()
    priority = 5  # OK

    for _index, msg in sorted(mails.items()):
        if isinstance(msg, EWSMessage):
            subject = msg.subject
            log_line = (
                subject
                + " | "  # type: ignore[operator]
                + (
                    msg.text_body[: args.body_limit]  # type: ignore[index]
                    if msg.text_body  # type: ignore[truthy-bool]
                    else "No mail body found."
                )
            )

        elif isinstance(msg, POPIMAPMessage):
            subject = msg.get("Subject", "None")  # type: ignore[arg-type]
            log_line = _get_imap_or_pop_log_line(msg, args.body_limit)

        else:
            assert_never(msg)  # type: ignore[arg-type]

        log_line = log_line.replace("\r\n", "\0")
        log_line = log_line.replace("\n", "\0")

        # replace match groups in "forward_app"
        if args.forward_app:
            application = args.forward_app
            if args.match_subject:
                matches = re.match(args.match_subject, subject)  # type: ignore[call-overload]
                for num, match in enumerate(matches.groups() if matches else []):
                    application = application.replace("\\%d" % (num + 1,), match)
        else:
            application = subject.replace("\n", "")  # type: ignore[attr-defined]

        # Construct the final syslog message
        messages.append(
            f"<{(int(args.forward_facility) << 3) + priority}> {cur_time}"
            f" {args.forward_host or args.fetch_server} {application}: {log_line}"
        )
    return messages


def forward_to_ec(args: Args, messages: list[str]) -> CheckResult:
    # send lines to event console
    # a) local in same omd site
    # b) local pipe
    # c) remote via udp
    # d) remote via tcp
    def evaluate_forward_method(description: str) -> str | tuple[str, str, int]:
        if not description:
            return "%s/tmp/run/mkeventd/eventsocket" % os.getenv("OMD_ROOT", "")
        if description == "spool:":
            return "spool:%s/var/mkeventd/spool" % os.getenv("OMD_ROOT", "")
        if "," in description:
            prot_addr_port = description.split(",")
            return prot_addr_port[0], prot_addr_port[1], int(prot_addr_port[2])
        return description

    forward_method = evaluate_forward_method(args.forward_method)
    socket.setdefaulttimeout(args.connect_timeout)

    try:
        if messages:
            if isinstance(forward_method, tuple):
                # connect either via tcp or udp
                prot, addr, port = forward_method
                sock = (
                    socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
                    if prot == "udp"
                    else socket.socket(socket.AF_INET, socket.SOCK_STREAM)  #
                )
                sock.connect((addr, port))
                for message in messages:
                    sock.send(message.encode())
                    sock.send(b"\n")
                sock.close()

            elif not forward_method.startswith("spool:"):
                # write into local event pipe
                # Important: When the event daemon is stopped, then the pipe
                # is *not* existing! This prevents us from hanging in such
                # situations. So we must make sure that we do not create a file
                # instead of the pipe!
                sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
                try:
                    sock.connect(forward_method)
                except FileNotFoundError:
                    raise RuntimeError("%r does not exist" % forward_method)
                sock.send(("\n".join(messages)).encode())
                sock.send(b"\n")
                sock.close()

            else:
                # Spool the log messages to given spool directory.
                # First write a file which is not read into ec, then
                # perform the move to make the file visible for ec
                if not (spool_path := Path(forward_method[6:])).exists():
                    os.makedirs(spool_path)

                file_name = ".%s_%d_%d" % (args.forward_host, os.getpid(), time.time())
                path_spool_file = spool_path / file_name
                path_spool_file.write_text("\n".join(messages) + "\n")
                path_spool_file.rename(spool_path / file_name[1:])

        return (
            0,
            "Forwarded %d messages to event console" % len(messages),
            [("messages", len(messages))],
        )
    except Exception as exc:
        raise ForwardToECError(
            "Unable to forward messages to event console (%s). Left %d messages untouched."
            % (exc, len(messages))
        ) from exc


def check_mail(args: Args) -> CheckResult:
    """Create a mailbox and try to connect. In case of success our check will happily return OK
    If desired mails can also be fetched and forwarded to the event console (EC)
    """
    fetch = parse_trx_arguments(args, Scope.FETCH)
    timeout = int(args.connect_timeout)
    try:
        with make_fetch_connection(fetch, timeout) as connection:
            if not args.forward_ec:
                return 0, "Successfully logged in to mailbox", None

            fetched_mails: MailMessages = fetch_mails(connection, args.match_subject)
            ec_messages = prepare_messages_for_ec(args, fetched_mails)
            result = forward_to_ec(args, ec_messages)

            # (Copy and) Delete the forwarded mails if configured
            if args.cleanup:
                if args.cleanup != "delete":
                    if not isinstance(connection, IMAP | EWS):
                        raise CleanupMailboxError(
                            f"Copying mails is not implemented for {type(connection)!r}"
                        )
                    connection.copy(fetched_mails, folder=args.cleanup.strip("/"))
                connection.delete(fetched_mails)
            return result

    except ConnectError as exc:
        # Handle this distinct error directly since it's the thing this check is all about
        return 2, str(exc), None


def main() -> None:
    logging.getLogger().name = "check_mail"
    active_check_main(create_argument_parser(), check_mail)
