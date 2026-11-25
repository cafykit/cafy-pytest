"""Deterministic routing policy for CAFY failure-time NetPilot triage.

This module decides whether NetPilot should be skipped, which agent should
receive the failure, and whether a semantically similar failure was seen before.
It does not launch NetPilot or perform failure analysis.
"""

from collections import namedtuple
from pathlib import PurePosixPath

from utils.cafyexception import CafyException

from .netpilot_metrics import get_metrics
from .netpilot_similarity import build_failure_fingerprint
from .netpilot_vectordb import open_vector_store


ACTION_SKIP = "skip"
ACTION_ROUTE = "route"

DEFAULT_AGENT = "cafy_deep_agent"
DEFAULT_SIMILARITY_THRESHOLD = 0.85
REASON_SIMILAR_FAILURE = "similar_failure"

TGEN_EXCEPTIONS = (
    CafyException.TgenConfigMissingError,
    CafyException.TgenCheckTrafficError,
    CafyException.TgenLoadConfigError,
    CafyException.TgenStartProtocolError,
    CafyException.TgenStartTrafficError,
    CafyException.TgenInvalidInputError,
    CafyException.TgenArpResolveError,
    CafyException.TgenServerError,
    CafyException.TgenClientError,
)

PYTHON_IMPORT_EXCEPTIONS = (ImportError, SyntaxError)


NetPilotRoutingContext = namedtuple(
    "NetPilotRoutingContext",
    (
        "failure_stage",
        "exception",
        "test_path",
        "nodeid",
        "exception_type",
        "exception_message",
        "scope_id",
        "work_dir",
    ),
)
NetPilotRoutingContext.__new__.__defaults__ = (
    None,
    None,
    None,
    None,
    None,
    None,
    None,
    None,
)

NetPilotDecision = namedtuple(
    "NetPilotDecision",
    (
        "action",
        "agent",
        "reason",
        "feature_family",
        "similarity_match",
        "similarity_score",
        "matched_nodeid",
        "fingerprint",
    ),
)
NetPilotDecision.__new__.__defaults__ = (
    None,
    None,
    None,
    "unknown",
    False,
    None,
    None,
    None,
)

FeatureRoute = namedtuple(
    "FeatureRoute",
    ("feature_family", "path_components", "agent"),
)


FEATURE_ROUTES = (
    FeatureRoute("srv6", ("srv6",), "srv6_agent"),
    FeatureRoute("routing_bgp", ("routing_bgp",), "pi-ip_agent"),
    FeatureRoute("routing_isis", ("routing", "isis"), "pi-ip_agent"),
)


class SimilarityConfig:
    """Runtime similarity settings injected from the pytest plugin."""

    def __init__(
        self,
        *,
        threshold=DEFAULT_SIMILARITY_THRESHOLD,
        real_skip=True,
        embedder=None,
        vector_store=None,
        metrics=None,
    ):
        self.threshold = threshold
        self.real_skip = real_skip
        self.embedder = embedder
        self.vector_store = vector_store
        self.metrics = metrics or get_metrics()


def _path_components(context):
    path = context.test_path
    if path is None and context.nodeid:
        path = str(context.nodeid).split("::", 1)[0]
    if path is None:
        return ()

    normalized = str(path).replace("\\", "/")
    return tuple(
        component.lower()
        for component in PurePosixPath(normalized).parts
        if component not in ("", "/")
    )


def _contains_contiguous_components(path_components, required_components):
    required_length = len(required_components)
    if required_length == 0 or required_length > len(path_components):
        return False
    return any(
        path_components[index:index + required_length] == required_components
        for index in range(len(path_components) - required_length + 1)
    )


def _direct_skip_reason(exception):
    if isinstance(exception, PYTHON_IMPORT_EXCEPTIONS):
        return "python_import_failure"
    if isinstance(exception, TGEN_EXCEPTIONS):
        return "tgen"
    return None


def _composite_skip_reason(exception):
    if not isinstance(exception, CafyException.CompositeError):
        return None

    children = getattr(exception, "exceptions", None)
    if not isinstance(children, (list, tuple)) or not children:
        return None

    child_reasons = []
    for child in children:
        reason = _direct_skip_reason(child)
        if reason is None:
            reason = _composite_skip_reason(child)
        if reason is None:
            return None
        child_reasons.append(reason)

    if all(reason == "tgen" for reason in child_reasons):
        return "tgen"
    if all(reason == "python_import_failure" for reason in child_reasons):
        return "python_import_failure"
    return "composite_skip_worthy"


def _skip_decision(reason, fingerprint=None):
    return NetPilotDecision(
        action=ACTION_SKIP,
        agent=None,
        reason=reason,
        feature_family="unknown",
        similarity_match=False,
        similarity_score=None,
        matched_nodeid=None,
        fingerprint=fingerprint,
    )


def _route_decision(agent, reason, feature_family, fingerprint=None, **similarity_fields):
    return NetPilotDecision(
        action=ACTION_ROUTE,
        agent=agent,
        reason=reason,
        feature_family=feature_family,
        similarity_match=similarity_fields.get("similarity_match", False),
        similarity_score=similarity_fields.get("similarity_score"),
        matched_nodeid=similarity_fields.get("matched_nodeid"),
        fingerprint=fingerprint,
    )


