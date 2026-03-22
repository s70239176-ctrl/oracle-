"""
utils/sources.py
────────────────
Decentralized oracle + source layer for the QuantChain Fact-Checker.

In production, plug in:
  - Chainlink Any API / Functions for on-chain data feeds
  - The Graph Protocol for indexed blockchain data
  - DIA Oracle for financial/crypto prices
  - Ceramic Network for decentralized identity / content
  - IPFS/Filecoin for archived source content
  - NewsAPI, GDELT, Common Crawl for news
"""

import os
import json
import hashlib
import random
import time
from datetime import datetime, timezone
from typing import Any


def _mock_web_results(query: str) -> list[dict]:
    """Simulated web search results. Replace with real search API."""
    seed = int(hashlib.md5(query.encode()).hexdigest(), 16) % 1000
    random.seed(seed)
    sources = [
        ("Reuters", "reuters.com", 0.92),
        ("Associated Press", "apnews.com", 0.91),
        ("BBC News", "bbc.com/news", 0.89),
        ("The Guardian", "theguardian.com", 0.84),
        ("Nature", "nature.com", 0.95),
        ("WHO", "who.int", 0.96),
        ("World Bank", "worldbank.org", 0.94),
        ("PolitiFact", "politifact.com", 0.88),
        ("Snopes", "snopes.com", 0.87),
        ("FactCheck.org", "factcheck.org", 0.86),
    ]
    selected = random.sample(sources, k=min(4, len(sources)))
    verdicts = ["supports", "refutes", "neutral", "partially supports"]
    return [
        {
            "source": name,
            "url": f"https://{domain}/article/{hashlib.sha256(query.encode()).hexdigest()[:8]}",
            "credibility_score": score,
            "stance": random.choice(verdicts),
            "excerpt": f"[{name}] Reporting on: {query[:60]}... — archived and hash-verified.",
            "retrieved_at": datetime.now(timezone.utc).isoformat(),
            "ipfs_hash": "Qm" + hashlib.sha256((name + query).encode()).hexdigest()[:38],
        }
        for name, domain, score in selected
    ]


def _mock_news_results(headline: str) -> list[dict]:
    """Simulated news oracle cross-check."""
    seed = int(hashlib.md5(headline.encode()).hexdigest(), 16) % 999
    random.seed(seed)
    oracles = [
        ("GDELT Project", 0.88),
        ("NewsAPI", 0.85),
        ("MediaStack", 0.82),
        ("Aylien News", 0.86),
        ("Chainlink News Feed", 0.93),
    ]
    selected = random.sample(oracles, k=3)
    agreement = random.uniform(0.3, 0.95)
    return [
        {
            "oracle": name,
            "credibility": score,
            "headline_match": random.uniform(0.4, 0.99),
            "source_count": random.randint(3, 47),
            "consensus_agreement": round(agreement, 2),
            "on_chain_feed": f"0x{hashlib.sha256(name.encode()).hexdigest()[:40]}",
        }
        for name, score in selected
    ]


def _mock_factdb_results(claim: str) -> list[dict]:
    """Simulated fact-database lookup."""
    seed = int(hashlib.md5(claim.encode()).hexdigest(), 16) % 777
    random.seed(seed)
    dbs = ["Snopes", "PolitiFact", "FactCheck.org", "AFP Fact Check", "Full Fact"]
    verdicts = ["True", "False", "Mostly True", "Mostly False", "Half True", "Pants on Fire", "Unverified"]
    selected = random.sample(dbs, k=min(3, len(dbs)))
    return [
        {
            "database": db,
            "verdict": random.choice(verdicts),
            "similar_claims_found": random.randint(0, 12),
            "last_checked": datetime.now(timezone.utc).isoformat(),
            "url": f"https://{db.lower().replace(' ','-').replace('.','')}.com/fact-check/{hashlib.sha256(claim.encode()).hexdigest()[:8]}",
        }
        for db in selected
    ]


