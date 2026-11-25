"""Tests for failure fingerprint normalization and hashing."""

from cafy_pytest.netpilot_similarity import (
    build_failure_fingerprint,
    normalize_failure_text,
)


def test_same_failure_with_different_timestamps_has_stable_fingerprint():
    first = build_failure_fingerprint(
        "VerificationError",
        "failed at 2026-08-13 10:00:00 with state idle",
    )
    second = build_failure_fingerprint(
        "VerificationError",
        "failed at 2026-08-14 11:22:33 with state idle",
    )

    assert first.normalized_text == second.normalized_text
    assert first.fingerprint_hash == second.fingerprint_hash


def test_same_failure_with_different_ips_is_normalized():
    first = build_failure_fingerprint(
        "VerificationError",
        "Traffic dropped for neighbor 10.1.1.1",
    )
    second = build_failure_fingerprint(
        "VerificationError",
        "Traffic dropped for neighbor 10.4.2.8",
    )

    assert first.normalized_text == "VerificationError: Traffic dropped for neighbor <IPV4>"
    assert second.normalized_text == first.normalized_text
    assert first.fingerprint_hash == second.fingerprint_hash


def test_materially_different_errors_have_different_fingerprints():
    drop = build_failure_fingerprint(
        "VerificationError",
        "traffic drop detected after convergence",
    )
    black_hole = build_failure_fingerprint(
        "VerificationError",
        "traffic black hole detected after convergence",
    )

    assert drop.fingerprint_hash != black_hole.fingerprint_hash


def test_exact_same_normalized_error_has_same_hash():
    first = build_failure_fingerprint("VerificationError", "expected established but got idle")
    second = build_failure_fingerprint("VerificationError", "expected established but got idle")

    assert first.fingerprint_hash == second.fingerprint_hash


def test_normalize_failure_text_collapses_whitespace_and_strips_paths():
    text = "failed in /nobackup/aasrai/work/run1   with pid=12345"
    normalized = normalize_failure_text(text)

    assert "<WORKDIR>" in normalized
    assert "pid=<PID>" in normalized
    assert "  " not in normalized
