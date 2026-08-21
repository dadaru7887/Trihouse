#!/usr/bin/env bash
set -euo pipefail

baseline_path="/docker-entrypoint-initdb.d/001_schema.sql"
baseline_sha256="$(sha256sum "${baseline_path}")"
baseline_sha256="${baseline_sha256%% *}"

# EN: Record the digest after schema creation so later runners can detect an edited immutable baseline.
# KO: 스키마 생성 뒤 해시를 기록하여 이후 실행기가 변경된 불변 기준선을 감지하게 한다.
MYSQL_PWD="${MYSQL_ROOT_PASSWORD}" mysql --protocol=socket -uroot trihouse_fms <<SQL
INSERT INTO schema_migrations (version, filename, sha256)
VALUES (1, '001_physical_v1_baseline.sql', '${baseline_sha256}');
SQL
