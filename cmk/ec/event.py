#!/usr/bin/env python3
# Copyright (C) 2021 Checkmk GmbH - License: GNU General Public License v2
# This file is part of Checkmk (https://checkmk.com). It is subject to the terms and
# conditions defined in the file COPYING, which is part of this source code package.

from collections.abc import Iterable, Mapping
from datetime import datetime
from logging import Logger
from re import findall
from time import localtime, mktime, strptime
from time import time as _time
from typing import Literal, TypedDict

from dateutil.parser import isoparse
from dateutil.tz import tzlocal

from cmk.ccc.hostaddress import HostAddress, HostName
from cmk.ccc.site import SiteId

# State transitions (probably incomplete):
#   {ack, open, counting} => closed
#   {ack, delayed}  => open
#   {open} => ack
EventPhase = Literal["open", "delayed", "counting", "ack", "closed"]


# This is far from perfect, but at least we see all possible keys.
class Event(TypedDict, total=False):
    # guaranteed after parsing
    facility: int
    priority: int
    text: str
    host: HostName
    ipaddress: str
    application: str
    pid: int
    time: float
    core_host: HostName | None
    host_in_downtime: bool
    # added later
    comment: str
    contact: str
    contact_groups: Iterable[str] | None  # TODO: Do we really need the Optional?
    contact_groups_notify: bool
    contact_groups_precedence: str
    count: int
    delay_until: float
    first: float
    id: int
    last: float
    last_token: float
    live_until: float
    live_until_phases: Iterable[EventPhase]
    match_groups: Iterable[str]
    match_groups_syslog_application: Iterable[str]
    orig_host: HostName
    owner: str
    phase: EventPhase
    rule_id: str | None
    site: SiteId
    sl: int
    state: int


def _make_event(text: str, ipaddress: str) -> Event:
    return Event(
        facility=1,
        priority=0,
        text=text,
        host=HostName(""),
        ipaddress=ipaddress,
        application="",
        pid=0,
        time=_time(),
        core_host=None,
        host_in_downtime=False,
    )


def create_events_from_syslog_messages(
    messages: Iterable[bytes], address: tuple[str, int] | None, logger: Logger | None
) -> Iterable[Event]:
    for message in messages:
        yield create_event_from_syslog_message(message, address, logger)


def create_event_from_syslog_message(
    message: bytes, address: tuple[str, int] | None, logger: Logger | None
) -> Event:
    if logger:
        adr = "" if address is None else f" from host {address[0]}, port {address[1]}:"
        logger.info("processing message %s %s", adr, message)
    # TODO: Is it really never a domain name?
    ipaddress = "" if address is None else address[0]
    try:
        event = parse_syslog_message_into_event(scrub_string(message.decode("utf-8")), ipaddress)
    except Exception:
        if logger:
            logger.info("could not parse message %s", message)
        event = _make_event(scrub_string(message.decode("utf-8", "replace")), ipaddress)
    if logger:
        width = max(len(k) for k in event) + 1
        logger.info(
            "parsed message: %s",
            "".join(f"\n {k + ':':{width}} {v}" for k, v in sorted(event.items())),
        )
    return event


