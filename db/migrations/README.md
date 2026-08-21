# Database migrations

`001_physical_v1_baseline.sql`은 첫 실물 테스트의 전체 스키마다. 새 DB는 이 파일
하나로 생성되며, Docker 초기화는 실제 파일 SHA-256을 `schema_migrations`에
기록한다.

`001`을 적용한 뒤에는 내용을 수정하지 않는다. 다음 변경은 현재 스키마와 기존
데이터를 모두 보존하는 `002_<purpose>.sql`로 추가하고, 이후 `003`, `004` 순서로
증가시킨다. migration 실행기는 적용 전 다음을 확인해야 한다.

1. DB에 기록된 기존 filename과 SHA-256이 로컬 파일과 일치한다.
2. 아직 적용하지 않은 번호가 중간 번호를 건너뛰지 않는다.
3. SQL이 성공한 같은 배포 절차에서 새 version, filename, SHA-256을 기록한다.
4. 이미 기록된 version의 파일 내용이 다르면 실행을 중단한다.

첫 기준선 이전에 사용한 upgrade SQL은 `db/archive/pre_physical_v1`에 보존한다.
그 파일들은 기존 개발 DB의 변천 근거이며 `001` 이후 DB에 다시 실행하지 않는다.

새 Docker DB는 `db/init/003_apply_physical_migrations.sh`가 `002` 이후 파일을
번호순으로 적용하고 SHA-256을 기록한다. 기존 volume에는 init 스크립트가 다시
실행되지 않으므로, 배포 전에 동일 스크립트를 DB 컨테이너에서 명시적으로 실행한다.
