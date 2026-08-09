"""고위험 Gateway 요청의 역할 권한 검사를 위한 인수 테스트."""
from __future__ import annotations

import unittest

from control_tower.gateway.authorization import AuthorizationPolicy, Role


class AuthorizationPolicyTest(unittest.TestCase):
    def setUp(self) -> None:
        self.policy = AuthorizationPolicy()

    def test_only_designated_admin_can_release_emergency_response(self) -> None:
        """An identified but ordinary operator cannot clear an incident zone."""
        self.assertFalse(self.policy.allows(Role.OPERATOR, 'RELEASE_EMERGENCY'))
        self.assertTrue(self.policy.allows(Role.ADMIN, 'RELEASE_EMERGENCY'))

    def test_operator_can_acknowledge_but_not_change_high_risk_policy(self) -> None:
        """Acknowledgement is lower privilege than emergency release or map policy change."""
        self.assertTrue(self.policy.allows(Role.OPERATOR, 'ACKNOWLEDGE_INCIDENT'))
        self.assertFalse(self.policy.allows(Role.OPERATOR, 'EDIT_KEEP_OUT_ZONE'))


if __name__ == '__main__':
    unittest.main()
