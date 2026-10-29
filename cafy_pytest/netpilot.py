"""NetPilot integration helpers for CAFY pytest failures.

This module keeps the NetPilot handoff logic small and testable so the main
pytest plugin only needs to decide when a failure should trigger triage.
"""

import json
import os
import time
import uuid
from datetime import datetime, timezone


FAILURE_PAYLOAD_SCHEMA_VERSION = "1.0"
TRIGGER_EVENT_SCHEMA_VERSION = "1.0"
TERMINAL_STATUSES = {"live_capture_complete", "completed", "failed", "timed_out"}
NETPILOT_HOLD_TIMEOUT_SECONDS = 1800
NETPILOT_STATUS_POLL_SECONDS = 2


def _safe_getattr(obj, name, default=None):
    try:
        return getattr(obj, name, default)
    except Exception:
        return default


def _nodeid_from(node=None, report=None):
    return _safe_getattr(node, "nodeid") or _safe_getattr(report, "nodeid")


def _test_file_from_nodeid(nodeid):
    if not nodeid:
        return None
    return nodeid.split("::", 1)[0]


def _ap_name_from_test_file(test_file):
    if not test_file:
        return None
    return os.path.splitext(os.path.basename(test_file))[0]


def _testcase_name_from(node=None, report=None):
    name = _safe_getattr(node, "name")
    if name:
        return name
    nodeid = _nodeid_from(node=node, report=report)
    if nodeid:
        return nodeid.split("::")[-1]
    return None


def _failure_phase_from(call=None, report=None):
    return _safe_getattr(report, "when") or _safe_getattr(call, "when")


def _exception_text_from(call=None):
    excinfo = _safe_getattr(call, "excinfo")
    if excinfo is None:
        return None
    try:
        return str(excinfo)
    except Exception:
        return repr(excinfo)


def build_failure_payload(cafy_log, node=None, call=None, report=None, reg_dict=None):
    """Build the standard AP-agnostic failure payload sent to NetPilot."""
    nodeid = _nodeid_from(node=node, report=report)
    test_file = _test_file_from_nodeid(nodeid)
    work_dir = _safe_getattr(cafy_log, "work_dir")
    all_log_path = os.path.join(work_dir, "all.log") if work_dir else None
    reg_dict = reg_dict or {}

    return {
        "schema_version": FAILURE_PAYLOAD_SCHEMA_VERSION,
        "testcase_name": _testcase_name_from(node=node, report=report),
        "nodeid": nodeid,
        "failure_phase": _failure_phase_from(call=call, report=report),
        "ap_name": _ap_name_from_test_file(test_file),
        "test_file": test_file,
        "work_dir": work_dir,
        "all_log_path": all_log_path,
        "topology_file": _safe_getattr(cafy_log, "topology_file"),
        "test_input_file": _safe_getattr(cafy_log, "test_input_file"),
        "exception_text": _exception_text_from(call=call),
        "registration_id": reg_dict.get("reg_id"),
        "debug_server": _safe_getattr(cafy_log, "debug_server"),
    }


def record_trigger_event(
    payload,
    *,
    decision,
    trigger_enabled,
    dedupe_key=None,
    session_id=None,
    status_file=None,
    error=None,
):
    """Append one failure-trigger decision to the CAFY run ledger."""
    work_dir = payload.get("work_dir") if isinstance(payload, dict) else None
    if not work_dir:
        return None

    triage_dir = os.path.join(work_dir, "netpilot_failure_triage")
    try:
        os.makedirs(triage_dir, exist_ok=True)
        event = {
            "schema_version": TRIGGER_EVENT_SCHEMA_VERSION,
            "event_id": uuid.uuid4().hex,
            "detected_at": datetime.now(timezone.utc).isoformat(),
            "eligible": True,
            "decision": decision,
            "trigger_enabled": bool(trigger_enabled),
            "dedupe_key": dedupe_key,
            "session_id": session_id,
            "status_file": status_file,
            "error": error,
            "ap_name": payload.get("ap_name"),
            "testcase_name": payload.get("testcase_name"),
            "nodeid": payload.get("nodeid"),
            "failure_phase": payload.get("failure_phase"),
            "test_file": payload.get("test_file"),
            "work_dir": work_dir,
        }
        ledger = os.path.join(triage_dir, "trigger_events.jsonl")
        with open(ledger, "a", encoding="utf-8") as stream:
            stream.write(json.dumps(event, sort_keys=True) + "\n")
        return ledger
    except (OSError, TypeError, ValueError):
        return None


def invoke_failure_triage(
    payload,
    *,
    netpilot_agent=None,
    ssh_username=None,
    ssh_password=None,
    live_capture_enabled=False,
    timeout_seconds=900,
    invoker=None,
):
    """Launch NetPilot CAFY failure triage using the standard failure payload."""
    if invoker is None:
        from rca.generic.agents.cafy_deep_agent.failure_triage import (  # noqa: PLC0415
            launch_cafy_failure_triage,
        )

        invoker = launch_cafy_failure_triage

    agent = netpilot_agent or payload.get("route_agent")
    return invoker(
        work_dir=payload.get("work_dir"),
        testcase_name=payload.get("testcase_name"),
        all_log_path=payload.get("all_log_path"),
        registration_id=payload.get("registration_id"),
        debug_server=payload.get("debug_server"),
        topology_file=payload.get("topology_file"),
        test_input_file=payload.get("test_input_file"),
        exception_text=payload.get("exception_text"),
        failure_payload=payload,
        netpilot_agent=agent,
        timeout_seconds=timeout_seconds,
        live_capture_enabled=live_capture_enabled,
        ssh_username=ssh_username,
        ssh_password=ssh_password,
        session_scoped_artifacts=True,
    )


def activate_runtime_context(
    payload,
    *,
    timeout_seconds=900,
    credentials_provider=None,
    setter=None,
):
    """Expose the active CAFY testcase to prompt-only NetPilot invocations."""
    if setter is None:
        try:
            from rca.netpilot import set_runtime_context  # noqa: PLC0415
        except ImportError:
            return None
        setter = set_runtime_context

    return setter(
        payload,
        timeout_seconds=timeout_seconds,
        credentials_provider=credentials_provider,
    )


def deactivate_runtime_context(token, *, resetter=None):
    """Restore the NetPilot context that preceded the active CAFY testcase."""
    if token is None:
        return
    if resetter is None:
        from rca.netpilot import reset_runtime_context  # noqa: PLC0415

        resetter = reset_runtime_context
    resetter(token)


def read_status(status_file):
    """Read a NetPilot status file and return ``(payload, error)``."""
    try:
        with open(status_file, "r") as status_handle:
            return json.load(status_handle), None
    except Exception as exc:
        return None, str(exc)


def wait_for_status(
    status_file,
    *,
    timeout_seconds,
    poll_seconds,
    on_status=None,
    sleep=time.sleep,
    now=time.time,
):
    """Poll status.json until a terminal NetPilot status or local timeout."""
    end_time = now() + max(0, int(timeout_seconds or 0))
    poll_seconds = max(1, int(poll_seconds or 1))

    while now() < end_time:
        if os.path.exists(status_file):
            payload, error = read_status(status_file)
            if error:
                return {"status": "status_unavailable", "error": error}

            status = payload.get("status")
            if on_status:
                on_status(status, payload)
            if status in TERMINAL_STATUSES:
                return payload

        sleep(min(poll_seconds, max(0, end_time - now())))

    return {"status": "hold_timeout"}
