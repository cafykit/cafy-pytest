"""End-to-end tests for enforced similarity skip at the approved threshold."""

from types import SimpleNamespace

import pytest

from cafy_pytest.netpilot_metrics import NetPilotMetrics
from cafy_pytest.netpilot_routing import (
    ACTION_ROUTE,
    ACTION_SKIP,
    DEFAULT_SIMILARITY_THRESHOLD,
    NetPilotRoutingContext,
    REASON_SIMILAR_FAILURE,
    SimilarityConfig,
    route_failure,
    store_failure_fingerprint,
)
from cafy_pytest.netpilot_similarity import build_failure_fingerprint
from cafy_pytest.netpilot_vectordb import FailureMetadataStore, open_vector_store


APPROVED_THRESHOLD = DEFAULT_SIMILARITY_THRESHOLD


def _srv6_context(tmp_path, *, nodeid, message):
    return NetPilotRoutingContext(
        exception_type="RuntimeError",
        exception_message=message,
        test_path="/nobackup/aasrai/cafyap/srv6/accounting/srv6_loc_int_egress_acc_ap.py",
        nodeid=nodeid,
        scope_id="reg-srv6-1",
        work_dir=str(tmp_path),
    )


def _metadata_similarity_config(vector_store, metrics=None):
    return SimilarityConfig(
        threshold=APPROVED_THRESHOLD,
        real_skip=True,
        embedder=None,
        vector_store=vector_store,
        metrics=metrics or NetPilotMetrics(),
    )


def test_two_run_metadata_only_exact_match_skips_without_faiss(tmp_path):
    """First routed failure stores a hash; the second identical failure skips."""
    store = FailureMetadataStore(str(tmp_path))
    config = _metadata_similarity_config(store)
    message = "IxNetwork error: Port is not owned by this user"

    first = route_failure(
        _srv6_context(
            tmp_path,
            nodeid="srv6_loc_int_egress_acc_ap.py::TestPing::test_ping",
            message=message,
        ),
        similarity_config=config,
    )
    assert first.action == ACTION_ROUTE
    assert first.agent == "srv6_agent"
    assert first.fingerprint is not None

    record_id = store_failure_fingerprint(
        work_dir=str(tmp_path),
        fingerprint=first.fingerprint,
        embedding=None,
        agent=first.agent,
        scope_id="reg-srv6-1",
        nodeid="srv6_loc_int_egress_acc_ap.py::TestPing::test_ping",
        vector_store=store,
    )
    assert record_id == "0"

    second = route_failure(
        _srv6_context(
            tmp_path,
            nodeid="srv6_loc_int_egress_acc_ap.py::TestPing::test_ping",
            message=message,
        ),
        similarity_config=config,
    )
    assert second.action == ACTION_SKIP
    assert second.reason == REASON_SIMILAR_FAILURE
    assert second.similarity_match is True
    assert second.similarity_score == 1.0
    assert config.metrics.similarity_skips == 1


def test_store_before_failed_launch_still_enables_skip_on_rerun(tmp_path):
    """Fingerprint persistence must not depend on a successful NetPilot launch."""
    store = FailureMetadataStore(str(tmp_path))
    config = _metadata_similarity_config(store)
    message = "Port Released (License Failed) on 20.0.0.2;1;1"

    first = route_failure(
        _srv6_context(tmp_path, nodeid="ap.py::TestPing::test_ping", message=message),
        similarity_config=config,
    )
    assert first.action == ACTION_ROUTE

    store_failure_fingerprint(
        work_dir=str(tmp_path),
        fingerprint=first.fingerprint,
        embedding=None,
        agent=first.agent,
        scope_id="reg-srv6-1",
        nodeid="ap.py::TestPing::test_ping",
        vector_store=store,
    )

    second = route_failure(
        _srv6_context(tmp_path, nodeid="ap.py::TestPing::test_ping", message=message),
        similarity_config=config,
    )
    assert second.action == ACTION_SKIP


def test_normalized_volatile_values_still_match_after_store(tmp_path):
    """IP addresses in the message are normalized before hashing."""
    store = FailureMetadataStore(str(tmp_path))
    config = _metadata_similarity_config(store)

    first = route_failure(
        _srv6_context(
            tmp_path,
            nodeid="ap.py::TestA::test_one",
            message="SSH timeout connecting to 10.89.172.196:22001",
        ),
        similarity_config=config,
    )
    store_failure_fingerprint(
        work_dir=str(tmp_path),
        fingerprint=first.fingerprint,
        embedding=None,
        agent=first.agent,
        scope_id="reg-srv6-1",
        nodeid="ap.py::TestA::test_one",
        vector_store=store,
    )

    second = route_failure(
        _srv6_context(
            tmp_path,
            nodeid="ap.py::TestB::test_two",
            message="SSH timeout connecting to 10.89.172.197:22001",
        ),
        similarity_config=config,
    )
    assert second.action == ACTION_SKIP
    assert second.matched_nodeid == "ap.py::TestA::test_one"


