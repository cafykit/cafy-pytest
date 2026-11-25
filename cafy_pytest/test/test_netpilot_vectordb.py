"""Tests for FAISS vector store with metadata sidecar."""

import pytest

from cafy_pytest.netpilot_vectordb import FailureMetadataStore, open_vector_store

faiss = pytest.importorskip("faiss")

from cafy_pytest.netpilot_vectordb import FailureVectorStore


@pytest.fixture
def store(tmp_path):
    return FailureVectorStore(str(tmp_path))


def test_metadata_store_persistence_roundtrip(tmp_path):
    first = FailureMetadataStore(str(tmp_path))
    fingerprint_hash = "abc123"
    first.upsert(
        {
            "fingerprint_hash": fingerprint_hash,
            "normalized_text": "RuntimeError: IXIA port error",
            "agent": "srv6_agent",
            "scope_id": "reg-1",
            "nodeid": "ap.py::TestPing::test_ping",
            "exception_type": "RuntimeError",
        }
    )

    second = FailureMetadataStore(str(tmp_path))
    match = second.find_exact(fingerprint_hash, "srv6_agent", "reg-1")
    assert match is not None
    assert match.nodeid == "ap.py::TestPing::test_ping"


def test_find_exact_match_filters_by_agent_and_scope(store):
    store.upsert(
        {
            "embedding": [1.0, 0.0],
            "fingerprint_hash": "abc123",
            "normalized_text": "VerificationError: bgp idle",
            "agent": "pi-ip_agent",
            "scope_id": "reg-1",
            "nodeid": "test::one",
            "exception_type": "VerificationError",
        }
    )

    match = store.find_exact("abc123", "pi-ip_agent", "reg-1")
    assert match is not None
    assert match.match_type == "exact"
    assert match.nodeid == "test::one"
    assert store.find_exact("abc123", "srv6_agent", "reg-1") is None
    assert store.find_exact("abc123", "pi-ip_agent", "reg-2") is None


def test_find_similar_filters_by_agent_and_scope(store):
    store.upsert(
        {
            "embedding": [1.0, 0.0],
            "fingerprint_hash": "hash-a",
            "normalized_text": "traffic drop after convergence",
            "agent": "pi-ip_agent",
            "scope_id": "reg-1",
            "nodeid": "test::a",
            "exception_type": "VerificationError",
        }
    )
    store.upsert(
        {
            "embedding": [0.0, 1.0],
            "fingerprint_hash": "hash-b",
            "normalized_text": "other failure",
            "agent": "srv6_agent",
            "scope_id": "reg-1",
            "nodeid": "test::b",
            "exception_type": "VerificationError",
        }
    )

    match = store.find_similar([0.99, 0.01], "pi-ip_agent", "reg-1", threshold=0.5)
    assert match is not None
    assert match.nodeid == "test::a"
    assert store.find_similar([0.99, 0.01], "srv6_agent", "reg-1", threshold=0.5) is None


def test_persistence_roundtrip(tmp_path):
    first = FailureVectorStore(str(tmp_path))
    first.upsert(
        {
            "embedding": [1.0, 0.0],
            "fingerprint_hash": "persist-me",
            "normalized_text": "persist",
            "agent": "cafy_deep_agent",
            "scope_id": "scope",
            "nodeid": "test::persist",
            "exception_type": "RuntimeError",
        }
    )

    second = FailureVectorStore(str(tmp_path))
    match = second.find_exact("persist-me", "cafy_deep_agent", "scope")
    assert match is not None
