from scripts.p0_map_publish_config import (
    map_project_name,
    map_projects_api_base,
    physical_features_file,
)


def test_map_publisher_keeps_the_normal_gateway_by_default() -> None:
    assert map_projects_api_base({}) == "http://127.0.0.1:8080/api/v1/map-projects"


def test_map_publisher_can_target_an_isolated_test_gateway() -> None:
    assert map_projects_api_base(
        {"FMS_GATEWAY_BASE_URL": "http://127.0.0.1:18080/"}
    ) == "http://127.0.0.1:18080/api/v1/map-projects"


def test_map_publisher_can_use_the_new_map_as_an_isolated_project() -> None:
    assert map_project_name({}) == "new_map_2"
    assert map_project_name({"FMS_MAP_PROJECT": "new_map_2"}) == "new_map_2"


def test_map_publisher_can_select_the_measured_feature_file_independently() -> None:
    assert physical_features_file({}) is None
    assert physical_features_file(
        {"FMS_PHYSICAL_FEATURES_FILE": "/tmp/measured.jsonl"}
    ) == "/tmp/measured.jsonl"
