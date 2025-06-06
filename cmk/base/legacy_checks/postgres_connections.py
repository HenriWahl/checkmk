#!/usr/bin/env python3
# Copyright (C) 2019 Checkmk GmbH - License: GNU General Public License v2
# This file is part of Checkmk (https://checkmk.com). It is subject to the terms and
# conditions defined in the file COPYING, which is part of this source code package.


from cmk.agent_based.legacy.v0_unstable import check_levels, LegacyCheckDefinition
from cmk.agent_based.v2 import IgnoreResultsError, render
from cmk.plugins.lib import postgres

check_info = {}

# OLD FORMAT - with idle filter
# <<<postgres_connections:sep(59)>>>
# [databases_start]
# postgres
# app
# app_test
# [databases_end]
# datname;current;mc
# app;0;100
# app_test;0;100
# postgres;1;100
# template0;0;100
# template1;0;100

# NEW FORMAT - without idle filter
# <<<postgres_connections:sep(59)>>>
# [databases_start]
# postgres
# app
# app_test
# [databases_end]
# datname;current;mc;state
# app;2;100;idle
# app_test;0;100;
# postgres;1;100;active
# template0;0;100;
# template1;0;100;

# instances
# <<<postgres_bloat>>>
# [[[foobar]]]
# [databases_start]
# postgres
# testdb
# [databases_end]
# ...


def _transform_params(params):
    # Transform old params: previously the levels refered to active connections only

    transformed_params = params.copy()
    for old_level in ("levels_abs", "levels_perc"):
        if old_level in transformed_params:
            transformed_params[f"{old_level}_active"] = transformed_params[old_level]

    return transformed_params


def inventory_postgres_connections(parsed):
    return [(db, {}) for db in parsed]


def check_postgres_connections(item, params, parsed):
    if item not in parsed:
        # In case of missing information we assume that the login into
        # the database has failed and we simply skip this check. It won't
        # switch to UNKNOWN, but will get stale.
        raise IgnoreResultsError("Login into database failed")

    transformed_params = _transform_params(params)

    database = parsed[item]
    if len(database) == 0:
        for connection_type in ("active", "idle"):
            warn, crit = transformed_params.get("levels_abs_%s" % connection_type, (0, 0))
            yield (
                0,
                "No %s connections" % connection_type,
                [
                    ("%s_connections" % connection_type, 0, warn, crit, 0, 0),
                ],
            )
        return

    database_connections = database[0]
    # New agent output differentiates between active and idle connections.
    # Previously, only number of active connections were sent
    has_active_and_idle = all(key in database_connections.keys() for key in ("active", "idle"))
    maximum = float(database_connections["mc"])

    connections = {
        "active": (
            database_connections["active"]
            if has_active_and_idle
            else database_connections["current"]
        ),
        "idle": database_connections["idle"] if has_active_and_idle else None,
    }

    for connection_type in ("active", "idle"):
        current = connections.get(connection_type)

        if not current:
            continue
        current = float(current)

        used_perc = current / maximum * 100

        warn, crit = transformed_params.get("levels_abs_%s" % connection_type, (None, None))
        yield check_levels(
            current,
            "%s_connections" % connection_type,
            (warn, crit),
            human_readable_func=int,
            infoname="Used %s connections" % connection_type,
            boundaries=(0, maximum),
        )

        warn, crit = transformed_params["levels_perc_%s" % connection_type]
        yield check_levels(
            used_perc,
            None,
            (warn, crit),
            human_readable_func=render.percent,
            infoname="Used %s percentage" % connection_type,
        )


check_info["postgres_connections"] = LegacyCheckDefinition(
    name="postgres_connections",
    parse_function=postgres.parse_dbs,
    service_name="PostgreSQL Connections %s",
    discovery_function=inventory_postgres_connections,
    check_function=check_postgres_connections,
    check_ruleset_name="db_connections",
    check_default_parameters={
        "levels_perc_active": (80.0, 90.0),  # Levels at 80%/90% of maximum
        "levels_perc_idle": (80.0, 90.0),  # Levels at 80%/90% of maximum
    },
)