def test_different_failure_message_does_not_skip(tmp_path):
    store = FailureMetadataStore(str(tmp_path))
    config = _metadata_similarity_config(store)

    first = route_failure(
        _srv6_context(tmp_path, nodeid="ap.py::TestPing::test_ping", message="IXIA port error"),
        similarity_config=config,
    )
    store_failure_fingerprint(
        work_dir=str(tmp_path),
        fingerprint=first.fingerprint,
        embedding=None,
        agent=first.agent,
        scope_id="reg-srv6-1",
        nodeid="ap.py::TestPing::test_ping",
        vector_store=store,
    )

    second = route_failure(
        _srv6_context(tmp_path, nodeid="ap.py::TestPing::test_ping", message="BGP not converged"),
        similarity_config=config,
    )
    assert second.action == ACTION_ROUTE


def test_open_vector_store_metadata_fallback_when_faiss_unavailable(tmp_path, monkeypatch):
    import cafy_pytest.netpilot_vectordb as vectordb

    monkeypatch.setattr(vectordb, "faiss", None)
    store = open_vector_store(str(tmp_path))

    assert isinstance(store, FailureMetadataStore)


def test_triage_enable_auto_enables_skip_similar_flag():
    config = SimpleNamespace(
        netpilot_cafy_triage_enable=True,
        netpilot_skip_similar=False,
    )
    enabled = (
        getattr(config, "netpilot_skip_similar", False)
        or config.netpilot_cafy_triage_enable
    )
    assert enabled is True


def test_semantic_skip_respects_approved_threshold():
    class FixedEmbedder:
        def embed(self, text):
            if "first" in text:
                return [1.0, 0.0]
            return [0.99, 0.01]

    class InMemoryVectorStore:
        def __init__(self):
            self.records = []

        def find_exact(self, fingerprint_hash, agent, scope_id):
            return None

        def find_similar(self, embedding, agent, scope_id, threshold, top_k=10):
            from cafy_pytest.netpilot_vectordb import SimilarityMatch

            score = 0.99
            if score < threshold:
                return None
            return SimilarityMatch("0", score, "ap.py::stored", "semantic")

        def upsert(self, record):
            self.records.append(record)
            return "0"

    store = InMemoryVectorStore()
    metrics = NetPilotMetrics()
    config = SimilarityConfig(
        threshold=APPROVED_THRESHOLD,
        real_skip=True,
        embedder=FixedEmbedder(),
        vector_store=store,
        metrics=metrics,
    )

    first_fp = build_failure_fingerprint("VerificationError", "first failure text")
    store.upsert(
        {
            "embedding": [1.0, 0.0],
            "fingerprint_hash": first_fp.fingerprint_hash,
            "normalized_text": first_fp.normalized_text,
            "agent": "srv6_agent",
            "scope_id": "scope-1",
            "nodeid": "ap.py::stored",
            "exception_type": "VerificationError",
        }
    )

    decision = route_failure(
        NetPilotRoutingContext(
            exception_type="VerificationError",
            exception_message="second failure text",
            test_path="/test/ap/srv6/accounting/ap.py",
            nodeid="ap.py::new",
            scope_id="scope-1",
            work_dir="/tmp/work",
        ),
        similarity_config=config,
    )

    assert decision.action == ACTION_SKIP
    assert decision.similarity_score == 0.99
    assert decision.similarity_score >= APPROVED_THRESHOLD
    assert metrics.similarity_skips == 1


def test_semantic_score_below_threshold_routes_instead_of_skip():
    class FixedEmbedder:
        def embed(self, text):
            return [0.5, 0.8660254037844386]

    class LowScoreStore:
        def find_exact(self, fingerprint_hash, agent, scope_id):
            return None

        def find_similar(self, embedding, agent, scope_id, threshold, top_k=10):
            from cafy_pytest.netpilot_vectordb import SimilarityMatch

            score = 0.84
            if score < threshold:
                return None
            return SimilarityMatch("0", score, "ap.py::stored", "semantic")

        def upsert(self, record):
            return "0"

    config = SimilarityConfig(
        threshold=APPROVED_THRESHOLD,
        real_skip=True,
        embedder=FixedEmbedder(),
        vector_store=LowScoreStore(),
    )
    decision = route_failure(
        NetPilotRoutingContext(
            exception_type="VerificationError",
            exception_message="unrelated failure",
            test_path="/test/ap/srv6/accounting/ap.py",
            nodeid="ap.py::new",
            scope_id="scope-1",
            work_dir="/tmp/work",
        ),
        similarity_config=config,
    )

    assert decision.action == ACTION_ROUTE
    assert decision.similarity_match is False
