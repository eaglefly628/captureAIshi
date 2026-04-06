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
import re
import urllib.request
import urllib.error
from pathlib import Path

WEBHOOK_URL = "https://open.feishu.cn/open-apis/bot/v2/hook/bad13239-7ace-4829-8cd8-c3e08fd0bea1"

# GitHub repo for file links
_GITHUB_REPO = "eaglefly628/captureAIshi"
_GITHUB_BRANCH = "claudeMainBranch"


def _md_to_feishu(text: str) -> str:
    """Pre-process markdown for Feishu card compatibility.

    Feishu card markdown does NOT support fenced code blocks (``` ```) --
    they render as white text on white background on mobile.
    Convert to indented plain text with a header line instead.
    """
    def _replace_code_block(m):
        lang = m.group(1) or ""
        code = m.group(2).rstrip("\n")
        # Indent each line with 4 spaces so it looks like a code block
        indented = "\n".join("    " + line for line in code.split("\n"))
        header = f"[{lang}]" if lang else "[code]"
        return f"\n**{header}**\n{indented}\n"

    # Replace fenced code blocks: ```lang\n...\n```
    text = re.sub(
        r'```(\w*)\n(.*?)```',
        _replace_code_block,
        text,
        flags=re.DOTALL,
    )
    return text


def notify(title: str, content: str) -> bool:
    """Send a markdown card message to Feishu group."""
    content = _md_to_feishu(content)
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
    as multiple sequential messages. The first message includes a GitHub
    link to the original file for full rendering.
    """
    path = Path(file_path)
    if not path.exists():
        return notify(title, f"File not found: {file_path}")

    text = path.read_text(encoding="utf-8")

    # Add GitHub link at the top for full markdown rendering
    github_url = (
        f"https://github.com/{_GITHUB_REPO}/blob/{_GITHUB_BRANCH}/{file_path}"
    )
    link_header = f"[GitHub 完整文档]({github_url})\n\n---\n\n"

    if len(text) + len(link_header) <= chunk_size:
        return notify(title, link_header + text)

    # Split by ## headings to get logical sections
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

    # Prepend GitHub link to first chunk
    chunks[0] = link_header + chunks[0]

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
