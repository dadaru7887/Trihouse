"""Gateway 제어 요청의 최소 역할 권한 정책.

Identity provider/JWT 검증은 이 순수 정책의 밖에 둔다. HTTP adapter는 검증한 역할만 전달한다.
"""

from enum import StrEnum


class Role(StrEnum):
    VIEWER = 'VIEWER'
    OPERATOR = 'OPERATOR'
    ADMIN = 'ADMIN'


class AuthorizationPolicy:
    _MINIMUM_ROLE = {
        'ACKNOWLEDGE_INCIDENT': Role.OPERATOR,
        'CANCEL_JOB': Role.OPERATOR,
        'REASSIGN_JOB': Role.OPERATOR,
        'RELEASE_EMERGENCY': Role.ADMIN,
        'EDIT_KEEP_OUT_ZONE': Role.ADMIN,
    }

    def allows(self, role: Role, action: str) -> bool:
        required = self._MINIMUM_ROLE.get(action)
        if required is None:
            return False
        return self._rank(role) >= self._rank(required)

    @staticmethod
    def _rank(role: Role) -> int:
        return {Role.VIEWER: 0, Role.OPERATOR: 1, Role.ADMIN: 2}[role]
