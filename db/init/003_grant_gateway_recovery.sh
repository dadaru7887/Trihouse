# This file is sourced by the MySQL Docker entrypoint during first initialization.
# It grants the Gateway runtime access to the recovery database.

case "${MYSQL_USER:-}" in
  ""|*[!a-zA-Z0-9_]*)
    mysql_error "MYSQL_USER must contain only letters, digits, and underscores"
    ;;
esac

docker_process_sql --database=mysql <<-EOSQL
GRANT SELECT, INSERT, UPDATE, DELETE
ON \`trihouse_recovery\`.*
TO '${MYSQL_USER}'@'%';
EOSQL