def parse_syslog_message_into_event(line: str, ipaddress: str) -> Event:
    """
    Variant 1: plain syslog message without priority/facility:
    May 26 13:45:01 Klapprechner CRON[8046]:  message....

    Variant 1a: plain syslog message without priority/facility/host:
    May 26 13:45:01 Klapprechner CRON[8046]:  message....

    Variant 2: syslog message including facility (RFC 3164)
    <78>May 26 13:45:01 Klapprechner CRON[8046]:  message....

    Variant 2a: forwarded message from zypper on SLES15 with brackets around application
    <78>May 26 13:45:01 Klapprechner [CRON][8046]:  message....

    Variant 3: local Nagios alert posted by mkevent -n
    <154>@1341847712;5;Contact Info; MyHost My Service: CRIT - This che

    Variant 4: remote Nagios alert posted by mkevent -n -> syslog
    <154>Jul  9 17:28:32 Klapprechner @1341847712;5;Contact Info;  MyHost My Service: CRIT - This che

    Variant 5: syslog message
     Timestamp is RFC3339 with additional restrictions:
     - The "T" and "Z" characters in this syntax MUST be upper case.
     - Usage of the "T" character is REQUIRED.
     - Leap seconds MUST NOT be used.
    <166>2013-04-05T13:49:31.685Z esx Vpxa: message....

    Variant 6: syslog message without date / host:
    <5>SYSTEM_INFO: [WLAN-1] Triggering Background Scan

    Variant 7: logwatch.ec event forwarding
    <78>@1341847712 Klapprechner /var/log/syslog: message....

    Variant 7a: Event simulation
    <%PRI%>@%TIMESTAMP%;%SL% %HOSTNAME% %syslogtag%: %msg%

    Variant 8: syslog message from sophos firewall
    <84>2015:03:25-12:02:06 gw pluto[7122]: listening for IKE messages

    Variant 9: syslog message (RFC 5424)
    <134>1 2016-06-02T12:49:05.181+02:00 chrissw7 ChrisApp - TestID - coming from  java code

    Variant 10:
    2016 May 26 15:41:47 IST XYZ Ebra: %LINEPROTO-5-UPDOWN: Line protocol on Interface Ethernet45 (XXX.ASAD.Et45), changed state to up
    year month day hh:mm:ss timezone HOSTNAME KeyAgent:

    Variant 11: TP-Link T1500G-8T 2.0
        - space separated date and time instead of "T"
        - no ": " between header and message
        - https://github.com/rsyslog/rsyslog/issues/5148
    <133>2023-09-29 18:41:55 host 51890 Login the web by user on web (x.x.x.x).....

    FIXME: Would be better to parse the syslog messages in another way:
    Split the message by the first ":", then split the syslog header part
    and detect which information are present. Take a look at the syslog RFCs
    for details.
    """
    event = _make_event(line, ipaddress)
    # Variant 2,2a,3,4,5,6,7,7a,8
    if line.startswith("<"):
        i = line.find(">")
        prio = int(line[1:i])
        line = line[i + 1 :]
        event["facility"] = prio >> 3
        event["priority"] = prio & 7

    # Variant 1,1a
    else:
        event["facility"] = 1  # user
        event["priority"] = 5  # notice

    # Variant 7 and 7a
    if line[0] == "@" and line[11] in {" ", ";"} and line.split(" ", 1)[0].count(";") <= 1:
        details, host, line = line.split(" ", 2)
        event["host"] = HostName(host)
        detail_tokens = details.split(";")
        timestamp = detail_tokens[0]
        if len(detail_tokens) > 1:
            event["sl"] = int(detail_tokens[1])
        event["time"] = float(timestamp[1:])
        event.update(parse_syslog_info(line))

    # Variant 3
    elif line.startswith("@"):
        event.update(parse_monitoring_info(line))

    # Variant 5
    elif len(line) > 24 and line[10] == "T":
        timestamp, host, rest = line.split(" ", 2)
        event["host"] = HostName(host)
        event["time"] = parse_iso_8601_timestamp(timestamp)
        event.update(parse_syslog_info(rest))

    # Variant 11
    elif line[10] == " " and line[19] == " ":
        date, time, host, pid, rest = line.split(" ", 4)
        event["host"] = HostName(host)
        event["pid"] = int(pid)
        event["time"] = parse_iso_8601_timestamp(f"{date}T{time}")
        event["text"] = rest

    # Variant 9
    elif len(line) > 24 and line[12] == "T":
        event.update(parse_rfc5424_syslog_info(line))

    # Variant 8
    elif line[10] == "-" and line[19] == " ":
        timestamp, host, rest = line.split(" ", 2)
        event["host"] = HostName(host)
        timestamp = fix_broken_sophos_timestamp(timestamp)
        event["time"] = parse_iso_8601_timestamp(timestamp)
        event.update(parse_syslog_info(rest))

    # Variant 6
    elif len(line.split(": ", 1)[0].split(" ")) == 1:
        event.update(parse_syslog_info(line))
        # There is no datetime information in the message, use current time
        event["time"] = _time()
        # There is no host information, use the provided address
        event["host"] = HostAddress(ipaddress)

    # Variant 10
    elif line[4] == " " and line[:4].isdigit():
        time_part = line[:20]  # ignoring tz info
        host, application, line = line[25:].split(" ", 2)
        event["host"] = HostName(host)
        event["application"] = application.rstrip(":")
        event["pid"] = 0
        event["text"] = line
        event["time"] = mktime(strptime(time_part, "%Y %b %d %H:%M:%S"))

    # Variant 1,1a,2,2a,4
    else:
        month_name, day, timeofday, rest = line.split(None, 3)

        # Special handling for variant 1a. Detect whether or not host
        # is a hostname or syslog tag
        host, tmp_rest = rest.split(None, 1)
        if host.endswith(":"):
            # There is no host information sent, use the source address as "host"
            host = ipaddress
        else:
            # Use the extracted host and continue with the remaining message text
            rest = tmp_rest

        event["host"] = HostName(host)

        # Variant 4
        if rest.startswith("@"):
            # TODO: host gets overwritten, strange... Is this OK?
            event.update(parse_monitoring_info(rest))

        # Variant 1, 2, 2a
        else:
            event.update(parse_syslog_info(rest))

            month = _MONTH_NAMES[month_name]
            iday = int(day)

            # Nasty: the year is not contained in the message. We cannot simply
            # assume that the message if from the current year.
            lt = localtime()
            if lt.tm_mon < 6 < month:  # Assume that message is from last year
                year = lt.tm_year - 1
            else:
                year = lt.tm_year  # Assume the current year

            hours, minutes, seconds = map(int, timeofday.split(":"))

            # With the -1 the mktime will correctly set the DST value
            # see: https://stackoverflow.com/questions/13464009/calculate-tm-isdst-from-date-and-timezone
            # see: https://docs.python.org/3/library/time.html#time.mktime
            event["time"] = mktime((year, month, iday, hours, minutes, seconds, 0, 0, -1))

    # The event simulator ships the simulated original IP address in the
    # hostname field, separated with a pipe, e.g. "myhost|1.2.3.4"
    if isinstance(event["host"], str) and "|" in event["host"]:
        host, ipaddress = event["host"].split("|", 1)
        event["host"] = HostName(host)
        event["ipaddress"] = str(ipaddress)
    return event


