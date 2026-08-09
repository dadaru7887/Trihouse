# Trihouse
3온도상황 (상온/냉장/냉동) 물류센터를 위한 멀티로봇 관제 시스템

문서의 시작점은 [Robosapiens 문서](docs/README.md)다. 환경 구성은
[환경 개요](docs/deployment/environment_overview.md), DB 구조와 실행은
[데이터베이스 가이드](docs/database/database_guide.md)를 따른다. UI는 DB에 직접
접속하지 않으며 Gateway API를 통해 재고를 조회·조정한다.
