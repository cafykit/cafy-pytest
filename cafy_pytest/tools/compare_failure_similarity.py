#!/usr/bin/env python3
"""Compare normalized failure fingerprints and embedding similarity."""

from __future__ import print_function

import argparse
import sys

from cafy_pytest.netpilot_similarity import (
    build_failure_fingerprint,
    get_default_embedder,
)


def compare(text_a, text_b, threshold):
    fingerprint_a = build_failure_fingerprint(None, text_a)
    fingerprint_b = build_failure_fingerprint(None, text_b)

    print("normalized A:", fingerprint_a.normalized_text)
    print("normalized B:", fingerprint_b.normalized_text)
    print("hash A:", fingerprint_a.fingerprint_hash)
    print("hash B:", fingerprint_b.fingerprint_hash)

    if fingerprint_a.fingerprint_hash == fingerprint_b.fingerprint_hash:
        print("similarity score: 1.0 (exact hash match)")
        print("match at configured threshold? yes")
        return 0

    embedder = get_default_embedder()
    if embedder is None:
        print("embedding unavailable; install sentence-transformers to compute semantic score", file=sys.stderr)
        return 1

    vector_a = embedder.embed(fingerprint_a.normalized_text)
    vector_b = embedder.embed(fingerprint_b.normalized_text)
    if vector_a is None or vector_b is None:
        print("embedding failed", file=sys.stderr)
        return 1

    score = sum(a * b for a, b in zip(vector_a, vector_b))
    matched = score >= threshold
    print("similarity score:", round(score, 4))
    print("match at configured threshold? {}".format("yes" if matched else "no"))
    return 0


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("text_a", help="First failure message")
    parser.add_argument("text_b", help="Second failure message")
    parser.add_argument(
        "--threshold",
        type=float,
        default=0.85,
        help="Cosine similarity threshold (default: 0.85)",
    )
    args = parser.parse_args(argv)
    return compare(args.text_a, args.text_b, args.threshold)


if __name__ == "__main__":
    sys.exit(main())
