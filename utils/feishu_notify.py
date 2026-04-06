"""
Feishu (Lark) webhook + Open API notification utility.

Usage:
    from utils.feishu_notify import notify, notify_file, send_file

    # Send a text message (via webhook)
    notify("Task completed", "xiaoxuan finished GBuffer classifier")

    # Send a file's content as text (via webhook, split into chunks)
    notify_file("New Roadmap", "docs/captureAIshi_analysis_and_roadmap.md")

    # Upload and send an actual file to the group (via Open API)
    send_file("docs/captureAIshi_analysis_and_roadmap.md")
"""

import json
import re
import urllib.request
import urllib.error
from pathlib import Path

WEBHOOK_URL = "https://open.feishu.cn/open-apis/bot/v2/hook/bad13239-7ace-4829-8cd8-c3e08fd0bea1"

# Feishu Open API credentials (for file upload)
_APP_ID = "cli_a9597bf3c4b81cc8"
_APP_SECRET = "dM58cOeDgdDMh8QuDuA8Lcyu7OikqIo7"

# GitHub repo for file links
_GITHUB_REPO = "eaglefly628/captureAIshi"
_GITHUB_BRANCH = "claudeMainBranch"

# ── Token cache ──────────────────────────────────────────────────
_token_cache = {"token": None, "expires_at": 0}


def _get_tenant_token() -> str:
    """Get or refresh the tenant_access_token."""
    import time
    now = time.time()
    if _token_cache["token"] and now < _token_cache["expires_at"] - 60:
        return _token_cache["token"]

    payload = json.dumps({
        "app_id": _APP_ID,
        "app_secret": _APP_SECRET,
    }).encode("utf-8")
    req = urllib.request.Request(
        "https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal",
        data=payload,
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=10) as resp:
        result = json.loads(resp.read())
    if result.get("code") != 0:
        raise RuntimeError(f"Failed to get token: {result}")

    _token_cache["token"] = result["tenant_access_token"]
    _token_cache["expires_at"] = now + result.get("expire", 7200)
    return _token_cache["token"]


def _get_bot_chat_id() -> str:
    """Find the first group chat the bot is in."""
    token = _get_tenant_token()
    req = urllib.request.Request(
        "https://open.feishu.cn/open-apis/im/v1/chats?page_size=20",
        headers={"Authorization": f"Bearer {token}"},
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            result = json.loads(resp.read())
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"List chats HTTP {e.code}: {body}")
    if result.get("code") != 0:
        raise RuntimeError(f"Failed to list chats: {result}")

    items = result.get("data", {}).get("items", [])
    # Prefer group chats
    for chat in items:
        if chat.get("chat_mode") == "group":
            return chat["chat_id"]
    if items:
        return items[0]["chat_id"]
    raise RuntimeError("Bot is not in any chat group. Add the bot to a group first.")


def _upload_file(file_path: Path, file_type: str = "stream") -> str:
    """Upload a file to Feishu and return the file_key."""
    import uuid

    token = _get_tenant_token()
    boundary = uuid.uuid4().hex

    file_name = file_path.name
    file_data = file_path.read_bytes()

    # Build multipart/form-data body
    parts = []
    # file_type field
    parts.append(
        f"--{boundary}\r\n"
        f'Content-Disposition: form-data; name="file_type"\r\n\r\n'
        f"{file_type}\r\n"
    )
    # file_name field
    parts.append(
        f"--{boundary}\r\n"
        f'Content-Disposition: form-data; name="file_name"\r\n\r\n'
        f"{file_name}\r\n"
    )
    # file binary field
    file_header = (
        f"--{boundary}\r\n"
        f'Content-Disposition: form-data; name="file"; filename="{file_name}"\r\n'
        f"Content-Type: application/octet-stream\r\n\r\n"
    )
    file_footer = f"\r\n--{boundary}--\r\n"

    body = b""
    for part in parts:
        body += part.encode("utf-8")
    body += file_header.encode("utf-8")
    body += file_data
    body += file_footer.encode("utf-8")

    req = urllib.request.Request(
        "https://open.feishu.cn/open-apis/im/v1/files",
        data=body,
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": f"multipart/form-data; boundary={boundary}",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            result = json.loads(resp.read())
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"Upload HTTP {e.code}: {body}")
    if result.get("code") != 0:
        raise RuntimeError(f"Failed to upload file: {result}")
    return result["data"]["file_key"]


def _send_message(chat_id: str, msg_type: str, content: dict) -> bool:
    """Send a message to a chat via Open API."""
    token = _get_tenant_token()
    payload = json.dumps({
        "receive_id": chat_id,
        "msg_type": msg_type,
        "content": json.dumps(content),
    }).encode("utf-8")
    req = urllib.request.Request(
        "https://open.feishu.cn/open-apis/im/v1/messages?receive_id_type=chat_id",
        data=payload,
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        },
    )
    with urllib.request.urlopen(req, timeout=10) as resp:
        result = json.loads(resp.read())
    if result.get("code") != 0:
        print(f"[feishu] Send failed: {result}")
        return False
    return True


