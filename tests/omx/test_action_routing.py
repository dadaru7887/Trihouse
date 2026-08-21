import pytest

from trihouse_omx_adapter.action_client import action_endpoint_for_device


@pytest.mark.parametrize(
    ("device_id", "endpoint"),
    (("OMX_01", "/omx_01/execute"), ("OMX_02", "/omx_02/execute")),
)
def test_canonical_device_id_selects_one_action_endpoint(device_id, endpoint) -> None:
    assert action_endpoint_for_device(device_id) == endpoint


@pytest.mark.parametrize("device_id", ("omx_01", "OMX-01", "OMX_1", "OMX_01/evil"))
def test_noncanonical_device_ids_are_rejected(device_id) -> None:
    with pytest.raises(ValueError):
        action_endpoint_for_device(device_id)
