"""Validation-only helpers for preserving NetPilot run artifacts."""

from __future__ import annotations

import json
import os
import shutil
from datetime import datetime, timezone


VALIDATION_DIRNAME = ".netpilot/validation"

PRESERVED_ARTIFACTS = (
    "status.json",
    "netpilot_cli_stdout.md",
    "netpilot_cli_stderr.log",
)


def validation_archive_dir(work_dir, session_id):
    """Return the session-scoped validation archive directory."""
    return os.path.join(work_dir, VALIDATION_DIRNAME, str(session_id))


def _resolve_triage_dir(launch_result):
    status_file = getattr(launch_result, "status_file", None)
    if status_file:
        return os.path.dirname(str(status_file))
    triage_dir = getattr(launch_result, "triage_dir", None)
    return str(triage_dir) if triage_dir else None


def preserve_validation_artifacts(launch_result, *, work_dir=None, metadata=None, logger=None):
    """Copy per-run triage artifacts into a session-scoped validation directory.

    This is validation-only bookkeeping. It does not alter NetPilot routing or
    RCA behavior. Failures are logged and ignored so CAFY continues normally.
    """
    session_id = getattr(launch_result, "session_id", None)
    if not session_id:
        if logger:
            logger.info("NetPilot validation: skip artifact preserve; missing session_id")
        return None

    resolved_work_dir = work_dir or getattr(launch_result, "work_dir", None)
    if not resolved_work_dir:
        if logger:
            logger.info("NetPilot validation: skip artifact preserve; missing work_dir")
        return None

    triage_dir = _resolve_triage_dir(launch_result)
    if not triage_dir:
        if logger:
            logger.info("NetPilot validation: skip artifact preserve; missing triage_dir")
        return None

    archive_dir = validation_archive_dir(resolved_work_dir, session_id)
    try:
        os.makedirs(archive_dir, exist_ok=True)
    except Exception as exc:
        if logger:
            logger.warning(
                "NetPilot validation: unable to create archive dir %s: %s",
                archive_dir,
                exc,
            )
        return None

    preserved = []
    for filename in PRESERVED_ARTIFACTS:
        source_path = os.path.join(triage_dir, filename)
        if not os.path.isfile(source_path):
            continue
        destination_path = os.path.join(archive_dir, filename)
        try:
            shutil.copy2(source_path, destination_path)
            preserved.append(filename)
        except Exception as exc:
            if logger:
                logger.warning(
                    "NetPilot validation: failed to copy %s to %s: %s",
                    source_path,
                    destination_path,
                    exc,
                )

    manifest = {
        "session_id": session_id,
        "archived_at": datetime.now(timezone.utc).isoformat(),
        "source_triage_dir": triage_dir,
        "archive_dir": archive_dir,
        "preserved_files": preserved,
        "metadata": metadata or {},
    }
    manifest_path = os.path.join(archive_dir, "manifest.json")
    try:
        with open(manifest_path, "w", encoding="utf-8") as handle:
            json.dump(manifest, handle, indent=2, sort_keys=True)
    except Exception as exc:
        if logger:
            logger.warning("NetPilot validation: failed to write manifest %s: %s", manifest_path, exc)

    if logger:
        logger.info(
            "NetPilot validation: preserved artifacts for session_id=%s in %s files=%s",
            session_id,
            archive_dir,
            preserved,
        )
    return archive_dir


__all__ = [
    "PRESERVED_ARTIFACTS",
    "VALIDATION_DIRNAME",
    "preserve_validation_artifacts",
    "validation_archive_dir",
]
