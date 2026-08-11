# Status 정책 한국어 주석 설계

## 목표

`status.py`의 실행 동작을 유지하면서 `StatusInputs`, `StatusSummary`, `build_status()`의 역할과 데이터 흐름을 한국어로 이해할 수 있게 한다.

## 변경 범위

- 모듈 docstring에서 이 파일이 ROS 토픽을 직접 구독하지 않는 순수 정책임을 설명한다.
- `dataclass` import와 `frozen=True`의 의미를 주석으로 설명한다.
- `StatusInputs`와 각 필드가 나타내는 입력을 한국어 docstring 및 인라인 주석으로 설명한다.
- `StatusSummary`와 각 필드가 나타내는 판정 결과를 설명한다.
- `build_status()`의 입력, 반환값, stale 오류 생성, `ready` 판정 과정을 설명한다.
- 복잡한 comprehension은 기존 실행 구조를 유지하며 주변 주석으로 해설한다.

## 비변경 사항

- 클래스 및 함수의 이름, 타입, 기본값과 반환값을 바꾸지 않는다.
- 오류 문자열과 오류 생성 순서를 바꾸지 않는다.
- `status_node.py`, `pinky_pro`, `control_system`을 수정하지 않는다.

## 검증

Python 구문 검사를 실행하고, 편집 전후의 실행 가능한 AST가 동일한지 비교한다. `git diff --check`로 공백 오류와 대상 파일 범위를 확인한다.
