"""FAISS-backed vector store with a lightweight JSON metadata sidecar."""

from __future__ import annotations

import json
import os
import threading
import uuid
from datetime import datetime, timezone

import numpy as np

try:
    import faiss
except ImportError:
    faiss = None


VECTORSTORE_DIRNAME = ".netpilot/vectorstore"
INDEX_FILENAME = "failures.faiss"
METADATA_FILENAME = "metadata.json"
DEFAULT_TOP_K = 10


def vectorstore_path(work_dir):
    return os.path.join(work_dir, VECTORSTORE_DIRNAME)


def _now_iso():
    return datetime.now(timezone.utc).isoformat()


class SimilarityMatch:
    """Result of an exact or semantic similarity lookup."""

    __slots__ = ("record_id", "score", "nodeid", "match_type")

    def __init__(self, record_id, score, nodeid, match_type):
        self.record_id = record_id
        self.score = score
        self.nodeid = nodeid
        self.match_type = match_type


class FailureMetadataStore:
    """JSON metadata store for exact fingerprint matches without FAISS."""

    def __init__(self, work_dir):
        self.work_dir = work_dir
        self.store_dir = vectorstore_path(work_dir)
        self.metadata_path = os.path.join(self.store_dir, METADATA_FILENAME)
        self._lock = threading.Lock()
        self._metadata = {"version": 1, "dimension": None, "records": {}}
        self._load()

    def _load(self):
        os.makedirs(self.store_dir, exist_ok=True)
        if os.path.isfile(self.metadata_path):
            with open(self.metadata_path, "r", encoding="utf-8") as handle:
                self._metadata = json.load(handle)

    def _persist(self):
        os.makedirs(self.store_dir, exist_ok=True)
        with open(self.metadata_path, "w", encoding="utf-8") as handle:
            json.dump(self._metadata, handle, indent=2, sort_keys=True)

    @staticmethod
    def _record_matches_filters(record, *, agent, scope_id, fingerprint_hash=None):
        if record.get("agent") != agent:
            return False
        if record.get("scope_id") != scope_id:
            return False
        if fingerprint_hash is not None and record.get("fingerprint_hash") != fingerprint_hash:
            return False
        return True

    def find_exact(self, fingerprint_hash, agent, scope_id):
        for record_id, record in self._metadata.get("records", {}).items():
            if self._record_matches_filters(
                record,
                agent=agent,
                scope_id=scope_id,
                fingerprint_hash=fingerprint_hash,
            ):
                return SimilarityMatch(
                    record_id=record_id,
                    score=1.0,
                    nodeid=record.get("nodeid"),
                    match_type="exact",
                )
        return None

    def find_similar(self, embedding, agent, scope_id, threshold, top_k=DEFAULT_TOP_K):
        return None

    def upsert(self, record):
        with self._lock:
            record_id = str(len(self._metadata.setdefault("records", {})))
            record_uuid = record.get("id") or uuid.uuid4().hex
            self._metadata["records"][record_id] = {
                "id": record_uuid,
                "fingerprint_hash": record.get("fingerprint_hash"),
                "normalized_text": record.get("normalized_text"),
                "agent": record.get("agent"),
                "scope_id": record.get("scope_id"),
                "nodeid": record.get("nodeid"),
                "exception_type": record.get("exception_type"),
                "created_at": record.get("created_at") or _now_iso(),
            }
            self._persist()
            return record_id


