"""Push summarized digest entries into the "AIトレンド Inbox" Notion database.

Each entry is created as a new page with status = 未読 (unread) so a human
reviews and re-statuses it later; this script never marks anything as read.
"""

import json
import os
import time
from pathlib import Path

import requests

NOTION_API_KEY = os.environ["NOTION_API_KEY"]
# Default points at the "AIトレンド Inbox" data source created for this project.
# Override with the NOTION_DATA_SOURCE_ID secret if you recreate the database.
DATA_SOURCE_ID = os.environ.get(
    "NOTION_DATA_SOURCE_ID", "5fff784e-7834-46c7-a322-4e68a1eb08a8"
)
NOTION_VERSION = "2025-09-03"

HEADERS = {
    "Authorization": f"Bearer {NOTION_API_KEY}",
    "Notion-Version": NOTION_VERSION,
    "Content-Type": "application/json",
}


def build_properties(entry):
    props = {
        "タイトル": {"title": [{"text": {"content": entry["title_ja"][:200]}}]},
        "日本語要約": {"rich_text": [{"text": {"content": entry["summary_ja"][:2000]}}]},
        "カテゴリ": {"select": {"name": entry["category"]}},
        "ソース": {"select": {"name": entry["source"]}},
        "ソースURL": {"url": entry["source_url"]},
        "ステータス": {"select": {"name": "未読"}},
    }
    if entry.get("published_date"):
        props["公開日"] = {"date": {"start": entry["published_date"]}}
    return props


def create_page(entry):
    payload = {
        "parent": {"type": "data_source_id", "data_source_id": DATA_SOURCE_ID},
        "properties": build_properties(entry),
    }
    resp = requests.post(
        "https://api.notion.com/v1/pages", headers=HEADERS, json=payload, timeout=15
    )
    if not resp.ok:
        print(f"Failed to create page for {entry['source_url']}: {resp.status_code} {resp.text}")
    else:
        print(f"Created: {entry['title_ja']}")
    return resp.ok


def main():
    digest = json.loads(Path("digest.json").read_text())
    ok, failed = 0, 0
    for entry in digest:
        if create_page(entry):
            ok += 1
        else:
            failed += 1
        time.sleep(0.35)  # stay comfortably under Notion's rate limit
    print(f"Done. {ok} created, {failed} failed.")


if __name__ == "__main__":
    main()
