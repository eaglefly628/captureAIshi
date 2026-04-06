"""
Feishu (Lark) webhook notification utility.

Usage:
    from utils.feishu_notify import notify, notify_file

    # Send a text message
    notify("Task completed", "xiaoxuan finished GBuffer classifier")

    # Send a file's content as a message
    notify_file("New Roadmap", "docs/captureAIshi_analysis_and_roadmap.md")
"""

import json
import urllib.request
import urllib.error
from pathlib import Path

WEBHOOK_URL = "https://open.feishu.cn/open-apis/bot/v2/hook/bad13239-7ace-4829-8cd8-c3e08fd0bea1"


def notify(title: str, content: str) -> bool:
    """Send a rich-text message to Feishu group.

    Uses 'post' msg_type instead of 'interactive' card because Feishu
    interactive cards render white-on-white on mobile (dark mode mismatch).
    The 'post' type has reliable text color on both PC and mobile.
    """
    # Split content into lines, each becomes a text element in the post
    lines = content.split("\n")
    body = [[{"tag": "text", "text": line}] for line in lines]

    payload = {
        "msg_type": "post",
        "content": {
            "post": {
                "zh_cn": {
                    "title": f"[captureAIshi] {title}",
                    "content": body,
                }
            }
        },
    }
    return _post(payload)


def notify_file(title: str, file_path: str, max_chars: int = 3000) -> bool:
    """Send a file's content to Feishu. Truncates if too long."""
    path = Path(file_path)
    if not path.exists():
        return notify(title, f"File not found: {file_path}")

    text = path.read_text(encoding="utf-8")
    if len(text) > max_chars:
        text = text[:max_chars] + f"\n\n... (truncated, {len(text)} chars total)"

    return notify(title, text)


def _post(payload: dict) -> bool:
    """Post JSON to Feishu webhook."""
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        WEBHOOK_URL,
        data=data,
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            result = json.loads(resp.read())
            if result.get("code") == 0:
                return True
            print(f"[feishu] Error: {result}")
            return False
    except urllib.error.URLError as e:
        print(f"[feishu] Request failed: {e}")
        return False


if __name__ == "__main__":
    import sys

    if len(sys.argv) >= 3:
        notify(sys.argv[1], sys.argv[2])
    else:
        print("Usage: python -m utils.feishu_notify <title> <content>")
