#!/usr/bin/env python3
# Copyright (C) 2019 Checkmk GmbH - License: GNU General Public License v2
# This file is part of Checkmk (https://checkmk.com). It is subject to the terms and
# conditions defined in the file COPYING, which is part of this source code package.

#
# 2019-01-17, comNET GmbH, Fabian Binder
"""
Special agent for monitoring Zerto application with Check_MK.
"""

import argparse
import logging
import sys
from collections.abc import Sequence

import requests

from cmk.utils.password_store import replace_passwords

LOGGER = logging.getLogger(__name__)


def parse_arguments(argv: Sequence[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)

    # flags
    parser.add_argument(
        "-a", "--authentication", default="windows", type=str, help="Authentication method"
    )
    parser.add_argument(
        "-d", "--debug", action="store_true", help="Debug mode: raise Python exceptions"
    )
    parser.add_argument("-v", "--verbose", action="count", help="Be more verbose")
    parser.add_argument("-u", "--username", required=True, help="Zerto user name")
    parser.add_argument("-p", "--password", required=True, help="Zerto user password")
    parser.add_argument("hostaddress", help="Zerto host name")

    args = parser.parse_args(argv)

    if args.verbose and args.verbose >= 2:
        fmt = "%(levelname)s: %(name)s: %(filename)s: %(lineno)s %(message)s"
        lvl = logging.DEBUG
    elif args.verbose:
        fmt = "%(levelname)s: %(message)s"
        lvl = logging.INFO
    else:
        fmt = "%(levelname)s: %(message)s"
        lvl = logging.WARNING
    logging.basicConfig(level=lvl, format=fmt)

    return args


class ZertoRequest:
    def __init__(self, connection_url: str, session_id: str | None) -> None:
        self._endpoint = "%s/vms" % connection_url
        self._headers = {"x-zerto-session": session_id, "content-type": "application/json"}

    def get_vms_data(self) -> Sequence[dict[str, str]]:
        response = requests.get(  # nosec B501 # BNS:016141
            self._endpoint, headers=self._headers, verify=False, timeout=900
        )

        if response.status_code != 200:
            LOGGER.debug("response status code: %s", response.status_code)
            LOGGER.debug("response : %s", response.text)
            raise RuntimeError("Call to ZVM failed")
        try:
            data = response.json()
        except ValueError:
            LOGGER.debug("failed to parse json")
            LOGGER.debug("response : %s", response.text)
            raise ValueError("Got invalid data from host")
        return data


class ZertoConnection:
    def __init__(self, hostaddress: str, username: str, password: str) -> None:
        self._credentials = username, password
        self._host = hostaddress
        self.base_url = "https://%s:9669/v1" % self._host

    def get_session_id(self, authentication: str) -> str | None:
        url = "%s/session/add" % self.base_url
        if authentication == "windows":
            response = requests.post(  # nosec B501 # BNS:016141
                url, auth=self._credentials, verify=False, timeout=900
            )
        else:
            headers = {"content-type": "application/json"}
            response = requests.post(  # nosec B501 # BNS:016141
                url, auth=self._credentials, headers=headers, verify=False, timeout=900
            )

        if response.status_code != 200:
            LOGGER.info("response status code: %s", response.status_code)
            LOGGER.debug("response text: %s", response.text)
            raise AuthError("Failed authenticating to the Zerto Virtual Manager")

        if "x-zerto-session" not in response.headers:
            LOGGER.info("session id not found in response header")
            LOGGER.debug("response header: %s", response.headers)
            LOGGER.debug("response text: %s", response.text)
        return response.headers.get("x-zerto-session")


class AuthError(Exception):
    pass


def main(argv: Sequence[str] | None = None) -> int:
    replace_passwords()
    args = parse_arguments(argv or sys.argv[1:])
    sys.stdout.write("<<<zerto_agent:sep(0)>>>\n")
    try:
        connection = ZertoConnection(args.hostaddress, args.username, args.password)
        session_id = connection.get_session_id(args.authentication)
    except Exception as e:
        sys.stdout.write(f"Error: {e}\n")
        return 1
    sys.stdout.write("Initialized OK\n")

    request = ZertoRequest(connection.base_url, session_id)
    vm_data = request.get_vms_data()
    for vm in vm_data:
        try:
            sys.stdout.write("<<<<{}>>>>\n".format(vm["VmName"]))
            sys.stdout.write("<<<zerto_vpg_rpo:sep(124)>>>\n")
            sys.stdout.write("{}|{}|{}\n".format(vm["VpgName"], vm["Status"], vm["ActualRPO"]))
            sys.stdout.write("<<<<>>>>\n")
        except KeyError:
            continue
    return 0
