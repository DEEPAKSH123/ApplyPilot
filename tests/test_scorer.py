"""Focused regression tests for deterministic scoring response parsing."""

from applypilot.scoring.scorer import _parse_score_response


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
