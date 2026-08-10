# Robosapiens 문서

이 디렉터리는 Robosapiens의 요구사항, 아키텍처, 배포, 개발 계약, 검증 증거를
관리하는 기준 문서 모음이다. 과거 문서와 생성 산출물은 `archive/`에 로컬로
보존하며 현재 기준으로 사용하지 않는다.

## 읽는 순서

1. [시스템 구성](architecture/system_overview.md)
2. [System Requirements](requirements/system_requirements.md)
3. [SR 구현·검증 상태](validation/implementation_map.md)
4. [Pinky SR 수동 검증](validation/pinky_sr_manual_validation.md)
5. [환경 구성](deployment/environment_overview.md)
6. [로컬 시뮬레이션](deployment/local_simulation_demo.md)
7. [데이터베이스](database/database_guide.md)

## 문서 영역

- `requirements/`: 사용자·시스템·Pinky 요구사항과 업무 흐름 원본
- `architecture/`: 시스템 책임, 권한 경계, 데이터 흐름
- `database/`: MySQL 스키마 운영 규칙과 편집 가능한 산출물
- `deployment/`: 현재 PC와 RTX 4060·5080 설치 및 실행 절차
- `development/`: 코드 변경 시작점과 컴포넌트 간 계약
- `validation/`: SR 구현 상태, 테스트 계획, 실행 증거
- `archive/`: 리팩터링 전 자료를 보존하는 Git 제외 로컬 snapshot

`pinky_pro/`와 `control_system/`은 변경하지 않는 외부 기준 코드다. 현재 구현
상태는 요구사항 문서가 아니라 `validation/implementation_map.md`에서 관리한다.