class FailureVectorStore:
    """Local FAISS index with JSON metadata for agent/scope filtering."""

    def __init__(self, work_dir, *, dimension=None):
        if faiss is None:
            raise RuntimeError("faiss is not installed")

        self.work_dir = work_dir
        self.store_dir = vectorstore_path(work_dir)
        self.index_path = os.path.join(self.store_dir, INDEX_FILENAME)
        self.metadata_path = os.path.join(self.store_dir, METADATA_FILENAME)
        self._lock = threading.Lock()
        self.dimension = dimension
        self._index = None
        self._metadata = {"version": 1, "dimension": None, "records": {}}
        self._load()

    def _load(self):
        os.makedirs(self.store_dir, exist_ok=True)

        if os.path.isfile(self.metadata_path):
            with open(self.metadata_path, "r", encoding="utf-8") as handle:
                self._metadata = json.load(handle)

        stored_dimension = self._metadata.get("dimension")
        if stored_dimension is not None:
            self.dimension = stored_dimension

        if os.path.isfile(self.index_path) and self.dimension:
            self._index = faiss.read_index(self.index_path)
        elif self.dimension:
            self._index = faiss.IndexFlatIP(self.dimension)
        else:
            self._index = None

    def _ensure_index(self, dimension):
        if self._index is not None:
            if self._index.d != dimension:
                raise ValueError(
                    "embedding dimension {} does not match index dimension {}".format(
                        dimension, self._index.d
                    )
                )
            return

        self.dimension = dimension
        self._index = faiss.IndexFlatIP(dimension)
        self._metadata["dimension"] = dimension

    def _persist(self):
        os.makedirs(self.store_dir, exist_ok=True)
        if self._index is not None and self._index.ntotal > 0:
            faiss.write_index(self._index, self.index_path)
        with open(self.metadata_path, "w", encoding="utf-8") as handle:
            json.dump(self._metadata, handle, indent=2, sort_keys=True)

    @staticmethod
    def _record_matches_filters(record, *, agent, scope_id, fingerprint_hash=None):
        if record.get("agent") != agent:
            return False
        if record.get("scope_id") != scope_id:
            return False
        if fingerprint_hash is not None and record.get("fingerprint_hash") != fingerprint_hash:
            return False
        return True

    def find_exact(self, fingerprint_hash, agent, scope_id):
        for record_id, record in self._metadata.get("records", {}).items():
            if self._record_matches_filters(
                record,
                agent=agent,
                scope_id=scope_id,
                fingerprint_hash=fingerprint_hash,
            ):
                return SimilarityMatch(
                    record_id=record_id,
                    score=1.0,
                    nodeid=record.get("nodeid"),
                    match_type="exact",
                )
        return None

    def find_similar(self, embedding, agent, scope_id, threshold, top_k=DEFAULT_TOP_K):
        if self._index is None or self._index.ntotal == 0:
            return None
        if not embedding:
            return None

        vector = np.asarray([embedding], dtype=np.float32)
        faiss.normalize_L2(vector)
        scores, indices = self._index.search(vector, min(top_k, self._index.ntotal))

        best_match = None
        records = self._metadata.get("records", {})
        for score, faiss_id in zip(scores[0], indices[0]):
            if faiss_id < 0:
                continue
            record_id = str(int(faiss_id))
            record = records.get(record_id)
            if record is None:
                continue
            if record.get("agent") != agent or record.get("scope_id") != scope_id:
                continue
            score_value = float(score)
            if score_value < threshold:
                continue
            if best_match is None or score_value > best_match.score:
                best_match = SimilarityMatch(
                    record_id=record_id,
                    score=score_value,
                    nodeid=record.get("nodeid"),
                    match_type="semantic",
                )
        return best_match

    def upsert(self, record):
        embedding = record.get("embedding")
        if not embedding:
            raise ValueError("record.embedding is required for FAISS vector store")

        with self._lock:
            self._ensure_index(len(embedding))
            faiss_id = str(self._index.ntotal)
            vector = np.asarray([embedding], dtype=np.float32)
            faiss.normalize_L2(vector)
            self._index.add(vector)

            record_uuid = record.get("id") or uuid.uuid4().hex
            self._metadata.setdefault("records", {})[faiss_id] = {
                "id": record_uuid,
                "fingerprint_hash": record.get("fingerprint_hash"),
                "normalized_text": record.get("normalized_text"),
                "agent": record.get("agent"),
                "scope_id": record.get("scope_id"),
                "nodeid": record.get("nodeid"),
                "exception_type": record.get("exception_type"),
                "created_at": record.get("created_at") or _now_iso(),
            }
            self._persist()
            return faiss_id


def open_vector_store(work_dir):
    """Open the vector store, falling back to metadata-only when FAISS is unavailable."""
    if not work_dir:
        return None
    if faiss is not None:
        try:
            return FailureVectorStore(work_dir)
        except Exception:
            pass
    try:
        return FailureMetadataStore(work_dir)
    except Exception:
        return None


__all__ = [
    "FailureMetadataStore",
    "FailureVectorStore",
    "SimilarityMatch",
    "open_vector_store",
    "vectorstore_path",
]
