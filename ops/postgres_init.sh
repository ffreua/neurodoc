#!/bin/sh
set -eu
export ND_OWNER_PASSWORD="$(cat /run/secrets/NEURODOC_DB_OWNER_PASSWORD)"
export ND_APP_PASSWORD="$(cat /run/secrets/NEURODOC_DB_APP_PASSWORD)"
psql -v ON_ERROR_STOP=1 --username postgres --dbname neurodoc -q <<'SQL'
SET log_min_error_statement = 'panic';
\getenv owner_password ND_OWNER_PASSWORD
\getenv app_password ND_APP_PASSWORD
CREATE ROLE neurodoc_owner LOGIN PASSWORD :'owner_password';
CREATE ROLE neurodoc_app LOGIN PASSWORD :'app_password';
REVOKE CREATE ON SCHEMA public FROM PUBLIC;
GRANT USAGE, CREATE ON SCHEMA public TO neurodoc_owner;
GRANT USAGE ON SCHEMA public TO neurodoc_app;
GRANT CONNECT ON DATABASE neurodoc TO neurodoc_owner, neurodoc_app;
ALTER DEFAULT PRIVILEGES FOR ROLE neurodoc_owner IN SCHEMA public
  GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO neurodoc_app;
ALTER DEFAULT PRIVILEGES FOR ROLE neurodoc_owner IN SCHEMA public
  GRANT USAGE, SELECT ON SEQUENCES TO neurodoc_app;
CREATE EXTENSION IF NOT EXISTS btree_gist;
SQL
unset ND_OWNER_PASSWORD ND_APP_PASSWORD
