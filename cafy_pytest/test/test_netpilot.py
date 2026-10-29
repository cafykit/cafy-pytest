"""Unit tests for NetPilot CAFY handoff helpers."""

import json
from types import SimpleNamespace

from cafy_pytest import netpilot


class FakeExcInfo:
    def __str__(self):
        return "VerificationError: expected interface state missing"


class FakeCafyLog:
    work_dir = "/tmp/cafy-run"
    topology_file = "/tmp/topology.json"
    test_input_file = "/tmp/input.json"
    debug_server = "debug-server"


def test_build_failure_payload_is_ap_agnostic():
    nodeid = (
        "test/ap/srv6/srv6_forwarding/srv6_forwarding_ap.py::TestOAM::test_ping_SID"
    )
    node = SimpleNamespace(nodeid=nodeid, name="test_ping_SID")
    call = SimpleNamespace(when="call", excinfo=FakeExcInfo())
    report = SimpleNamespace(when="call", nodeid=nodeid)

    payload = netpilot.build_failure_payload(
        FakeCafyLog,
        node=node,
        call=call,
        report=report,
        reg_dict={"reg_id": "reg-1"},
    )

    assert payload["schema_version"] == netpilot.FAILURE_PAYLOAD_SCHEMA_VERSION
    assert payload["testcase_name"] == "test_ping_SID"
    assert payload["nodeid"] == nodeid
    assert payload["failure_phase"] == "call"
    assert payload["ap_name"] == "srv6_forwarding_ap"
    assert payload["test_file"] == "test/ap/srv6/srv6_forwarding/srv6_forwarding_ap.py"
    assert payload["work_dir"] == "/tmp/cafy-run"
    assert payload["all_log_path"] == "/tmp/cafy-run/all.log"
    assert payload["topology_file"] == "/tmp/topology.json"
    assert payload["test_input_file"] == "/tmp/input.json"
    assert (
        payload["exception_text"]
        == "VerificationError: expected interface state missing"
    )
    assert payload["registration_id"] == "reg-1"
    assert payload["debug_server"] == "debug-server"


def test_record_trigger_event_appends_coverage_ledger(tmp_path):
    payload = {
        "work_dir": str(tmp_path),
        "ap_name": "sample_ap",
        "testcase_name": "test_sample",
        "nodeid": "sample.py::TestSample::test_sample",
        "failure_phase": "call",
        "test_file": "sample.py",
    }

    ledger = netpilot.record_trigger_event(
        payload,
        decision="launched",
        trigger_enabled=True,
        dedupe_key=payload["nodeid"],
        session_id="session-1",
        status_file="/tmp/status.json",
    )

    with open(ledger, encoding="utf-8") as stream:
        event = json.loads(stream.readline())
    assert event["eligible"] is True
    assert event["decision"] == "launched"
    assert event["session_id"] == "session-1"
    assert event["nodeid"] == payload["nodeid"]


def test_invoke_failure_triage_uses_public_api_with_standard_payload():
    calls = []

    def invoker(**kwargs):
        calls.append(kwargs)
        return SimpleNamespace(status_file="/tmp/status.json")

    payload = {
        "work_dir": "/tmp/cafy-run",
        "testcase_name": "test_case",
        "all_log_path": "/tmp/cafy-run/all.log",
    }

    result = netpilot.invoke_failure_triage(
        payload,
        netpilot_agent="srv6_agent",
        ssh_username="user",
        ssh_password="password",
        live_capture_enabled=True,
        timeout_seconds=120,
        invoker=invoker,
    )

    assert result.status_file == "/tmp/status.json"
    assert calls[0]["failure_payload"] == payload
    assert calls[0]["netpilot_agent"] == "srv6_agent"
    assert calls[0]["ssh_username"] == "user"
    assert calls[0]["ssh_password"] == "password"
    assert calls[0]["live_capture_enabled"] is True
    assert calls[0]["timeout_seconds"] == 120
    assert calls[0]["session_scoped_artifacts"] is True


def test_activate_and_deactivate_runtime_context_forward_lifecycle():
    calls = []
    token = object()
    payload = {
        "work_dir": "/tmp/cafy-run",
        "testcase_name": "test_case",
    }

    result = netpilot.activate_runtime_context(
        payload,
        timeout_seconds=300,
        credentials_provider="provider",
        setter=lambda *args, **kwargs: calls.append((args, kwargs)) or token,
    )
    netpilot.deactivate_runtime_context(
        result,
        resetter=lambda value: calls.append((value, None)),
    )

    assert result is token
    assert calls[0][0] == (payload,)
    assert calls[0][1]["timeout_seconds"] == 300
    assert calls[0][1]["credentials_provider"] == "provider"
    assert calls[1] == (token, None)


def test_invoke_failure_triage_preserves_topology_in_full_payload():
    calls = []

    def invoker(**kwargs):
        calls.append(kwargs)
        return SimpleNamespace(status_file="/tmp/status.json")

    payload = {
        "work_dir": "/tmp/cafy-run",
        "testcase_name": "test_case",
        "all_log_path": "/tmp/cafy-run/all.log",
        "topology_file": "/tmp/topology.json",
        "test_input_file": "/tmp/input.json",
        "failure_phase": "collect",
        "route_agent": "pi-ip_agent",
    }

    netpilot.invoke_failure_triage(payload, invoker=invoker)

    assert calls[0]["failure_payload"] == payload
    assert calls[0]["failure_payload"]["topology_file"] == "/tmp/topology.json"
    assert calls[0]["failure_payload"]["test_input_file"] == "/tmp/input.json"
    assert calls[0]["failure_payload"]["failure_phase"] == "collect"
    assert calls[0]["netpilot_agent"] == "pi-ip_agent"


def test_wait_for_status_returns_terminal_payload(tmp_path):
    status_file = tmp_path / "status.json"
    status_file.write_text(json.dumps({"status": "completed"}), encoding="utf-8")

    result = netpilot.wait_for_status(
        str(status_file),
        timeout_seconds=5,
        poll_seconds=1,
    )

    assert result["status"] == "completed"
