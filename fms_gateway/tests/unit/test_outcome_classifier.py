from fms_gateway.app.outcomes import CATALOG_VERSION, OutcomeClassifier


def test_safety_reason_dominates_navigation_abort_and_keeps_contributor():
    result = OutcomeClassifier().classify(
        {
            "data_complete": True,
            "safety_reason": "SAFETY_WORKER_DETECTED",
            "navigation_reason": "NAV2_ABORTED",
        }
    )

    assert result.primary_reason == "SAFETY_WORKER_DETECTED"
    assert result.failure_domain == "safety"
    assert result.contributing_reasons == ("NAV2_ABORTED",)
    assert result.catalog_version == CATALOG_VERSION == "v1"


def test_context_mismatch_dominates_every_execution_fact():
    result = OutcomeClassifier().classify(
        {
            "data_complete": True,
            "context_matches": False,
            "safety_reason": "SAFETY_LATCHED",
            "navigation_reason": "NAV2_CONTROLLER_FAILED",
        }
    )

    assert result.primary_reason == "TASK_CONTEXT_MISMATCH"
    assert result.failure_domain == "integration"
    assert result.contributing_reasons == (
        "SAFETY_LATCHED",
        "NAV2_CONTROLLER_FAILED",
    )


def test_complete_success_is_classified_in_none_domain():
    result = OutcomeClassifier().classify(
        {"data_complete": True, "success_reason": "WAYPOINT_REACHED"}
    )

    assert result.primary_reason == "WAYPOINT_REACHED"
    assert result.failure_domain == "none"
    assert result.contributing_reasons == ()


def test_missing_and_unknown_results_are_stable_classifications():
    incomplete = OutcomeClassifier().classify({"data_complete": False})
    unknown = OutcomeClassifier().classify({"data_complete": True})

    assert (incomplete.primary_reason, incomplete.failure_domain) == (
        "RESULT_DATA_INCOMPLETE",
        "integration",
    )
    assert (unknown.primary_reason, unknown.failure_domain) == (
        "UNCLASSIFIED_RESULT",
        "unknown",
    )