_MONTH_NAMES = {
    "Jan": 1,
    "Feb": 2,
    "Mar": 3,
    "Apr": 4,
    "May": 5,
    "Jun": 6,
    "Jul": 7,
    "Aug": 8,
    "Sep": 9,
    "Oct": 10,
    "Nov": 11,
    "Dec": 12,
}


def parse_syslog_info(content: str) -> Event:
    """
    Replaced ":" by ": " here to make tags with ":" possible. This
    is needed to process logs generated by windows agent logfiles
    like "c://test.log".
    """
    parts = content.split(": ", 1)
    if len(parts) == 1:  # no TAG at all
        application = ""
        pid = 0
        text = content.strip()
    elif "[" in parts[0]:  # TAG followed by pid
        application, pid_str = parts[0].rsplit("[", 1)
        application = application.lstrip("[").rstrip("]")
        try:
            pid = int(pid_str.rstrip("]"))
        except ValueError:
            pid = 0
        text = parts[1].strip()
    else:  # TAG not followed by pid
        application = parts[0]
        pid = 0
        text = parts[1].strip()
    return Event(
        application=application,
        pid=pid,
        text=text,
    )


def parse_monitoring_info(line: str) -> Event:
    event = Event()
    # line starts with '@'
    if line[11] == ";":
        timestamp_str, sl, contact, rest = line[1:].split(";", 3)
        host, rest = rest.split(None, 1)
        if len(sl):
            event["sl"] = int(sl)
        if len(contact):
            event["contact"] = contact
    else:
        timestamp_str, host, rest = line[1:].split(None, 2)

    event["time"] = float(int(timestamp_str))
    service, message = rest.split(": ", 1)
    event["application"] = service
    event["text"] = message.strip()
    event["host"] = HostName(host)
    event["pid"] = 0
    return event


def parse_rfc5424_syslog_info(line: str) -> Event:
    event = Event()
    (
        _unused_version,
        timestamp,
        hostname,
        app_name,
        procid,
        _unused_msgid,
        sd_and_message,
    ) = line.split(" ", 6)
    nil_value = "-"  # SyslogMessage.nilvalue()
    event["time"] = _time() if timestamp == nil_value else parse_iso_8601_timestamp(timestamp)
    event["host"] = HostName("" if hostname == nil_value else hostname)
    event["application"] = "" if app_name == nil_value else app_name
    event["pid"] = 0 if procid == nil_value else int(procid)

    structured_data, message = split_syslog_structured_data_and_message(sd_and_message)
    message = remove_leading_bom(message)
    if structured_data:
        event_update, remaining_structured_data = parse_syslog_message_structured_data(
            structured_data
        )
        # TODO: Fix the typing chaos below. We really need to parse the attributes.
        event.update(event_update)  # type: ignore[typeddict-item]
        # TODO: What about the other non-string attributes of an event?
        if (service_level := event.get("sl")) is not None:
            event["sl"] = int(service_level)
        event["text"] = (
            f"{(remaining_structured_data + ' ') if remaining_structured_data else ''}{message}"
        )
    else:
        event["text"] = message
    return event


