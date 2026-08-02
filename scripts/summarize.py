"""Summarize newly collected items into Japanese using the Claude API."""

import json
import os
import re
from pathlib import Path

import anthropic

MODEL = os.environ.get("CLAUDE_MODEL", "claude-haiku-4-5-20251001")

# Deterministic source -> Notion category mapping (matches the "AIトレンド Inbox"
# database's カテゴリ select options).
SOURCE_TO_CATEGORY = {
    "Claude Code Changelog": "Claude Code",
    "Anthropic News": "Anthropic公式",
    "arXiv": "業界動向",
    "Hacker News": "コミュニティ",
    "Reddit": "コミュニティ",
}

SYSTEM_PROMPT = """あなたはAI/Claude関連ニュースの編集者です。
渡された英語(一部日本語)の記事リストについて、それぞれ次の2つを日本語で作成してください。

1. title_ja: 15〜25文字程度の日本語の見出し
2. summary_ja: 100〜200文字程度の日本語要約(専門用語はそのまま使ってよい)

出力は必ず次のJSON配列のみ。前置き・後書き・コードフェンスは一切不要です。
[{"id": <入力のid>, "title_ja": "...", "summary_ja": "..."}, ...]
"""


def build_user_prompt(items):
    blocks = []
    for i, item in enumerate(items):
        blocks.append(
            f"id: {i}\nsource: {item['source']}\ntitle: {item['title']}\n"
            f"snippet: {item.get('snippet', '')[:500]}"
        )
    return "\n---\n".join(blocks)


def parse_json_array(text):
    """Best-effort JSON extraction. Models sometimes ignore the "no code
    fences" instruction, or add a stray sentence before/after the array.
    Try a straight parse first, then fall back to stripping fences / pulling
    out the outermost [...] before giving up."""
    candidates = [text.strip()]

    fence_match = re.match(r"^```(?:json)?\s*(.*?)\s*```$", text.strip(), re.DOTALL)
    if fence_match:
        candidates.append(fence_match.group(1).strip())

    bracket_match = re.search(r"\[.*\]", text, re.DOTALL)
    if bracket_match:
        candidates.append(bracket_match.group(0))

    for candidate in candidates:
        try:
            return json.loads(candidate)
        except json.JSONDecodeError:
            continue
    return None


def main():
    raw_items = json.loads(Path("raw_data.json").read_text())
    if not raw_items:
        Path("digest.json").write_text("[]")
        print("No new items to summarize.")
        return

    api_key = os.environ.get("ANTHROPIC_API_KEY", "").strip()
    if not api_key:
        raise SystemExit(
            "ANTHROPIC_API_KEY is not set (or is empty). "
            "Add it under Settings > Secrets and variables > Actions in this repo."
        )
    client = anthropic.Anthropic(api_key=api_key)

    digest = []
    batch_size = 15  # keep prompts small and requests cheap
    for start in range(0, len(raw_items), batch_size):
        batch = raw_items[start:start + batch_size]
        response = client.messages.create(
            model=MODEL,
            max_tokens=4000,
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": build_user_prompt(batch)}],
        )
        text = "".join(block.text for block in response.content if block.type == "text")
        translations = parse_json_array(text)
        if translations is None:
            print("Failed to parse model output as JSON, skipping this batch. Raw output was:")
            print(text[:1000])
            continue

        for t in translations:
            item = batch[t["id"]]
            digest.append({
                "category": SOURCE_TO_CATEGORY.get(item["source"], "コミュニティ"),
                "source": item["source"],
                "source_url": item["url"],
                "published_date": item.get("published_date"),
                "title_ja": t["title_ja"],
                "summary_ja": t["summary_ja"],
            })

    Path("digest.json").write_text(json.dumps(digest, ensure_ascii=False, indent=2))
    print(f"Summarized {len(digest)} item(s).")
    if raw_items and not digest:
        raise SystemExit(
            f"summarize.py collected {len(raw_items)} item(s) but produced 0 digest "
            "entries -- the model's output likely wasn't valid JSON. Check the "
            "'Failed to parse model output as JSON' log lines above for the raw output."
        )


if __name__ == "__main__":
    main()
