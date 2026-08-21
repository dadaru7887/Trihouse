#!/usr/bin/env bash
set -euo pipefail

migration_dir="/trihouse-migrations"

for migration_path in "${migration_dir}"/[0-9][0-9][0-9]_*.sql; do
  [[ -e "${migration_path}" ]] || continue
  filename="$(basename "${migration_path}")"
  version="${filename%%_*}"
  version="$((10#${version}))"
  sha256="$(sha256sum "${migration_path}")"
  sha256="${sha256%% *}"
  recorded="$({ MYSQL_PWD="${MYSQL_ROOT_PASSWORD}" mysql --protocol=socket -N -B -uroot trihouse_fms \
    -e "SELECT CONCAT(filename, ':', sha256) FROM schema_migrations WHERE version = ${version}"; } || true)"

  if [[ -n "${recorded}" ]]; then
    if [[ "${recorded}" != "${filename}:${sha256}" ]]; then
      echo "migration ${version} digest mismatch: ${recorded}" >&2
      exit 1
    fi
    continue
  fi

  if (( version == 1 )); then
    echo "baseline migration is not recorded" >&2
    exit 1
  fi

  MYSQL_PWD="${MYSQL_ROOT_PASSWORD}" mysql --protocol=socket -uroot trihouse_fms < "${migration_path}"
  MYSQL_PWD="${MYSQL_ROOT_PASSWORD}" mysql --protocol=socket -uroot trihouse_fms <<SQL
INSERT INTO schema_migrations (version, filename, sha256)
VALUES (${version}, '${filename}', '${sha256}');
SQL
done
