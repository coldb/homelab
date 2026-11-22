-- CNPG runs this once as postgres in database planner, before managed roles.
-- Passwords are subsequently reconciled from separate CNPG-managed Secrets.
CREATE ROLE planner_migrator LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION;
CREATE ROLE planner_api LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION;
REVOKE ALL ON DATABASE planner FROM PUBLIC;
REVOKE ALL ON SCHEMA public FROM PUBLIC;
GRANT CONNECT ON DATABASE planner TO planner_db_owner, planner_migrator, planner_api;
GRANT CREATE ON DATABASE planner TO planner_migrator;
CREATE SCHEMA planner AUTHORIZATION planner_migrator;
REVOKE ALL ON SCHEMA planner FROM PUBLIC;
GRANT USAGE ON SCHEMA planner TO planner_api;
-- The checked-in Planner migrations grant access to individual runtime tables.
