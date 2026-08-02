"""Collect recent AI/Claude-related items from a handful of curated sources.

Intended to run once a day via GitHub Actions.
Writes:  raw_data.json          (new items found this run)
Reads/updates: state/seen_ids.json  (dedup state, committed back to the repo)
"""

import json
import os
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path

import feedparser
import requests

STATE_PATH = Path("state/seen_ids.json")
LOOKBACK_HOURS = int(os.environ.get("LOOKBACK_HOURS", "30"))
MAX_STATE_AGE_DAYS = 14

# Keywords used to filter broad feeds (arXiv cs.AI, r/singularity) down to
# things actually relevant to Claude / LLMs. Anthropic + Claude Code specific
# feeds don't need this filter since everything they publish is on-topic.
KEYWORDS = [k.lower() for k in [
    "claude", "anthropic", "llm agent", "language model",
    "large language model", "rlhf", "ai agent",
]]

HEADERS = {"User-Agent": "ai-trend-digest/1.0 (personal use)"}


def load_seen():
    if STATE_PATH.exists():
        data = json.loads(STATE_PATH.read_text())
        cutoff = (datetime.now(timezone.utc) - timedelta(days=MAX_STATE_AGE_DAYS)).isoformat()
        # Drop old entries so the state file doesn't grow forever.
        return {k: v for k, v in data.items() if v > cutoff}
    return {}


def save_seen(seen):
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    STATE_PATH.write_text(json.dumps(seen, ensure_ascii=False, indent=2))


def within_lookback(published_struct):
    if not published_struct:
        # Keep items we can't date rather than silently dropping them.
        return True
    published = datetime(*published_struct[:6], tzinfo=timezone.utc)
    return published > datetime.now(timezone.utc) - timedelta(hours=LOOKBACK_HOURS)


def matches_keywords(text):
    text = text.lower()
    return any(k in text for k in KEYWORDS)


def struct_to_date_string(struct_time):
    """Convert feedparser's parsed *_parsed struct into a plain YYYY-MM-DD
    string. Different feeds format raw date strings differently (ISO 8601
    for Atom, RFC 822 for RSS 2.0), so date extraction elsewhere in this
    pipeline should always go through this helper rather than slicing a raw
    string and assuming a particular format."""
    if not struct_time:
        return None
    try:
        return datetime(*struct_time[:6], tzinfo=timezone.utc).date().isoformat()
    except (TypeError, ValueError):
        return None


def collect_claude_code_changelog():
    feed = feedparser.parse("https://github.com/anthropics/claude-code/releases.atom")
    items = []
    for e in feed.entries:
        if not within_lookback(e.get("published_parsed") or e.get("updated_parsed")):
            continue
        items.append({
            "source": "Claude Code Changelog",
            "title": e.title,
            "url": e.link,
            "published_date": struct_to_date_string(e.get("published_parsed") or e.get("updated_parsed")),
            "snippet": strip_html(e.get("summary", ""))[:600],
        })
    return items


def collect_arxiv():
    feed = feedparser.parse("http://export.arxiv.org/rss/cs.AI")
    items = []
    for e in feed.entries:
        text = f"{e.title} {e.get('summary', '')}"
        if not matches_keywords(text):
            continue
        items.append({
            "source": "arXiv",
            "title": e.title,
            "url": e.link,
            "published_date": struct_to_date_string(e.get("published_parsed")),
            "snippet": strip_html(e.get("summary", ""))[:600],
        })
    return items


def collect_hacker_news():
    items = []
    cutoff_ts = int((datetime.now(timezone.utc) - timedelta(hours=LOOKBACK_HOURS)).timestamp())
    for query in ["Claude", "Anthropic"]:
        resp = requests.get(
            "https://hn.algolia.com/api/v1/search_by_date",
            params={
                "query": query,
                "tags": "story",
                "numericFilters": f"created_at_i>{cutoff_ts}",
                "hitsPerPage": 15,
            },
            headers=HEADERS,
            timeout=15,
        )
        resp.raise_for_status()
        for hit in resp.json().get("hits", []):
            url = hit.get("url") or f"https://news.ycombinator.com/item?id={hit['objectID']}"
            created_at = hit.get("created_at", "")
            try:
                published_date = datetime.fromisoformat(created_at.replace("Z", "+00:00")).date().isoformat()
            except ValueError:
                published_date = None
            items.append({
                "source": "Hacker News",
                "title": hit.get("title") or hit.get("story_title") or "",
                "url": url,
                "published_date": published_date,
                "snippet": "",
            })
    return items


def collect_reddit():
    items = []
    for sub in ["ClaudeAI", "singularity"]:
        resp = requests.get(
            f"https://www.reddit.com/r/{sub}/new.json",
            params={"limit": 20},
            headers=HEADERS,
            timeout=15,
        )
        resp.raise_for_status()
        for child in resp.json().get("data", {}).get("children", []):
            post = child["data"]
            created = datetime.fromtimestamp(post["created_utc"], tz=timezone.utc)
            if created < datetime.now(timezone.utc) - timedelta(hours=LOOKBACK_HOURS):
                continue
            if sub == "singularity" and not matches_keywords(post.get("title", "")):
                continue
            items.append({
                "source": "Reddit",
                "title": post.get("title", ""),
                "url": f"https://www.reddit.com{post.get('permalink', '')}",
                "published_date": created.date().isoformat(),
                "snippet": (post.get("selftext") or "")[:600],
            })
    return items


def collect_anthropic_news():
    # Anthropic does not publish an official RSS feed for anthropic.com/news,
    # so this is a best-effort HTML scrape. If Anthropic changes the page
    # layout this returns an empty list (with a logged warning) instead of
    # crashing the whole pipeline.
    items = []
    try:
        from bs4 import BeautifulSoup

        resp = requests.get("https://www.anthropic.com/news", headers=HEADERS, timeout=15)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "html.parser")
        for a in soup.select("a[href^='/news/']")[:20]:
            href = a.get("href", "")
            title = a.get_text(strip=True)
            if not title or href.rstrip("/") == "/news":
                continue
            items.append({
                "source": "Anthropic News",
                "title": title,
                "url": f"https://www.anthropic.com{href}",
                "published_date": None,
                "snippet": "",
            })
    except Exception as exc:  # noqa: BLE001 - keep the pipeline alive
        print(f"[collect_anthropic_news] skipped due to: {exc}")
    return items


def main():
    seen = load_seen()
    collectors = [
        collect_claude_code_changelog,
        collect_arxiv,
        collect_hacker_news,
        collect_reddit,
        collect_anthropic_news,
    ]

    new_items = []
    now_iso = datetime.now(timezone.utc).isoformat()
    for collector in collectors:
        try:
            for item in collector():
                if item["url"] in seen:
                    continue
                seen[item["url"]] = now_iso
                new_items.append(item)
        except Exception as exc:  # noqa: BLE001 - one bad source shouldn't kill the run
            print(f"[{collector.__name__}] failed: {exc}")

    Path("raw_data.json").write_text(json.dumps(new_items, ensure_ascii=False, indent=2))
    save_seen(seen)
    print(f"Collected {len(new_items)} new item(s).")


if __name__ == "__main__":
    main()
