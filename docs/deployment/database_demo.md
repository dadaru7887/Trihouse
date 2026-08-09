# DB 스키마 시연

## 설명 순서

```text
MySQL 8.4 on RTX 4060
├─ trihouse_fms       # 운영 원장 16개 테이블
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

비밀번호는 명령행에 직접 쓰지 않고 prompt에 입력한다. 기대 개수는 FMS 16,
recovery 2다.

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

## 한국어 테이블·컬럼 설명 확인

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

두 database를 합친 기대 결과는 테이블 18개, 컬럼 253개다. 설명 원본과 문서의
동기화 여부는 다음 명령으로 확인한다.

```bash
python3 db/tools/sync_schema_comments.py --check
```

## 초기화 주의

`docker-entrypoint-initdb.d`는 named volume이 비어 있을 때만 실행된다. 스키마를
바꾼 뒤 container를 restart하는 것만으로 기존 DB는 갱신되지 않는다. 운영 데이터는
migration을 사용하고, 개발 볼륨 삭제는 백업과 명시적 승인을 거친다.
이번 v4 한국어 설명 마이그레이션은
`db/migrations/004_add_korean_comments.sql`이며 데이터 행을 삭제하지 않는다.
