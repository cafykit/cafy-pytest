"""Lightweight counters for NetPilot routing and similarity decisions."""


class NetPilotMetrics:
    """Process-local counters for NetPilot triage observability."""

    def __init__(self):
        self.total_failures_considered = 0
        self.hard_skips = 0
        self.routes_by_agent = {}
        self.fallback_count = 0
        self.exact_fingerprint_matches = 0
        self.semantic_similarity_matches = 0
        self.would_skip_shadow = 0
        self.similarity_skips = 0
        self.embedding_failures = 0
        self.vector_db_failures = 0

    def record_hard_skip(self):
        self.hard_skips += 1

    def record_route(self, agent, *, fallback=False):
        self.routes_by_agent[agent] = self.routes_by_agent.get(agent, 0) + 1
        if fallback:
            self.fallback_count += 1

    def record_exact_match(self):
        self.exact_fingerprint_matches += 1

    def record_semantic_match(self, *, shadow=True):
        self.semantic_similarity_matches += 1
        if shadow:
            self.would_skip_shadow += 1

    def record_similarity_skip(self):
        self.similarity_skips += 1

    def record_embedding_failure(self):
        self.embedding_failures += 1

    def record_vector_db_failure(self):
        self.vector_db_failures += 1

    def summary(self):
        return {
            "total_failures_considered": self.total_failures_considered,
            "hard_skips": self.hard_skips,
            "routes_by_agent": dict(self.routes_by_agent),
            "fallback_count": self.fallback_count,
            "exact_fingerprint_matches": self.exact_fingerprint_matches,
            "semantic_similarity_matches": self.semantic_similarity_matches,
            "would_skip_shadow": self.would_skip_shadow,
            "similarity_skips": self.similarity_skips,
            "embedding_failures": self.embedding_failures,
            "vector_db_failures": self.vector_db_failures,
        }


_GLOBAL_METRICS = NetPilotMetrics()


def get_metrics():
    return _GLOBAL_METRICS
