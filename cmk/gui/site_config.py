#!/usr/bin/env python3
# Copyright (C) 2019 Checkmk GmbH - License: GNU General Public License v2
# This file is part of Checkmk (https://checkmk.com). It is subject to the terms and
# conditions defined in the file COPYING, which is part of this source code package.

from __future__ import annotations

from livestatus import SiteConfiguration, SiteConfigurations

from cmk.ccc.site import omd_site, SiteId

import cmk.utils.paths

from cmk.gui.config import active_config


def sitenames() -> list[SiteId]:
    return list(active_config.sites)


# TODO: Cleanup: Make clear that this function is used by the status GUI (and not WATO)
# and only returns the currently enabled sites. Or should we redeclare the "disabled" state
# to disable the sites at all?
def enabled_sites() -> SiteConfigurations:
    return SiteConfigurations(
        {
            name: active_config.sites[name]
            for name in sitenames()
            if not active_config.sites[name].get("disabled", False)
        }
    )


def configured_sites() -> SiteConfigurations:
    return SiteConfigurations({site_id: active_config.sites[site_id] for site_id in sitenames()})


def has_wato_slave_sites() -> bool:
    return bool(wato_slave_sites())


def is_wato_slave_site() -> bool:
    return _has_distributed_wato_file() and not has_wato_slave_sites()


def _has_distributed_wato_file() -> bool:
    path = cmk.utils.paths.check_mk_config_dir / "distributed_wato.mk"
    return path.exists() and path.stat().st_size != 0


def get_login_sites() -> list[SiteId]:
    """Returns the Setup slave sites a user may login and the local site"""
    return get_login_slave_sites() + [omd_site()]


# TODO: All site listing functions should return the same data structure, e.g. a list of
#       pairs (site_id, site)
def get_login_slave_sites() -> list[SiteId]:
    """Returns a list of site ids which are Setup slave sites and users can login"""
    login_sites = []
    for site_id, site_spec in wato_slave_sites().items():
        if site_spec.get("user_login", True) and not site_is_local(
            active_config.sites[site_id], site_id
        ):
            login_sites.append(site_id)
    return login_sites


def is_replication_enabled(site_config: SiteConfiguration) -> bool:
    return bool(site_config.get("replication"))


def get_replication_site_id(site_config: SiteConfiguration) -> str:
    return replication if (replication := site_config.get("replication")) else ""


def wato_slave_sites() -> SiteConfigurations:
    return SiteConfigurations(
        {site_id: s for site_id, s in active_config.sites.items() if is_replication_enabled(s)}
    )


def site_is_local(site_config: SiteConfiguration, site_id: SiteId) -> bool:
    socket_info = site_config["socket"]
    if isinstance(socket_info, str):
        # Should be unreachable
        return False

    if socket_info[0] == "local":
        return True

    if socket_info[0] == "unix":
        return socket_info[1]["path"] == str(cmk.utils.paths.livestatus_unix_socket)

    return False


def is_single_local_site() -> bool:
    if len(active_config.sites) > 1:
        return False
    if len(active_config.sites) == 0:
        return True

    # Also use Multisite mode if the one and only site is not local
    sitename = list(active_config.sites.keys())[0]
    return site_is_local(active_config.sites[sitename], sitename)


def wato_site_ids() -> list[SiteId]:
    return [
        omd_site(),
        *wato_slave_sites(),
    ]
