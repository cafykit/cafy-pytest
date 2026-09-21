"""Unit tests for deterministic CAFY to NetPilot routing."""

import pytest

from utils.cafyexception import CafyException
from utils.cafybase import CafyBase

from cafy_pytest.netpilot_routing import (
    ACTION_ROUTE,
    ACTION_SKIP,
    NetPilotRoutingContext,
    route_failure,
    route_failure_deterministic,
)


def _route(*, stage="call", exception=None, path=None, nodeid=None):
    return route_failure_deterministic(
        NetPilotRoutingContext(
            failure_stage=stage,
            exception=exception,
            test_path=path,
            nodeid=nodeid,
        )
    )


@pytest.mark.parametrize("exception", [ImportError("missing"), SyntaxError("bad")])
def test_import_or_syntax_failure_is_skipped(exception):
    decision = _route(exception=exception)

    assert decision.action == ACTION_SKIP
    assert decision.reason == "python_import_failure"


def test_normal_setup_failure_is_not_automatically_skipped():
    decision = _route(stage="setup", exception=RuntimeError("setup failed"))

    assert decision.action == ACTION_ROUTE
    assert decision.agent == "cafy_deep_agent"


@pytest.mark.parametrize(
    "exception_type",
    [
        CafyException.TgenConfigMissingError,
        CafyException.TgenCheckTrafficError,
        CafyException.TgenLoadConfigError,
        CafyException.TgenStartProtocolError,
        CafyException.TgenStartTrafficError,
        CafyException.TgenInvalidInputError,
        CafyException.TgenArpResolveError,
        CafyException.TgenServerError,
        CafyException.TgenClientError,
    ],
)
def test_tgen_failure_is_skipped(exception_type):
    decision = _route(exception=exception_type("tgen failure"))

    assert decision.action == ACTION_SKIP
    assert decision.agent is None
    assert decision.reason == "tgen"


@pytest.mark.parametrize(
    "exception_type",
    [
        CafyException.VerificationError,
        CafyException.ConfigError,
        CafyException.CafyBaseException,
        CafyBase.NoData,
    ],
)
def test_non_infrastructure_failure_is_not_skipped(exception_type):
    decision = _route(exception=exception_type("route-worthy"))

    assert decision.action == ACTION_ROUTE
    assert decision.agent == "cafy_deep_agent"


@pytest.mark.parametrize(
    "path, expected_agent, expected_family",
    [
        ("/test/ap/srv6/forwarding/test_ap.py", "srv6_agent", "srv6"),
        ("/test/ap/routing_bgp/bgp_ap.py", "pi-ip_agent", "routing_bgp"),
        ("/test/ap/routing/isis/isis_ap.py", "pi-ip_agent", "routing_isis"),
    ],
)
def test_feature_family_path_routing(path, expected_agent, expected_family):
    decision = _route(path=path, exception=RuntimeError("failure"))

    assert decision.action == ACTION_ROUTE
    assert decision.agent == expected_agent
    assert decision.feature_family == expected_family


def test_unknown_path_uses_cafy_deep_agent():
    decision = _route(path="/test/ap/qos/qos_ap.py")

    assert decision.agent == "cafy_deep_agent"
    assert decision.feature_family == "unknown"
    assert decision.reason == "fallback"


@pytest.mark.parametrize(
    "path",
    [
        "/test/ap/srv6_backup/test_ap.py",
        "/test/ap/my_routing_bgp_tests/test_ap.py",
        "/test/ap/routing/isis_extra/test_ap.py",
        "/test/ap/notrouting/isis/test_ap.py",
    ],
)
def test_path_component_matching_avoids_substring_false_positives(path):
    decision = _route(path=path)

    assert decision.agent == "cafy_deep_agent"


def test_all_skippable_composite_is_skipped():
    exception = CafyException.CompositeError(
        [
            CafyException.TgenConfigMissingError("missing"),
            CafyException.TgenInvalidInputError("invalid"),
        ]
    )

    decision = _route(exception=exception)

    assert decision.action == ACTION_SKIP
    assert decision.reason == "tgen"


def test_mixed_composite_is_not_skipped_and_routes_by_feature_family():
    exception = CafyException.CompositeError(
        [
            CafyException.TgenConfigMissingError("missing"),
            CafyException.VerificationError("verification failed"),
        ]
    )

    decision = _route(exception=exception, path="/test/ap/srv6/test_ap.py")

    assert decision.action == ACTION_ROUTE
    assert decision.agent == "srv6_agent"


@pytest.mark.parametrize("children", [[], None, [object()]])
def test_empty_or_malformed_composite_is_not_skipped(children):
    exception = CafyException.CompositeError([])
    exception.exceptions = children

    decision = _route(exception=exception)

    assert decision.action == ACTION_ROUTE
    assert decision.agent == "cafy_deep_agent"


def test_nodeid_path_is_used_when_test_path_is_unavailable():
    decision = _route(
        nodeid="test/ap/routing/isis/isis_ap.py::TestIsis::test_adjacency"
    )

    assert decision.agent == "pi-ip_agent"
    assert decision.feature_family == "routing_isis"


def test_route_failure_without_similarity_config_matches_deterministic():
    context = NetPilotRoutingContext(
        exception=RuntimeError("failure"),
        test_path="/test/ap/routing_bgp/bgp_ap.py",
    )
    assert route_failure(context).agent == "pi-ip_agent"
