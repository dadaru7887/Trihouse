# Trihouse
3온도상황 (상온/냉장/냉동) 물류센터를 위한 멀티로봇 관제 시스템

MySQL `trihouse_fms`와 FMS Gateway, Flutter 관제 UI를 함께 실행하는 절차는
[FMS Gateway 개발 환경 구성](docs/setup/fms-gateway-setup.md)을 따른다. UI는 DB에
직접 접속하지 않으며 Gateway API를 통해 재고를 조회·조정한다.
