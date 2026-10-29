"""Tests for similarity-aware NetPilot routing."""

import pytest

from cafy_pytest.netpilot_metrics import NetPilotMetrics
from cafy_pytest.netpilot_routing import (
    ACTION_ROUTE,
    ACTION_SKIP,
    NetPilotRoutingContext,
    SimilarityConfig,
    route_failure,
    store_failure_fingerprint,
)
from cafy_pytest.netpilot_similarity import build_failure_fingerprint


class MockEmbedder:
    def __init__(self, vector=None, fail=False):
        self.vector = vector or [1.0, 0.0, 0.0]
        self.fail = fail
        self.calls = 0

    def embed(self, text):
        self.calls += 1
        if self.fail:
            return None
        return list(self.vector)


class MockVectorStore:
    def __init__(self):
        self.records = []
        self.exact = None
        self.similar = None
        self.fail = False

    def find_exact(self, fingerprint_hash, agent, scope_id):
        if self.fail:
            raise RuntimeError("vectordb down")
        if self.exact and self.exact["hash"] == fingerprint_hash:
            if self.exact["agent"] == agent and self.exact["scope_id"] == scope_id:
                from cafy_pytest.netpilot_vectordb import SimilarityMatch

                return SimilarityMatch("0", 1.0, self.exact["nodeid"], "exact")
        return None

    def find_similar(self, embedding, agent, scope_id, threshold, top_k=10):
        if self.fail:
            raise RuntimeError("vectordb down")
        if self.similar is None:
            return None
        if self.similar["agent"] != agent or self.similar["scope_id"] != scope_id:
            return None
        if self.similar["score"] < threshold:
            return None
        from cafy_pytest.netpilot_vectordb import SimilarityMatch

        return SimilarityMatch("1", self.similar["score"], self.similar["nodeid"], "semantic")

    def upsert(self, record):
        self.records.append(record)
        return str(len(self.records) - 1)


def _context(**kwargs):
    defaults = {
        "exception_type": "VerificationError",
        "exception_message": "traffic drop detected after convergence",
        "test_path": "/test/ap/routing_bgp/bgp_ap.py",
        "nodeid": "test/ap/routing_bgp/bgp_ap.py::TestBgp::test_one",
        "scope_id": "reg-123",
        "work_dir": "/tmp/work",
    }
    defaults.update(kwargs)
    return NetPilotRoutingContext(**defaults)


def _similarity_config(**kwargs):
    metrics = NetPilotMetrics()
    defaults = {
        "real_skip": False,
        "embedder": MockEmbedder(),
        "vector_store": MockVectorStore(),
        "metrics": metrics,
    }
    defaults.update(kwargs)
    return SimilarityConfig(**defaults)


def test_no_similarity_match_routes_normally():
    decision = route_failure(_context(), similarity_config=_similarity_config())

    assert decision.action == ACTION_ROUTE
    assert decision.agent == "pi-ip_agent"
    assert decision.similarity_match is False


def test_high_similarity_same_agent_match_shadow_mode():
    store = MockVectorStore()
    store.similar = {
        "agent": "pi-ip_agent",
        "scope_id": "reg-123",
        "score": 0.92,
        "nodeid": "test/ap/routing_bgp/bgp_ap.py::TestBgp::test_prior",
    }
    decision = route_failure(
        _context(),
        similarity_config=_similarity_config(vector_store=store),
    )

    assert decision.action == ACTION_ROUTE
    assert decision.similarity_match is True
    assert decision.similarity_score == 0.92
    assert decision.matched_nodeid.endswith("test_prior")


def test_identical_text_exact_hash_match():
    fingerprint = build_failure_fingerprint(
        "VerificationError",
        "traffic drop detected after convergence",
    )
    store = MockVectorStore()
    store.exact = {
        "hash": fingerprint.fingerprint_hash,
        "agent": "pi-ip_agent",
        "scope_id": "reg-123",
        "nodeid": "test::exact",
    }
    decision = route_failure(
        _context(),
        similarity_config=_similarity_config(vector_store=store),
    )

    assert decision.similarity_match is True
    assert decision.similarity_score == 1.0


def test_high_similarity_different_agent_entry_is_ignored():
    store = MockVectorStore()
    store.similar = {
        "agent": "srv6_agent",
        "scope_id": "reg-123",
        "score": 0.99,
        "nodeid": "test::srv6",
    }
    decision = route_failure(
        _context(),
        similarity_config=_similarity_config(vector_store=store),
    )

    assert decision.similarity_match is False


