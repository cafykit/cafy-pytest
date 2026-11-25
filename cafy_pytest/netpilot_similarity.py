"""Failure fingerprint construction and embedding for NetPilot similarity."""

from __future__ import annotations

import hashlib
import re
from collections import namedtuple


FailureFingerprint = namedtuple(
    "FailureFingerprint",
    ("normalized_text", "fingerprint_hash", "exception_type", "raw_text"),
)

DEFAULT_EMBEDDING_MODEL = "all-MiniLM-L6-v2"

# Volatile value patterns replaced while preserving technical meaning.
_TIMESTAMP_RE = re.compile(
    r"\b\d{4}-\d{2}-\d{2}[ T]\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:?\d{2})?\b"
    r"|\b\d{2}/\d{2}/\d{4}\s+\d{2}:\d{2}:\d{2}\b"
    r"|\b\d{2}-\d{2}-\d{4}\s+\d{2}:\d{2}:\d{2}\b"
)
_UUID_RE = re.compile(
    r"\b[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}\b"
)
_PID_RE = re.compile(r"\bpid[=:\s#]*\d+\b", re.IGNORECASE)
_WORK_DIR_RE = re.compile(
    r"(?:/tmp/[^\s]+|/var/tmp/[^\s]+|/nobackup/[^\s]+|/scratch/[^\s]+|"
    r"/users/[^\s]+/work/[^\s]+|/work/[^\s]+)"
)
_IPV4_RE = re.compile(r"\b(?:(?:25[0-5]|2[0-4]\d|[01]?\d?\d)\.){3}(?:25[0-5]|2[0-4]\d|[01]?\d?\d)\b")
_IPV6_RE = re.compile(r"\b(?:[0-9a-fA-F]{0,4}:){2,7}[0-9a-fA-F]{0,4}\b")
_MAC_RE = re.compile(r"\b(?:[0-9a-fA-F]{2}[:-]){5}[0-9a-fA-F]{2}\b")
_WHITESPACE_RE = re.compile(r"\s+")


def normalize_failure_text(text):
    """Normalize volatile runtime values in a failure message."""
    if not text:
        return ""

    normalized = str(text)
    normalized = _TIMESTAMP_RE.sub("<TIMESTAMP>", normalized)
    normalized = _UUID_RE.sub("<UUID>", normalized)
    normalized = _PID_RE.sub("pid=<PID>", normalized)
    normalized = _WORK_DIR_RE.sub("<WORKDIR>", normalized)
    normalized = _IPV4_RE.sub("<IPV4>", normalized)
    normalized = _IPV6_RE.sub("<IPV6>", normalized)
    normalized = _MAC_RE.sub("<MAC>", normalized)
    normalized = _WHITESPACE_RE.sub(" ", normalized).strip()
    return normalized


def build_failure_fingerprint(exception_type, exception_message):
    """Build normalized fingerprint text and SHA256 hash."""
    exception_type = (exception_type or "").strip()
    message = "" if exception_message is None else str(exception_message).strip()

    if exception_type and message:
        raw_text = "{}: {}".format(exception_type, message)
    elif exception_type:
        raw_text = exception_type
    else:
        raw_text = message

    normalized_text = normalize_failure_text(raw_text)
    fingerprint_hash = hashlib.sha256(normalized_text.encode("utf-8")).hexdigest()
    return FailureFingerprint(
        normalized_text=normalized_text,
        fingerprint_hash=fingerprint_hash,
        exception_type=exception_type or None,
        raw_text=raw_text,
    )


class Embedder:
    """Swappable embedding interface."""

    def embed(self, text):
        raise NotImplementedError


class SentenceTransformerEmbedder(Embedder):
    """Lazy-loaded sentence-transformers embedder (separate from FAISS storage)."""

    _shared_model = None
    _shared_model_name = None

    def __init__(self, model_name=DEFAULT_EMBEDDING_MODEL):
        self.model_name = model_name

    def embed(self, text):
        if not text:
            return None
        try:
            model = self._get_model()
            vector = model.encode(text, normalize_embeddings=True)
            return vector.tolist()
        except Exception:
            return None

    def _get_model(self):
        if (
            SentenceTransformerEmbedder._shared_model is not None
            and SentenceTransformerEmbedder._shared_model_name == self.model_name
        ):
            return SentenceTransformerEmbedder._shared_model

        from sentence_transformers import SentenceTransformer  # noqa: PLC0415

        SentenceTransformerEmbedder._shared_model = SentenceTransformer(self.model_name)
        SentenceTransformerEmbedder._shared_model_name = self.model_name
        return SentenceTransformerEmbedder._shared_model


def get_default_embedder():
    """Return the default embedder or ``None`` when dependencies are unavailable."""
    try:
        import sentence_transformers  # noqa: F401, PLC0415
    except ImportError:
        return None
    return SentenceTransformerEmbedder()


def cosine_similarity(left, right):
    """Cosine similarity for unit-normalized vectors."""
    if not left or not right or len(left) != len(right):
        return 0.0
    return float(sum(a * b for a, b in zip(left, right)))


__all__ = [
    "DEFAULT_EMBEDDING_MODEL",
    "Embedder",
    "FailureFingerprint",
    "SentenceTransformerEmbedder",
    "build_failure_fingerprint",
    "cosine_similarity",
    "get_default_embedder",
    "normalize_failure_text",
]
