// Copyright (C) 2025 Checkmk GmbH - License: GNU General Public License v2
// This file is part of Checkmk (https://checkmk.com). It is subject to the terms and
// conditions defined in the file COPYING, which is part of this source code package.

use crate::config::{self, ora_sql::AuthType, ora_sql::Endpoint};
use crate::types::{HostName, PointName, Port};
use anyhow::Result;

use crate::config::ora_sql::Authentication;
// use oracle::{Connection, Error};

#[derive(Debug)]
pub struct StdBackend {}

#[derive(Debug)]
pub struct SqlPlusBackend {}

#[derive(Debug)]
pub struct JdbcBackend {}

#[derive(Debug)]
pub enum Backend {
    Std(StdBackend),
    SqlPlus(SqlPlusBackend),
    Jdbc(JdbcBackend),
}

#[derive(Debug)]
pub struct Target {
    pub host: HostName,
    pub point: PointName,
    pub port: Port,
    pub auth: Authentication,
}

#[derive(Debug, Default)]
pub struct TaskBuilder {
    target: Option<Target>,
    backend: Option<Backend>,
    database: Option<String>,
}

#[derive(Debug)]
pub struct Task {
    target: Target,
    backend: Backend,
    _database: Option<String>,
}

impl Task {
    pub fn connect(&self) -> Result<()> {
        match &self.backend {
            Backend::Std(_) => Ok(()),
            Backend::SqlPlus(_) => anyhow::bail!("JDBC backend is not implemented yet"),
            Backend::Jdbc(_) => anyhow::bail!("JDBC backend is not implemented yet"),
        }
    }
    pub fn target(&self) -> &Target {
        &self.target
    }

    pub fn backend(&self) -> &Backend {
        &self.backend
    }

    pub fn database(&self) -> Option<&String> {
        self._database.as_ref()
    }
}

impl TaskBuilder {
    pub fn new() -> TaskBuilder {
        TaskBuilder::default()
    }

    pub fn database<S: Into<String>>(mut self, database: Option<S>) -> Self {
        self.database = database.map(|d| d.into());
        self
    }

    pub fn target(mut self, endpoint: &Endpoint) -> Self {
        self.target = Some(Target {
            host: endpoint.hostname().clone(),
            point: endpoint.conn().point().clone(),
            port: endpoint.port().clone(),
            auth: endpoint.auth().clone(),
        });
        self
    }

    pub fn backend(mut self, backend: Backend) -> Self {
        self.backend = Some(backend);
        self
    }

    pub fn build(self) -> Result<Task> {
        Ok(Task {
            backend: self
                .backend
                .ok_or_else(|| anyhow::anyhow!("Backend not defined"))?,
            target: self
                .target
                .ok_or_else(|| anyhow::anyhow!("Target is absent"))?,
            _database: self.database,
        })
    }
}

#[derive(Debug)]
pub struct Credentials {
    pub user: String,
    pub password: String,
}

pub fn make_task(endpoint: &Endpoint) -> Result<Task> {
    TaskBuilder::new()
        .target(endpoint)
        .backend(Backend::SqlPlus(SqlPlusBackend {}))
        .build()
}

pub fn make_custom_task(endpoint: &Endpoint, point_name: &PointName) -> Result<Task> {
    make_task(endpoint).map(|mut t| {
        t.target.point = point_name.clone();
        t
    })
}

pub fn obtain_config_credentials(auth: &config::ora_sql::Authentication) -> Option<Credentials> {
    match auth.auth_type() {
        AuthType::Standard | AuthType::Kerberos => Some(Credentials {
            user: auth.username().to_string(),
            password: auth
                .password()
                .map(|s| s.as_str())
                .unwrap_or("")
                .to_string(),
        }),
        AuthType::Os => None,
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::config::ora_sql::Config;

    fn make_config_with_auth_type(auth_type: &str) -> Config {
        const BASE: &str = r#"
---
oracle:
  main:
    authentication:
       username: "bad_user"
       password: "bad_password"
       type: type_tag
    connection:
       hostname: "localhost" # we use real host to avoid long timeout
       port: 65345 # we use weird port to avoid connection
       instance: XE
       timeout: 1
"#;
        Config::from_string(&BASE.replace("type_tag", auth_type))
            .unwrap()
            .unwrap()
    }

    #[test]
    fn test_create_client_from_config_for_error() {
        let c = make_config_with_auth_type("bad");
        let task = make_task(&c.endpoint());
        assert!(task.is_ok());
    }

    #[test]
    fn test_create_client_from_config_correct() {
        let config = make_config_with_auth_type("standard");
        assert!(make_task(&config.endpoint()).is_ok());
    }

    #[test]
    fn test_obtain_credentials_from_config() {
        assert!(obtain_config_credentials(make_config_with_auth_type("os").auth()).is_none());
        assert!(obtain_config_credentials(make_config_with_auth_type("kerberos").auth()).is_some());
        assert!(obtain_config_credentials(make_config_with_auth_type("standard").auth()).is_some());
    }
}