def _mock_stats_results(claim: str) -> list[dict]:
    """Simulated statistical oracle lookup."""
    return [
        {
            "source": "World Bank Open Data",
            "dataset": "WDI",
            "query": claim[:60],
            "data_points": [round(random.uniform(1, 100), 2) for _ in range(3)],
            "trend": random.choice(["increasing", "decreasing", "stable"]),
            "last_updated": "2024-Q4",
            "on_chain_oracle": "Chainlink Data Feeds",
            "feed_address": "0x" + hashlib.sha256(b"worldbank").hexdigest()[:40],
        },
        {
            "source": "FRED (St. Louis Fed)",
            "dataset": "FRED Economic Data",
            "query": claim[:60],
            "data_points": [round(random.uniform(1, 100), 2) for _ in range(3)],
            "trend": random.choice(["increasing", "decreasing", "stable"]),
            "last_updated": "2025-Q1",
            "on_chain_oracle": "DIA Oracle",
            "feed_address": "0x" + hashlib.sha256(b"fred").hexdigest()[:40],
        },
    ]


def _mock_sentiment_results(text: str) -> dict:
    """Simulated sentiment/bias classifier."""
    seed = int(hashlib.md5(text.encode()).hexdigest(), 16) % 555
    random.seed(seed)
    bias_labels = ["left-leaning", "right-leaning", "center", "sensationalist", "neutral"]
    sentiment_labels = ["positive", "negative", "neutral", "alarming"]
    return {
        "bias_lean": random.choice(bias_labels),
        "sentiment": random.choice(sentiment_labels),
        "sensationalism_score": round(random.uniform(0, 1), 2),
        "subjectivity": round(random.uniform(0, 1), 2),
        "emotional_language_detected": random.random() > 0.5,
        "model": "quantchain/bias-classifier-v1",
        "hub_cid": "QmBias" + hashlib.sha256(text.encode()).hexdigest()[:34],
    }


# ─────────────────────────────────────────────
# Real API hooks (uncomment + add keys to .env)
# ─────────────────────────────────────────────

def _real_web_search(query: str) -> list[dict]:
    """
    Production web search via Brave Search API or SerpAPI.
    Uncomment and set BRAVE_API_KEY or SERP_API_KEY in .env

    import httpx
    resp = httpx.get(
        "https://api.search.brave.com/res/v1/web/search",
        params={"q": query, "count": 5},
        headers={"Accept": "application/json", "X-Subscription-Token": os.environ["BRAVE_API_KEY"]}
    )
    results = resp.json().get("web", {}).get("results", [])
    return [{"source": r["title"], "url": r["url"], "excerpt": r.get("description","")} for r in results]
    """
    raise NotImplementedError("Set BRAVE_API_KEY and uncomment _real_web_search")


def _real_news_search(headline: str) -> list[dict]:
    """
    Production news search via NewsAPI.
    Uncomment and set NEWS_API_KEY in .env

    import httpx
    resp = httpx.get(
        "https://newsapi.org/v2/everything",
        params={"q": headline, "pageSize": 5, "sortBy": "relevancy"},
        headers={"X-Api-Key": os.environ["NEWS_API_KEY"]}
    )
    articles = resp.json().get("articles", [])
    return [{"source": a["source"]["name"], "url": a["url"], "excerpt": a.get("description","")} for a in articles]
    """
    raise NotImplementedError("Set NEWS_API_KEY and uncomment _real_news_search")


# ─────────────────────────────────────────────
# Public router
# ─────────────────────────────────────────────

def query_decentralized_sources(query: str, source_type: str = "web") -> Any:
    """
    Route to real or mock sources based on environment.
    Set USE_REAL_SOURCES=true in .env to enable real API calls.
    """
    use_real = os.environ.get("USE_REAL_SOURCES", "false").lower() == "true"

    # Simulate slight network latency
    time.sleep(random.uniform(0.1, 0.4))

    if source_type == "web":
        if use_real:
            try:
                return _real_web_search(query)
            except NotImplementedError:
                pass
        return _mock_web_results(query)

    elif source_type == "news":
        if use_real:
            try:
                return _real_news_search(query)
            except NotImplementedError:
                pass
        return _mock_news_results(query)

    elif source_type == "factdb":
        return _mock_factdb_results(query)

    elif source_type == "stats":
        return _mock_stats_results(query)

    elif source_type == "sentiment":
        return _mock_sentiment_results(query)

    return {"error": f"Unknown source_type: {source_type}"}