def test_different_scope_is_not_matched():
    store = MockVectorStore()
    store.similar = {
        "agent": "pi-ip_agent",
        "scope_id": "other-reg",
        "score": 0.99,
        "nodeid": "test::other",
    }
    decision = route_failure(
        _context(),
        similarity_config=_similarity_config(vector_store=store),
    )

    assert decision.similarity_match is False


def test_vector_db_failure_routes_normally():
    store = MockVectorStore()
    store.fail = True
    decision = route_failure(
        _context(),
        similarity_config=_similarity_config(vector_store=store),
    )

    assert decision.action == ACTION_ROUTE
    assert decision.similarity_match is False


def test_embedder_failure_routes_normally():
    store = MockVectorStore()
    decision = route_failure(
        _context(),
        similarity_config=_similarity_config(
            vector_store=store,
            embedder=MockEmbedder(fail=True),
        ),
    )

    assert decision.action == ACTION_ROUTE
    assert decision.similarity_match is False


def test_real_skip_mode_skips_on_similarity_match():
    store = MockVectorStore()
    store.similar = {
        "agent": "pi-ip_agent",
        "scope_id": "reg-123",
        "score": 0.91,
        "nodeid": "test::prior",
    }
    decision = route_failure(
        _context(),
        similarity_config=_similarity_config(vector_store=store, real_skip=True),
    )

    assert decision.action == ACTION_SKIP
    assert decision.reason == "similar_failure"


def test_tgen_hard_skip_never_queries_vector_store():
    from utils.cafyexception import CafyException

    store = MockVectorStore()
    store.fail = True
    decision = route_failure(
        NetPilotRoutingContext(
            exception=CafyException.TgenCheckTrafficError("traffic"),
            test_path="/test/ap/routing_bgp/bgp_ap.py",
            scope_id="reg-123",
        ),
        similarity_config=_similarity_config(vector_store=store),
    )

    assert decision.action == ACTION_SKIP
    assert decision.reason == "tgen"


def test_import_hard_skip_never_queries_vector_store():
    store = MockVectorStore()
    store.fail = True
    decision = route_failure(
        NetPilotRoutingContext(
            exception=ImportError("missing module"),
            test_path="/test/ap/routing_bgp/bgp_ap.py",
            scope_id="reg-123",
        ),
        similarity_config=_similarity_config(vector_store=store),
    )

    assert decision.action == ACTION_SKIP


def test_store_failure_fingerprint_upserts_record():
    store = MockVectorStore()
    fingerprint = build_failure_fingerprint("VerificationError", "bgp idle")
    record_id = store_failure_fingerprint(
        work_dir="/tmp/work",
        fingerprint=fingerprint,
        embedding=[1.0, 0.0],
        agent="pi-ip_agent",
        scope_id="reg-123",
        nodeid="test::one",
        vector_store=store,
    )

    assert record_id == "0"
    assert len(store.records) == 1


def test_store_failure_fingerprint_without_embedding_uses_metadata_store(tmp_path):
    from cafy_pytest.netpilot_vectordb import FailureMetadataStore

    store = FailureMetadataStore(str(tmp_path))
    fingerprint = build_failure_fingerprint("VerificationError", "bgp idle")
    record_id = store_failure_fingerprint(
        work_dir=str(tmp_path),
        fingerprint=fingerprint,
        embedding=None,
        agent="pi-ip_agent",
        scope_id="reg-123",
        nodeid="test::one",
        vector_store=store,
    )

    assert record_id == "0"
    match = store.find_exact(fingerprint.fingerprint_hash, "pi-ip_agent", "reg-123")
    assert match is not None
    assert match.nodeid == "test::one"


def test_exact_hash_match_skips_in_real_skip_mode():
    fingerprint = build_failure_fingerprint(
        "VerificationError",
        "traffic drop detected after convergence",
    )
    store = MockVectorStore()
    store.exact = {
        "hash": fingerprint.fingerprint_hash,
        "agent": "pi-ip_agent",
        "scope_id": "reg-123",
        "nodeid": "test::exact",
    }
    metrics = NetPilotMetrics()
    decision = route_failure(
        _context(),
        similarity_config=_similarity_config(
            vector_store=store,
            real_skip=True,
            metrics=metrics,
        ),
    )

    assert decision.action == ACTION_SKIP
    assert decision.reason == "similar_failure"
    assert metrics.similarity_skips == 1