def send_file(file_path: str, title: str = "") -> bool:
    """Upload a file and send it to the Feishu group.

    This uses the Open API (app credentials) to upload the actual file,
    so it appears as a downloadable attachment in the chat.
    Optionally sends a text message with the title before the file.
    """
    path = Path(file_path)
    if not path.exists():
        print(f"[feishu] File not found: {file_path}")
        return False

    try:
        print("[feishu] Step 1: Getting token...")
        token = _get_tenant_token()
        print(f"[feishu] Token OK: {token[:10]}...")

        print("[feishu] Step 2: Finding chat...")
        chat_id = _get_bot_chat_id()
        print(f"[feishu] Chat ID: {chat_id}")

        print("[feishu] Step 3: Uploading file...")
        file_key = _upload_file(path)
        print(f"[feishu] File key: {file_key}")

        # Send title message first if provided
        if title:
            _send_message(chat_id, "text", {"text": f"[captureAIshi] {title}"})

        print("[feishu] Step 4: Sending file message...")
        return _send_message(chat_id, "file", {"file_key": file_key})
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="replace")
        print(f"[feishu] HTTP {e.code}: {body}")
        return False
    except Exception as e:
        print(f"[feishu] File send failed: {e}")
        return False


# ── Webhook-based messaging (no app credentials needed) ─────────

def _md_to_post(text: str):
    """Convert markdown text to Feishu 'post' rich-text content array."""
    # Strip fenced code blocks -> indented plain text
    def _replace_code_block(m):
        code = m.group(1).rstrip("\n")
        indented = "\n".join("  " + line for line in code.split("\n"))
        return f"\n{indented}\n"

    text = re.sub(r'```\w*\n(.*?)```', _replace_code_block, text, flags=re.DOTALL)

    # Strip inline code backticks
    text = re.sub(r'`([^`]+)`', r'\1', text)

    # Convert markdown headings to bracketed text
    text = re.sub(r'^#{1,4}\s+(.+)$', r'\1', text, flags=re.MULTILINE)

    # Strip bold markers
    text = re.sub(r'\*\*(.+?)\*\*', r'\1', text)

    # Strip blockquote markers
    text = re.sub(r'^>\s?', '', text, flags=re.MULTILINE)

    # Strip horizontal rules
    text = re.sub(r'^---+\s*$', '', text, flags=re.MULTILINE)

    lines = text.split("\n")
    body = []
    for line in lines:
        parts = []
        last_end = 0
        for m in re.finditer(r'\[([^\]]+)\]\((https?://[^)]+)\)', line):
            before = line[last_end:m.start()]
            if before:
                parts.append({"tag": "text", "text": before})
            parts.append({"tag": "a", "text": m.group(1), "href": m.group(2)})
            last_end = m.end()
        remaining = line[last_end:]
        if remaining:
            parts.append({"tag": "text", "text": remaining})
        if not parts:
            parts.append({"tag": "text", "text": ""})
        body.append(parts)

    return body


def notify(title: str, content: str) -> bool:
    """Send a rich-text post message to Feishu group via webhook."""
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
    return _post_webhook(payload)


def notify_file(title: str, file_path: str, chunk_size: int = 4000) -> bool:
    """Send a file's content as text to Feishu, split into chunks if needed."""
    path = Path(file_path)
    if not path.exists():
        return notify(title, f"File not found: {file_path}")

    text = path.read_text(encoding="utf-8")

    github_url = (
        f"https://github.com/{_GITHUB_REPO}/blob/{_GITHUB_BRANCH}/{file_path}"
    )
    link_header = f"[GitHub 完整文档(含排版)]({github_url})\n\n"

    if len(text) + len(link_header) <= chunk_size:
        return notify(title, link_header + text)

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

    chunks[0] = link_header + chunks[0]

    ok = True
    for i, chunk in enumerate(chunks):
        part_title = f"{title} ({i + 1}/{len(chunks)})" if len(chunks) > 1 else title
        if not notify(part_title, chunk):
            ok = False
    return ok


def _post_webhook(payload: dict) -> bool:
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
    elif len(sys.argv) >= 3 and sys.argv[1] == "--send":
        # python -m utils.feishu_notify --send <filepath> [title]
        title = sys.argv[3] if len(sys.argv) >= 4 else ""
        send_file(sys.argv[2], title)
    elif len(sys.argv) >= 3:
        notify(sys.argv[1], sys.argv[2])
    else:
        print("Usage:")
        print("  python -m utils.feishu_notify <title> <content>")
        print("  python -m utils.feishu_notify --file <title> <filepath>     (as text)")
        print("  python -m utils.feishu_notify --send <filepath> [title]     (as file)")
