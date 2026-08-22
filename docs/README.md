# Robosapiens 문서

이 디렉터리는 Robosapiens의 현재 요구사항, 아키텍처, 배포, 개발 계약과 검증
절차를 관리하는 기준 문서 모음이다. 완료된 계획, 세션 인수인계와 과거 실행 기록은
별도 복사본을 두지 않고 Git 이력에서 확인한다.

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
- `runbooks/`: 현재 시뮬레이션·실기 실행 및 실측 절차
- `validation/`: SR 구현 상태, 테스트 계획과 현재 검증 절차
- `superpowers/`: 현재 브랜치에서 아직 유효한 설계와 구현 계획

`pinky_pro/`와 `control_system/`은 변경하지 않는 외부 기준 코드다. 현재 구현
상태는 요구사항 문서가 아니라 `validation/implementation_map.md`에서 관리한다.
