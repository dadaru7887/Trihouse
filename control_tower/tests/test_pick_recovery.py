"""Operator-owned OMX pick recovery policy tests."""

from control_tower.task_manager.omx_workflow import PickRecovery


def test_recovery_exposes_exactly_retry_and_handle_at_packing() -> None:
    """Pick recovery never inherits intake-time partial-fulfilment behavior."""
    recovery = PickRecovery(item_id="item-1")
    recovery.record_failure("LOAD_UNCERTAIN")

    assert recovery.available_choices == ("재시도", "포장대에서 처리")


def test_operator_retry_reobserves_markers_and_resets_the_act_episode() -> None:
    """A selected retry starts from fresh perception and policy state."""
    recovery = PickRecovery(item_id="item-1")
    recovery.record_failure("GRASP_RETAINED")

    decision = recovery.select("재시도")

    assert decision.accepted is True
    assert decision.reobserve_qr_aruco is True
    assert decision.reset_act_episode is True
    assert decision.retry_no == 1


def test_at_most_two_operator_selected_retries_then_only_packing_handling() -> None:
    """A third retry is never exposed or accepted."""
    recovery = PickRecovery(item_id="item-1")
    for _ in range(2):
        recovery.record_failure("LOAD_UNCERTAIN")
        assert recovery.select("재시도").accepted is True

    recovery.record_failure("LOAD_UNCERTAIN")

    assert recovery.available_choices == ("포장대에서 처리",)
    assert recovery.select("재시도").accepted is False


def test_packing_handling_keeps_item_in_order_as_manual_required() -> None:
    """Manual packing is a fulfilment path, not removal from the order."""
    recovery = PickRecovery(item_id="item-1")
    recovery.record_failure("LOAD_UNCERTAIN")

    decision = recovery.select("포장대에서 처리")

    assert decision.accepted is True
    assert recovery.item_state == "MANUAL_FULFILLMENT_REQUIRED"
    assert recovery.item_in_order is True


def test_drop_blocks_retry_and_pinky_departure_until_both_recovery_facts() -> None:
    """A drop holds the workcell until object recovery and area-clear are explicit."""
    recovery = PickRecovery(item_id="item-1")

    dropped = recovery.record_failure("DROP_DETECTED")
    before_clear = recovery.select("재시도")
    recovery.record_object_recovered()
    still_held = recovery.select("재시도")
    recovery.record_area_clear()
    released = recovery.select("재시도")

    assert dropped.pinky_departure_allowed is False
    assert dropped.retry_allowed is False
    assert before_clear.accepted is False
    assert still_held.accepted is False
    assert released.accepted is True
