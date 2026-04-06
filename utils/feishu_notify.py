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
    """Send a markdown card message to Feishu group.

    Uses interactive card with explicit font_color to fix mobile dark mode
    white-on-white rendering issue.
    """
    payload = {
        "msg_type": "interactive",
        "card": {
            "config": {"wide_screen_mode": True},
            "header": {
                "title": {"tag": "plain_text", "content": f"[captureAIshi] {title}"},
                "template": "blue",
            },
            "elements": [
                {
                    "tag": "markdown",
                    "content": content,
                    "text_align": "left",
                },
            ],
        },
    }
    return _post(payload)


def notify_file(title: str, file_path: str, chunk_size: int = 4000) -> bool:
    """Send a file's content to Feishu, split into chunks if needed.

    Feishu card markdown has a practical limit around 4-5KB per element.
    Long files are split at section boundaries (## headings) and sent
    as multiple sequential messages.
    """
    path = Path(file_path)
    if not path.exists():
        return notify(title, f"File not found: {file_path}")

    text = path.read_text(encoding="utf-8")

    if len(text) <= chunk_size:
        return notify(title, text)

    # Split by ## headings to get logical sections
    import re
    sections = re.split(r'(?=^## )', text, flags=re.MULTILINE)

    chunks = []
    current = ""
    for section in sections:
        if len(current) + len(section) > chunk_size and current:
            chunks.append(current)
            current = section
        else:
            current += section
    if current:
        chunks.append(current)

    ok = True
    for i, chunk in enumerate(chunks):
        part_title = f"{title} ({i + 1}/{len(chunks)})" if len(chunks) > 1 else title
        if not notify(part_title, chunk):
            ok = False
    return ok


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

    if len(sys.argv) >= 3 and sys.argv[1] == "--file":
        # python -m utils.feishu_notify --file <title> <filepath>
        notify_file(sys.argv[2], sys.argv[3])
    elif len(sys.argv) >= 3:
        notify(sys.argv[1], sys.argv[2])
    else:
        print("Usage:")
        print("  python -m utils.feishu_notify <title> <content>")
        print("  python -m utils.feishu_notify --file <title> <filepath>")
