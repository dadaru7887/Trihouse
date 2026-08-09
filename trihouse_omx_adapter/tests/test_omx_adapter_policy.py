"""Gazebo OMX와 실기 OMX가 공유할 적재·비상·timeout 정책 테스트."""
from __future__ import annotations

import unittest

from trihouse_omx_adapter.policy import OmxAdapter, OmxState


class OmxAdapterPolicyTest(unittest.TestCase):
    """OMX 성공 응답을 독립 완료로 오인하지 않는지 검증한다."""

    def test_loading_requires_joint_readiness_and_physical_confirmation(self) -> None:
        adapter = OmxAdapter("OMX-01")
        self.assertFalse(adapter.start_loading(pinky_ready=False, omx_ready=True).accepted)
        self.assertTrue(adapter.start_loading(pinky_ready=True, omx_ready=True).accepted)
        self.assertEqual(OmxState.LOADING, adapter.state)
        self.assertFalse(adapter.complete_loading(gripper_open=True, safely_retracted=True, cargo_confirmed=False).accepted)
        self.assertTrue(adapter.complete_loading(gripper_open=True, safely_retracted=True, cargo_confirmed=True).accepted)
        self.assertEqual(OmxState.LOADED, adapter.state)

    def test_failure_timeout_and_emergency_hold_motion_until_operator_resolution(self) -> None:
        adapter = OmxAdapter("OMX-01")
        adapter.start_loading(pinky_ready=True, omx_ready=True)
        self.assertTrue(adapter.timeout().accepted)
        self.assertEqual(OmxState.HELD, adapter.state)
        self.assertFalse(adapter.start_loading(pinky_ready=True, omx_ready=True).accepted)
        self.assertTrue(adapter.operator_reset().accepted)
        adapter.start_loading(pinky_ready=True, omx_ready=True)
        self.assertTrue(adapter.emergency_stop().accepted)
        self.assertEqual(OmxState.EMERGENCY, adapter.state)
        self.assertFalse(adapter.operator_reset().accepted)

