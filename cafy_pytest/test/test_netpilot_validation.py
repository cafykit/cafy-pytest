"""Tests for validation-only NetPilot artifact preservation."""

import json
import os

from cafy_pytest.netpilot_validation import (
    PRESERVED_ARTIFACTS,
    preserve_validation_artifacts,
    validation_archive_dir,
)


class _LaunchResult(object):
    def __init__(self, **fields):
        for key, value in fields.items():
            setattr(self, key, value)


def test_preserve_validation_artifacts_copies_session_scoped_files(tmp_path):
    work_dir = tmp_path / "work"
    triage_dir = work_dir / "netpilot_failure_triage"
    triage_dir.mkdir(parents=True)

    session_id = "abc123session"
    for filename in PRESERVED_ARTIFACTS:
        (triage_dir / filename).write_text("content-for-{}".format(filename), encoding="utf-8")

    status_file = triage_dir / "status.json"
    launch_result = _LaunchResult(
        session_id=session_id,
        work_dir=str(work_dir),
        status_file=str(status_file),
        triage_dir=str(triage_dir),
        launched=True,
    )

    archive_dir = preserve_validation_artifacts(
        launch_result,
        work_dir=str(work_dir),
        metadata={"nodeid": "test::one", "agent": "pi-ip_agent"},
    )

    expected_dir = validation_archive_dir(str(work_dir), session_id)
    assert archive_dir == expected_dir
    for filename in PRESERVED_ARTIFACTS:
        archived = os.path.join(expected_dir, filename)
        assert os.path.isfile(archived)
        assert "content-for-{}".format(filename) in open(archived, encoding="utf-8").read()

    manifest = json.loads(open(os.path.join(expected_dir, "manifest.json"), encoding="utf-8").read())
    assert manifest["session_id"] == session_id
    assert manifest["metadata"]["nodeid"] == "test::one"
    assert set(manifest["preserved_files"]) == set(PRESERVED_ARTIFACTS)


def test_preserve_validation_artifacts_fail_open_without_session_id(tmp_path):
    launch_result = _LaunchResult(work_dir=str(tmp_path), launched=True)
    assert preserve_validation_artifacts(launch_result, work_dir=str(tmp_path)) is None
