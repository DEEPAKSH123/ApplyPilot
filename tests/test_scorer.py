"""Focused regression tests for deterministic scoring response parsing."""

import sqlite3

from applypilot.scoring.scorer import _parse_score_response, _persist_scores


def test_parse_complete_score_response():
    parsed = _parse_score_response(
        "SCORE: 8\nKEYWORDS: Java, Kafka, Redis\nREASONING: Strong backend match."
    )

    assert parsed == {
        "score": 8,
        "keywords": "Java, Kafka, Redis",
        "reasoning": "Strong backend match.",
    }


def test_parse_score_is_clamped_to_supported_range():
    assert _parse_score_response(
        "SCORE: 99\nKEYWORDS: APIs\nREASONING: Good."
    )["score"] == 10

    assert _parse_score_response(
        "SCORE: 0\nKEYWORDS: APIs\nREASONING: Weak."
    )["score"] == 1


def test_malformed_score_is_marked_unscored():
    parsed = _parse_score_response(
        "SCORE: unavailable\nKEYWORDS: Java\nREASONING: Could not evaluate."
    )

    assert parsed["score"] == 0
    assert parsed["keywords"] == "Java"
    assert parsed["reasoning"] == "Could not evaluate."



def test_persist_scores_leaves_transient_failures_pending():
    conn = sqlite3.connect(":memory:")
    conn.execute(
        "CREATE TABLE jobs (url TEXT PRIMARY KEY, fit_score INTEGER, score_reasoning TEXT, scored_at TEXT)"
    )
    conn.executemany(
        "INSERT INTO jobs (url) VALUES (?)",
        [("https://example.com/valid",), ("https://example.com/retry",)],
    )

    persisted = _persist_scores(
        conn,
        [
            {
                "url": "https://example.com/valid",
                "score": 8,
                "keywords": "Java",
                "reasoning": "Good match.",
            },
            {
                "url": "https://example.com/retry",
                "score": 0,
                "keywords": "",
                "reasoning": "LLM error: rate limited",
            },
        ],
        "2026-11-16T00:00:00+00:00",
    )

    rows = dict(conn.execute("SELECT url, fit_score FROM jobs").fetchall())
    assert persisted == 1
    assert rows["https://example.com/valid"] == 8
    assert rows["https://example.com/retry"] is None
