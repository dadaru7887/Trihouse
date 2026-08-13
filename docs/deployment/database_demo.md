# DB 스키마 시연

## 설명 순서

```text
MySQL 8.4 on RTX 4060
├─ trihouse_fms       # FMS 운영 원장
└─ trihouse_recovery  # episode/step 2개 테이블
```

`location_recovery_profiles`는 검증된 장소별 Reference Memory다.
`recovery_episodes`와 `recovery_steps`는 실행 결과를 남기는 Episodic Memory다.
두 database 사이에는 MySQL FK를 만들지 않고 식별자 snapshot과 Gateway 검증으로
결합도를 제한한다. recovery 내부에서는 step이 episode를 FK로 참조한다.

## 실행

```bash
cd /home/syw/Trihouse
docker compose -p trihouse_db -f compose.db.yaml up -d --wait mysql
docker compose -p trihouse_db -f compose.db.yaml ps
```

## database와 table 확인

```bash
docker compose -p trihouse_db -f compose.db.yaml exec mysql \
  mysql -uroot -p -e \
  "SHOW DATABASES LIKE 'trihouse_%';
   SELECT TABLE_SCHEMA, TABLE_NAME
   FROM information_schema.TABLES
   WHERE TABLE_SCHEMA IN ('trihouse_fms','trihouse_recovery')
   ORDER BY TABLE_SCHEMA, TABLE_NAME;"
```

비밀번호는 명령행에 직접 쓰지 않고 prompt에 입력한다. FMS 테이블은
`db/schema_mysql.sql`의 테이블 이름 집합을 기준으로 검증한다. recovery는
`recovery_episodes`, `recovery_steps` 두 테이블이다.

## recovery 관계 확인

```bash
docker compose -p trihouse_db -f compose.db.yaml exec mysql \
  mysql -uroot -p -e \
  "SELECT TABLE_SCHEMA, TABLE_NAME, CONSTRAINT_NAME,
          REFERENCED_TABLE_SCHEMA, REFERENCED_TABLE_NAME
   FROM information_schema.KEY_COLUMN_USAGE
   WHERE TABLE_SCHEMA='trihouse_recovery'
     AND REFERENCED_TABLE_NAME IS NOT NULL;"
```

기대 결과는 `recovery_steps → recovery_episodes` 한 관계이며,
`trihouse_recovery → trihouse_fms` 교차 DB FK는 없어야 한다.

## 영문 테이블·컬럼 설명 확인

Adminer에서 database를 선택하면 테이블 설명을, 테이블의 구조 화면에서는 컬럼
설명을 볼 수 있다. SQL로 전체 적용 여부를 확인하려면 다음을 실행한다.

```bash
docker compose -f compose.db.yaml exec mysql \
  sh -lc 'MYSQL_PWD="$MYSQL_ROOT_PASSWORD" mysql -uroot -e "
    SELECT TABLE_SCHEMA, COUNT(*) AS commented_tables
    FROM information_schema.TABLES
    WHERE TABLE_SCHEMA IN (\"trihouse_fms\", \"trihouse_recovery\")
      AND TABLE_TYPE = \"BASE TABLE\"
      AND TABLE_COMMENT <> \"\"
    GROUP BY TABLE_SCHEMA;

    SELECT TABLE_SCHEMA, COUNT(*) AS commented_columns
    FROM information_schema.COLUMNS
    WHERE TABLE_SCHEMA IN (\"trihouse_fms\", \"trihouse_recovery\")
      AND COLUMN_COMMENT <> \"\"
    GROUP BY TABLE_SCHEMA;
  "'
```

개수를 고정값으로 비교하지 않고, `db/schema_mysql.sql`에 선언된 모든
테이블·컬럼에 빈 설명이 없고 ASCII 영문으로 작성됐는지 통합 테스트로
검증한다.

```bash
FMS_DB_HOST=127.0.0.1 FMS_DB_PORT=3307 \
FMS_DB_ADMIN_USER=root FMS_DB_ADMIN_PASSWORD=test_root_password \
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 \
/tmp/fms-gateway-venv/bin/python -m pytest -v \
  fms_gateway/tests/integration/test_schema.py
```

## 창고·선반·QR 재고 확인

`db/seed_dev.sql`을 적용하면 3개 창고의 L1/L2·S01/S02 선반과
11개 QR 재고 lot이 생성된다. 상온 창고의 `AMB-L1-S02`는 빈 선반으로
남는다. 다음 조회의 11개 lot이
`docs/database/item_qr_payloads.json`과 일치해야 한다.

```bash
docker compose -f compose.db_test.yaml exec -T mysql_test \
  mysql -ufms_gateway -ptest_gateway_password trihouse_fms -e "
SELECT
  lot.lot_code, lot.product_code, lot.item_name,
  lot.available_qty, lot.reserved_qty,
  slot.location_code AS slot_code,
  parent.location_code AS warehouse_code,
  JSON_UNQUOTE(JSON_EXTRACT(slot.metadata, '$.shelf_level')) AS shelf_level,
  JSON_UNQUOTE(JSON_EXTRACT(slot.metadata, '$.slot_index')) AS slot_index
FROM inventory_lots lot
JOIN locations slot ON slot.location_id = lot.location_id
LEFT JOIN locations parent ON parent.location_id = slot.parent_location_id
ORDER BY warehouse_code, shelf_level, slot_index;"
```

창고와 선반의 `map_name`, `rmf_waypoint_name`, `pose_x`, `pose_y`,
`pose_yaw`는 UI에서 waypoint를 정한 뒤 연결한다. 시드 단계에서는 `NULL`이
정상이다.

## 초기화 주의

`docker-entrypoint-initdb.d`는 named volume이 비어 있을 때만 실행된다. 스키마를
바꾼 뒤 container를 restart하는 것만으로 기존 DB는 갱신되지 않는다. 운영 데이터는
migration을 사용하고, 개발 볼륨 삭제는 백업과 명시적 승인을 거친다.
이미 생성된 DB를 갱신할 때는 현재 운영 데이터에 맞는 migration을 별도로
작성해야 한다.
