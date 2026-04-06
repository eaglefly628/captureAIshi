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


def _md_to_post(text: str):
    """Convert markdown text to Feishu 'post' rich-text content array.

    Returns a list of paragraphs, where each paragraph is a list of
    inline elements (text, links, bold text).
    """
    # Strip fenced code blocks → indented plain text
    def _replace_code_block(m):
        code = m.group(2).rstrip("\n")
        indented = "\n".join("  " + line for line in code.split("\n"))
        return f"\n{indented}\n"

    text = re.sub(r'```\w*\n(.*?)```', _replace_code_block, text, flags=re.DOTALL)

    # Strip inline code backticks
    text = re.sub(r'`([^`]+)`', r'\1', text)

    # Convert markdown headings to bold lines
    text = re.sub(r'^#{1,4}\s+(.+)$', r'【\1】', text, flags=re.MULTILINE)

    # Strip bold markers **text** → text (post doesn't render them)
    text = re.sub(r'\*\*(.+?)\*\*', r'\1', text)

    # Strip > blockquote markers
    text = re.sub(r'^>\s?', '', text, flags=re.MULTILINE)

    # Strip horizontal rules
    text = re.sub(r'^---+\s*$', '', text, flags=re.MULTILINE)

    lines = text.split("\n")
    body = []
    for line in lines:
        # Detect markdown links [text](url) and convert to Feishu <a> tags
        parts = []
        last_end = 0
        for m in re.finditer(r'\[([^\]]+)\]\((https?://[^)]+)\)', line):
            # Text before the link
            before = line[last_end:m.start()]
            if before:
                parts.append({"tag": "text", "text": before})
            parts.append({"tag": "a", "text": m.group(1), "href": m.group(2)})
            last_end = m.end()
        # Remaining text after last link
        remaining = line[last_end:]
        if remaining:
            parts.append({"tag": "text", "text": remaining})
        if not parts:
            parts.append({"tag": "text", "text": ""})
        body.append(parts)

    return body


def notify(title: str, content: str) -> bool:
    """Send a rich-text post message to Feishu group.

    Uses 'post' msg_type which renders reliably on both PC and mobile.
    Interactive cards have white-on-white issues on mobile.
    """
    body = _md_to_post(content)
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


def notify_file(title: str, file_path: str, chunk_size: int = 4000) -> bool:
    """Send a file's content to Feishu, split into chunks if needed.

    Long files are split at section boundaries (## headings) and sent
    as multiple sequential messages. The first message includes a GitHub
    link to the original file for full markdown rendering.
    """
    path = Path(file_path)
    if not path.exists():
        return notify(title, f"File not found: {file_path}")

    text = path.read_text(encoding="utf-8")

    # GitHub link for full rendered version
    github_url = (
        f"https://github.com/{_GITHUB_REPO}/blob/{_GITHUB_BRANCH}/{file_path}"
    )
    link_header = f"[GitHub 完整文档(含排版)]({github_url})\n\n"

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
