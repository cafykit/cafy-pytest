"""Smoke tests for the test-author NetPilot invoke() API."""

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

rca = pytest.importorskip("rca")
netpilot = pytest.importorskip("rca.netpilot")


def test_invoke_forwards_required_context_and_prompt(tmp_path, monkeypatch):
    calls = []
    launch = SimpleNamespace(
        status="launched",
        status_file=str(tmp_path / "status.json"),
        output_file=str(tmp_path / "report.md"),
    )

    def fake_launch(**kwargs):
        calls.append(kwargs)
        return launch

    monkeypatch.setattr(netpilot, "_launch", fake_launch)

    handle = netpilot.invoke(
        prompt="Check whether BGP converged after reload",
        work_dir=str(tmp_path),
        testcase_name="test_bgp_reload",
        all_log_path=str(tmp_path / "all.log"),
    )

    assert isinstance(handle, netpilot.InvocationHandle)
    assert calls == [
        {
            "prompt": "Check whether BGP converged after reload",
            "work_dir": str(tmp_path),
            "testcase_name": "test_bgp_reload",
            "all_log_path": str(tmp_path / "all.log"),
            "session_scoped_artifacts": True,
        }
    ]


def test_invoke_handle_status_wait_and_report(tmp_path, monkeypatch):
    status_file = tmp_path / "status.json"
    report_file = tmp_path / "report.md"
    status_file.write_text(json.dumps({"status": "completed"}), encoding="utf-8")
    report_file.write_text("# RCA report", encoding="utf-8")

    launch = SimpleNamespace(
        status="launched",
        status_file=str(status_file),
        output_file=str(report_file),
    )
    monkeypatch.setattr(netpilot, "_launch", lambda **_kwargs: launch)

    handle = netpilot.invoke(
        prompt="Checkpoint after ISIS adjacency failure",
        work_dir=str(tmp_path),
        testcase_name="test_isis_adjacency",
        all_log_path=str(tmp_path / "all.log"),
    )

    assert handle.status() == "completed"
    assert handle.wait(timeout=1) is True
    assert handle.get_report() == "# RCA report"
