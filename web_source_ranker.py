from __future__ import annotations

import re
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

# Keep trust tiers aligned with tau-web defaults.
TRUST_HIGH = {
    "docs.python.org",
    "pypi.org",
    "packaging.python.org",
    "docs.rs",
    "crates.io",
    "developer.mozilla.org",
    "www.w3.org",
    "github.com",
    "raw.githubusercontent.com",
    "gist.github.com",
    "stackoverflow.com",
    "superuser.com",
    "serverfault.com",
    "en.wikipedia.org",
    "registry.npmjs.org",
    "www.npmjs.com",
    "pkg.go.dev",
    "go.dev",
    "hub.docker.com",
    "learn.microsoft.com",
    "docs.microsoft.com",
    "cloud.google.com",
    "docs.aws.amazon.com",
    "api.github.com",
}
TRUST_MEDIUM = {
    "medium.com",
    "dev.to",
    "news.ycombinator.com",
    "reddit.com",
    "www.reddit.com",
}
TRACKING_QUERY_PREFIXES = ("utm_", "ref", "fbclid", "gclid", "mc_cid", "mc_eid")
TOKEN_RE = re.compile(r"[a-z0-9]{2,}")


def _normalize_url(url: str) -> str:
    try:
        parsed = urlparse(url)
        query_items = []
        for key, value in parse_qsl(parsed.query, keep_blank_values=True):
            low = key.lower()
            if any(low.startswith(prefix) for prefix in TRACKING_QUERY_PREFIXES):
                continue
            query_items.append((key, value))
        return urlunparse((parsed.scheme, parsed.netloc.lower(), parsed.path, "", urlencode(query_items), ""))
    except Exception:
        return url


def _source_trust(domain: str) -> tuple[str, int]:
    d = domain.lower().strip()
    if d in TRUST_HIGH:
        return "high", 3
    if d in TRUST_MEDIUM:
        return "medium", 2
    return "unknown", 1


def _tokenize(text: str) -> set[str]:
    return set(TOKEN_RE.findall((text or "").lower()))


def _relevance_score(query: str, title: str, snippet: str) -> int:
    q = _tokenize(query)
    if not q:
        return 0
    title_tokens = _tokenize(title)
    snippet_tokens = _tokenize(snippet)
    title_hits = len(q & title_tokens)
    snippet_hits = len(q & snippet_tokens)
    return (title_hits * 3) + snippet_hits


def normalize_and_rank_sources(query: str, items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    ranked: list[dict[str, Any]] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        normalized_url = _normalize_url(str(item.get("url", "")).strip())
        domain = urlparse(normalized_url).netloc.lower()
        trust_tier, trust_score = _source_trust(domain)
        title = str(item.get("title", "")).strip()
        snippet = str(item.get("snippet", "")).strip()
        relevance = _relevance_score(query, title, snippet)
        composite = (trust_score * 100) + relevance
        ranked.append(
            {
                **item,
                "url": normalized_url,
                "domain": domain,
                "trust_tier": trust_tier,
                "trust_score": trust_score,
                "relevance_score": relevance,
                "rank_score": composite,
                "ranking_reason": (
                    f"trust={trust_tier}({trust_score}), relevance={relevance} "
                    f"for query token overlap"
                ),
            }
        )
    ranked.sort(
        key=lambda row: (
            int(row.get("rank_score", 0)),
            int(row.get("trust_score", 0)),
            str(row.get("title", "")).lower(),
        ),
        reverse=True,
    )
    return ranked
