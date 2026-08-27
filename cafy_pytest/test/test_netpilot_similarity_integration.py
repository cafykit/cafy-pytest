"""Integration test for real fingerprint/embedder/FAISS similarity flow."""

import pytest

faiss = pytest.importorskip("faiss")
pytest.importorskip("sentence_transformers")

from cafy_pytest.netpilot_routing import (
    ACTION_ROUTE,
    ACTION_SKIP,
    DEFAULT_SIMILARITY_THRESHOLD,
    NetPilotRoutingContext,
    SimilarityConfig,
    route_failure,
    store_failure_fingerprint,
)
from cafy_pytest.netpilot_similarity import get_default_embedder
from cafy_pytest.netpilot_vectordb import FailureVectorStore


@pytest.fixture
def real_similarity_stack(tmp_path):
    embedder = get_default_embedder()
    if embedder is None:
        pytest.skip("sentence-transformers embedder unavailable")
    vector_store = FailureVectorStore(str(tmp_path))
    return embedder, vector_store


THRESHOLD = DEFAULT_SIMILARITY_THRESHOLD


def _similarity_config(embedder, vector_store):
    return SimilarityConfig(
        threshold=THRESHOLD,
        real_skip=True,
        embedder=embedder,
        vector_store=vector_store,
    )


def test_failure_sequence_store_then_skip_match(real_similarity_stack, tmp_path):
    """A stores successfully; similar B is skipped."""
    embedder, vector_store = real_similarity_stack
    scope_id = "validation-reg-1"
    agent = "pi-ip_agent"

    context_a = NetPilotRoutingContext(
        exception_type="VerificationError",
        exception_message="packet loss observed after convergence on neighbor 10.1.1.1",
        test_path="/test/ap/routing_bgp/bgp_ap.py",
        nodeid="test/ap/routing_bgp/bgp_ap.py::TestBgp::test_a",
        scope_id=scope_id,
        work_dir=str(tmp_path),
    )
    decision_a = route_failure(context_a, similarity_config=_similarity_config(embedder, vector_store))
    assert decision_a.action == ACTION_ROUTE
    assert decision_a.similarity_match is False
    assert decision_a.fingerprint is not None

    embedding_a = embedder.embed(decision_a.fingerprint.normalized_text)
    assert embedding_a is not None
    store_failure_fingerprint(
        work_dir=str(tmp_path),
        fingerprint=decision_a.fingerprint,
        embedding=embedding_a,
        agent=agent,
        scope_id=scope_id,
        nodeid=context_a.nodeid,
        vector_store=vector_store,
    )

    context_b = NetPilotRoutingContext(
        exception_type="VerificationError",
        exception_message="traffic did not recover following convergence on neighbor 10.5.8.2",
        test_path="/test/ap/routing_bgp/bgp_ap.py",
        nodeid="test/ap/routing_bgp/bgp_ap.py::TestBgp::test_b",
        scope_id=scope_id,
        work_dir=str(tmp_path),
    )
    decision_b = route_failure(context_b, similarity_config=_similarity_config(embedder, vector_store))

    assert decision_b.action == ACTION_SKIP
    assert decision_b.reason == "similar_failure"
    assert decision_b.similarity_match is True
    assert decision_b.similarity_score is not None
    assert decision_b.similarity_score >= THRESHOLD
    assert decision_b.matched_nodeid == context_a.nodeid
