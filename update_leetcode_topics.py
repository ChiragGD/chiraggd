#!/usr/bin/env python3
"""Track accepted LeetCode submissions and generate a topic-count SVG.

Uses LeetCode's public GraphQL endpoint. The script remembers every accepted
problem it discovers in solved_problems.json, so the list grows across runs.
LeetCode's recent-accepted-submissions endpoint is limited; run this regularly
and understand that problems solved before the tracker was installed may not
all be discovered automatically.
"""
import json
import os
import html
import urllib.request
import urllib.error
from pathlib import Path

ROOT = Path(__file__).resolve().parent
USERNAME = os.environ.get("LEETCODE_USERNAME", "chiraggd")
GRAPHQL_URL = "https://leetcode.com/graphql"
SOLVED_FILE = ROOT / "solved_problems.json"
SVG_FILE = ROOT / "leetcode-topics.svg"
COUNTS_FILE = ROOT / "topic_counts.json"

QUERY_RECENT = """
query recentAcSubmissions($username: String!, $limit: Int!) {
  recentAcSubmissionList(username: $username, limit: $limit) {
    title
    titleSlug
    timestamp
  }
}
"""
QUERY_TAGS = """
query questionTags($titleSlug: String!) {
  question(titleSlug: $titleSlug) {
    title
    titleSlug
    topicTags {
      name
    }
  }
}
"""

def graphql(query, variables):
    payload = json.dumps({"query": query, "variables": variables}).encode("utf-8")
    req = urllib.request.Request(
        GRAPHQL_URL,
        data=payload,
        headers={
            "Content-Type": "application/json",
            "Referer": f"https://leetcode.com/{USERNAME}/",
            "User-Agent": "Mozilla/5.0 (compatible; LeetCodeTopicTracker/1.0)",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as response:
            data = json.loads(response.read().decode("utf-8"))
    except (urllib.error.URLError, TimeoutError) as exc:
        raise RuntimeError(f"Could not reach LeetCode GraphQL endpoint: {exc}") from exc
    if data.get("errors"):
        raise RuntimeError("LeetCode GraphQL returned errors: " + json.dumps(data["errors"]))
    if "data" not in data:
        raise RuntimeError("Unexpected response from LeetCode GraphQL.")
    return data["data"]

def load_solved():
    if not SOLVED_FILE.exists():
        return {}
    try:
        payload = json.loads(SOLVED_FILE.read_text(encoding="utf-8"))
        return payload.get("problems", {})
    except (json.JSONDecodeError, OSError):
        return {}

def save_json(path, obj):
    path.write_text(json.dumps(obj, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

def make_svg(counts):
    width, left, right, top, row_h, bar_h, bottom = 1000, 250, 70, 78, 38, 20, 52
    topics = sorted(counts.items(), key=lambda kv: (-kv[1], kv[0].lower()))
    height = top + len(topics) * row_h + bottom
    plot_w = width - left - right
    max_count = max([v for _, v in topics] + [1])
    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}" role="img" aria-labelledby="title desc">',
        '<title id="title">LeetCode problems solved by topic</title>',
        '<desc id="desc">Counts are calculated from unique accepted problems discovered by the tracker.</desc>',
        '<rect width="100%" height="100%" fill="#ffffff" rx="14"/>',
        f'<text x="{left}" y="34" font-family="Arial,sans-serif" font-size="22" font-weight="700" fill="#222">LeetCode Problems Solved by Topic</text>',
        f'<text x="{left}" y="56" font-family="Arial,sans-serif" font-size="12" fill="#666">Profile: leetcode.com/u/{html.escape(USERNAME)}/ · unique accepted problems discovered</text>',
    ]
    for i in range(6):
        x = left + plot_w * i / 5
        value = round(max_count * i / 5)
        parts.append(f'<line x1="{x:.1f}" y1="{top-8}" x2="{x:.1f}" y2="{height-bottom+2}" stroke="#e6e8eb"/>')
        parts.append(f'<text x="{x:.1f}" y="{height-21}" text-anchor="middle" font-family="Arial,sans-serif" font-size="12" fill="#555">{value}</text>')
    for i, (topic, count) in enumerate(topics):
        y = top + i * row_h
        bar_w = plot_w * count / max_count if count else 0
        parts.append(f'<text x="{left-14}" y="{y+bar_h/2+4}" text-anchor="end" font-family="Arial,sans-serif" font-size="14" fill="#333">{html.escape(topic)}</text>')
        parts.append(f'<rect x="{left}" y="{y}" width="{plot_w}" height="{bar_h}" rx="5" fill="#f0f2f5"/>')
        if bar_w > 0:
            parts.append(f'<rect x="{left}" y="{y}" width="{bar_w:.2f}" height="{bar_h}" rx="5" fill="#2da44e"/>')
        parts.append(f'<text x="{left + (bar_w if bar_w else 0) + 8:.2f}" y="{y+bar_h/2+4}" font-family="Arial,sans-serif" font-size="13" fill="#333">{count}</text>')
    parts.extend([
        f'<text x="{left+plot_w/2:.1f}" y="{height-4}" text-anchor="middle" font-family="Arial,sans-serif" font-size="12" fill="#555">Unique accepted problems</text>',
        '</svg>'
    ])
    SVG_FILE.write_text("\n".join(parts) + "\n", encoding="utf-8")

def main():
    existing = load_solved()
    recent = graphql(QUERY_RECENT, {"username": USERNAME, "limit": 20}).get("recentAcSubmissionList") or []
    if not recent and not existing:
        raise RuntimeError("LeetCode returned no recent accepted submissions. Check the username/profile visibility.")

    # Remember newly discovered accepted submissions; never remove historical entries.
    for item in recent:
        slug = item.get("titleSlug")
        if slug:
            existing.setdefault(slug, {
                "title": item.get("title") or slug.replace("-", " ").title(),
                "timestamp": item.get("timestamp", ""),
                "topics": []
            })

    # Fetch topic tags for every known slug, so previously discovered entries are completed too.
    for slug, info in list(existing.items()):
        if info.get("topics"):
            continue
        try:
            question = graphql(QUERY_TAGS, {"titleSlug": slug}).get("question")
            if question:
                info["title"] = question.get("title") or info.get("title") or slug
                info["topics"] = [tag["name"] for tag in (question.get("topicTags") or []) if tag.get("name")]
        except Exception as exc:
            print(f"Warning: could not fetch tags for {slug}: {exc}")

    save_json(SOLVED_FILE, {"username": USERNAME, "problems": existing})

    counts = {}
    for info in existing.values():
        for topic in set(info.get("topics") or []):
            counts[topic] = counts.get(topic, 0) + 1

    save_json(COUNTS_FILE, {
        "username": USERNAME,
        "unique_problems_discovered": len(existing),
        "topics": [{"topic": k, "solved": v} for k, v in sorted(counts.items(), key=lambda kv: (-kv[1], kv[0].lower()))]
    })
    make_svg(counts)
    print(f"Updated tracker: {len(existing)} unique accepted problems discovered; {len(counts)} topics.")
    print("Note: this only discovers accepted submissions returned by LeetCode's recent-submission endpoint.")

if __name__ == "__main__":
    main()