def route_failure_deterministic(context):
    """Return the deterministic NetPilot decision for a CAFY failure."""
    reason = _direct_skip_reason(context.exception)
    if reason is None:
        reason = _composite_skip_reason(context.exception)
    if reason is not None:
        return _skip_decision(reason)

    path_components = _path_components(context)
    for feature_route in FEATURE_ROUTES:
        if _contains_contiguous_components(
            path_components,
            feature_route.path_components,
        ):
            return _route_decision(
                feature_route.agent,
                "feature_{}".format(feature_route.feature_family),
                feature_route.feature_family,
            )

    return _route_decision(DEFAULT_AGENT, "fallback", "unknown")


def _resolve_exception_fields(context):
    exception_type = context.exception_type
    exception_message = context.exception_message

    if context.exception is not None:
        if exception_type is None:
            exception_type = type(context.exception).__name__
        if exception_message is None:
            try:
                exception_message = str(context.exception)
            except Exception:
                exception_message = repr(context.exception)

    return exception_type, exception_message


def _apply_similarity(decision, context, similarity_config):
    if similarity_config is None:
        return decision
    if decision.action == ACTION_SKIP:
        return decision

    metrics = similarity_config.metrics
    exception_type, exception_message = _resolve_exception_fields(context)
    fingerprint = build_failure_fingerprint(exception_type, exception_message)

    vector_store = similarity_config.vector_store
    if vector_store is None and context.work_dir:
        vector_store = open_vector_store(context.work_dir)
    if vector_store is None:
        metrics.record_vector_db_failure()
        return decision._replace(fingerprint=fingerprint)

    scope_id = context.scope_id or "unknown-scope"
    agent = decision.agent

    try:
        exact_match = vector_store.find_exact(
            fingerprint.fingerprint_hash,
            agent,
            scope_id,
        )
        if exact_match is not None:
            metrics.record_exact_match()
            return _finalize_similarity_match(
                decision,
                fingerprint,
                exact_match.score,
                exact_match.nodeid,
                similarity_config,
            )

        embedder = similarity_config.embedder
        if embedder is None:
            metrics.record_embedding_failure()
            return decision._replace(fingerprint=fingerprint)

        embedding = embedder.embed(fingerprint.normalized_text)
        if embedding is None:
            metrics.record_embedding_failure()
            return decision._replace(fingerprint=fingerprint)

        semantic_match = vector_store.find_similar(
            embedding,
            agent,
            scope_id,
            similarity_config.threshold,
        )
        if semantic_match is None:
            return decision._replace(fingerprint=fingerprint)

        metrics.record_semantic_match(shadow=not similarity_config.real_skip)
        return _finalize_similarity_match(
            decision,
            fingerprint,
            semantic_match.score,
            semantic_match.nodeid,
            similarity_config,
        )
    except Exception:
        metrics.record_vector_db_failure()
        return decision._replace(fingerprint=fingerprint)


def _finalize_similarity_match(
    decision,
    fingerprint,
    score,
    matched_nodeid,
    similarity_config,
):
    if similarity_config.real_skip:
        similarity_config.metrics.record_similarity_skip()
        return NetPilotDecision(
            action=ACTION_SKIP,
            agent=None,
            reason=REASON_SIMILAR_FAILURE,
            feature_family=decision.feature_family,
            similarity_match=True,
            similarity_score=score,
            matched_nodeid=matched_nodeid,
            fingerprint=fingerprint,
        )

    return decision._replace(
        similarity_match=True,
        similarity_score=score,
        matched_nodeid=matched_nodeid,
        fingerprint=fingerprint,
    )


def route_failure(context, similarity_config=None):
    """Return the NetPilot routing decision including optional similarity."""
    metrics = (
        similarity_config.metrics
        if similarity_config is not None
        else get_metrics()
    )
    metrics.total_failures_considered += 1

    decision = route_failure_deterministic(context)
    if decision.action == ACTION_SKIP:
        metrics.record_hard_skip()
        return decision

    if decision.reason == "fallback":
        metrics.record_route(decision.agent, fallback=True)
    else:
        metrics.record_route(decision.agent, fallback=False)

    return _apply_similarity(decision, context, similarity_config)


def store_failure_fingerprint(
    *,
    work_dir,
    fingerprint,
    embedding,
    agent,
    scope_id,
    nodeid,
    vector_store=None,
):
    """Persist a failure fingerprint for future similarity-based skip decisions."""
    if fingerprint is None:
        return None

    store = vector_store or open_vector_store(work_dir)
    if store is None:
        get_metrics().record_vector_db_failure()
        return None

    record = {
        "fingerprint_hash": fingerprint.fingerprint_hash,
        "normalized_text": fingerprint.normalized_text,
        "embedding": embedding,
        "agent": agent,
        "scope_id": scope_id or "unknown-scope",
        "nodeid": nodeid,
        "exception_type": fingerprint.exception_type,
    }

    try:
        if embedding:
            return store.upsert(record)
        if hasattr(store, "find_exact"):
            return store.upsert({key: record[key] for key in record if key != "embedding"})
        get_metrics().record_embedding_failure()
        return None
    except Exception:
        get_metrics().record_vector_db_failure()
        return None


__all__ = [
    "ACTION_ROUTE",
    "ACTION_SKIP",
    "FEATURE_ROUTES",
    "NetPilotDecision",
    "NetPilotRoutingContext",
    "REASON_SIMILAR_FAILURE",
    "SimilarityConfig",
    "route_failure",
    "route_failure_deterministic",
    "store_failure_fingerprint",
]
