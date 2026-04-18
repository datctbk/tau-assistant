from __future__ import annotations

from web_source_ranker import normalize_and_rank_sources


def test_normalize_and_rank_sources_strips_tracking_params():
    ranked = normalize_and_rank_sources(
        query="python docs",
        items=[
            {
                "title": "Python docs",
                "url": "https://docs.python.org/3/?utm_source=x&ref=abc&q=1#frag",
                "snippet": "Official docs",
            }
        ],
    )
    assert len(ranked) == 1
    assert ranked[0]["url"] == "https://docs.python.org/3/?q=1"
    assert ranked[0]["trust_tier"] == "high"


def test_normalize_and_rank_sources_prefers_high_trust():
    ranked = normalize_and_rank_sources(
        query="python testing",
        items=[
            {"title": "Unknown", "url": "https://unknown.example.com/post", "snippet": "python testing guide"},
            {"title": "Python docs", "url": "https://docs.python.org/3/library/unittest.html", "snippet": "testing"},
        ],
    )
    assert len(ranked) == 2
    assert ranked[0]["domain"] == "docs.python.org"
    assert ranked[0]["trust_score"] >= ranked[1]["trust_score"]