def parse_iso_8601_timestamp(timestamp: str) -> float:
    return isoparse(timestamp).timestamp()


def fix_broken_sophos_timestamp(timestamp: str) -> str:
    """Sophos firewalls use a braindead non-standard timestamp format with funny separators and without a timezone."""
    # Step 1: Fix separator between date and time
    timestamp = timestamp.replace("-", "T", 1)
    # Step 2: Fix separators between date parts
    timestamp = timestamp.replace(":", "-", 2)
    # Step 3: Add explicit offset for local time
    offset = current_utcoffset_seconds()
    hours, minutes = divmod(abs(offset) // 60, 60)
    return timestamp + f"{'-' if offset < 0 else '+'}{hours:02}{minutes:02}"


def current_utcoffset_seconds() -> int:
    utcoffset = datetime.now(tzlocal()).utcoffset()
    # utcoffset is an 'aware' datetime object (we explicitly passed a timezone above),
    # but the typing is too weak to express this. As a consequence, we must help mypy.
    assert utcoffset is not None
    return round(utcoffset.total_seconds())


def remove_leading_bom(message: str) -> str:
    return message[1:] if message.startswith("\ufeff") else message


def split_syslog_structured_data_and_message(sd_and_message: str) -> tuple[str | None, str]:
    """Split a string containing structured data and the message into the two parts."""
    if sd_and_message.startswith("["):
        return _split_syslog_nonnil_sd_and_message(sd_and_message)
    nil_value = "-"  # SyslogMessage.nilvalue()
    if sd_and_message.startswith(f"{nil_value} "):
        return None, sd_and_message.split(" ", 1)[1]
    raise ValueError("Invalid RFC 5424 syslog message: structured data has the wrong format")


def _split_syslog_nonnil_sd_and_message(sd_and_message: str) -> tuple[str, str]:
    currently_outside_sd_element = True
    for idx, char in enumerate(sd_and_message):
        if char == "[" and currently_outside_sd_element:
            currently_outside_sd_element = False
        if char == "]" and sd_and_message[idx - 1] != "\\":
            currently_outside_sd_element = True
        if char == " " and currently_outside_sd_element:
            return sd_and_message[:idx], sd_and_message[idx + 1 :]
    # Special case: no message
    if currently_outside_sd_element:
        return sd_and_message, ""
    raise ValueError("Invalid RFC 5424 syslog message: structured data has the wrong format")


def parse_syslog_message_structured_data(structured_data: str) -> tuple[dict[str, str], str]:
    """Checks if the structured data contains Checkmk-specific data and extracts it if found."""
    checkmk_id = "Checkmk@18662"
    if not (checkmk_elements := findall(rf"\[{checkmk_id}.*?(?<!\\)\]", structured_data)):
        return {}, structured_data
    if len(checkmk_elements) != 1:
        raise ValueError(
            "Invalid RFC 5424 syslog message: Found Checkmk structured data element multiple times"
        )
    event_update = {}
    for sd_param in findall(r' .*?=".*?(?<!\\)"', checkmk_elements[0]):
        name, value = sd_param[1:].split("=", 1)
        event_update[name] = value[1:-1]
    return _unescape_parsed_struc(event_update), structured_data.replace(checkmk_elements[0], "")


def _unescape_parsed_struc(parsed_structured_data: Mapping[str, str]) -> dict[str, str]:
    return {
        key: _unescape_structured_data_value(value) for key, value in parsed_structured_data.items()
    }


def _unescape_structured_data_value(v: str, /) -> str:
    """Undo the escaping done in cmk.ec.forward.StructuredDataValue."""
    v_unescaped = v
    for escaped_char in ("\\", '"', "]"):
        v_unescaped = v_unescaped.replace(rf"\{escaped_char}", escaped_char)
    return v_unescaped


def scrub_string(s: str) -> str:
    """Rip out/replace any characters which have a special meaning in the UTF-8
    encoded history files, see e.g. quote_tab. In theory this shouldn't be
    necessary, because there are a bunch of bytes which are not contained in any
    valid UTF-8 string, but following Murphy's Law, those are not used in
    Checkmk. To keep backwards compatibility with old history files, we have no
    choice and continue to do it wrong... :-/.
    """
    return s.translate(_scrub_string_unicode_table)


_scrub_string_unicode_table = {0: None, 1: None, 2: None, ord("\n"): None, ord("\t"): ord(" ")}
