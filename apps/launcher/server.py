"""爱萌视觉训练中心 — Launcher.

A small Flask app that serves the landing page + spawns child apps.
- GET  /                  -> landing page
- POST /api/launch/<app>  -> spawn captureAIshi or adore_robot subprocess
- GET  /api/status/<app>  -> is app running? port reachable?
"""

from __future__ import annotations

import socket
import subprocess
import sys
import time
import webbrowser
from pathlib import Path

from flask import Flask, jsonify, render_template_string, request

ROOT = Path(__file__).resolve().parents[2]

APPS = {
    "capture": {
        "name": "captureAIshi",
        "cmd": [sys.executable, str(ROOT / "apps/capture/web_ui.py")],
        "cwd": str(ROOT / "apps/capture"),
        "port": 5000,
        "url": "http://localhost:5000",
    },
    "adore_robot": {
        "name": "Adore Robot",
        "cmd": [sys.executable, str(ROOT / "apps/adore_robot/main.py")],
        "cwd": str(ROOT / "apps/adore_robot"),
        "port": 5001,
        "url": "http://localhost:5001",
    },
}

_procs: dict[str, subprocess.Popen] = {}

app = Flask(__name__)


def _port_open(port: int, host: str = "127.0.0.1", timeout: float = 0.3) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def _wait_port(port: int, timeout_s: float = 15.0) -> bool:
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        if _port_open(port):
            return True
        time.sleep(0.3)
    return False


@app.route("/")
def index():
    return render_template_string(_LANDING_HTML)


@app.route("/api/launch/<app_id>", methods=["POST"])
def launch(app_id: str):
    if app_id not in APPS:
        return jsonify({"ok": False, "error": f"unknown app {app_id}"}), 404
    cfg = APPS[app_id]

    if _port_open(cfg["port"]):
        return jsonify({"ok": True, "already_running": True, "url": cfg["url"]})

    proc = _procs.get(app_id)
    if proc is None or proc.poll() is not None:
        proc = subprocess.Popen(cfg["cmd"], cwd=cfg["cwd"])
        _procs[app_id] = proc

    if not _wait_port(cfg["port"]):
        return jsonify({"ok": False, "error": f"port {cfg['port']} not ready"}), 500

    return jsonify({"ok": True, "already_running": False, "url": cfg["url"]})


@app.route("/api/status/<app_id>")
def status(app_id: str):
    if app_id not in APPS:
        return jsonify({"ok": False}), 404
    cfg = APPS[app_id]
    return jsonify({"ok": True, "running": _port_open(cfg["port"]), "url": cfg["url"]})


_LANDING_HTML = r"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>爱萌视觉训练中心 — Aimen Visual Training Hub</title>
<style>
  :root {
    --bg-base: #0e1018;
    --bg-surface: #16181d;
    --bg-elevated: #1c1f26;
    --bg-card: linear-gradient(135deg, #1c1f26 0%, #242832 100%);
    --border: rgba(255,255,255,0.10);
    --border-hover: rgba(110,161,255,0.40);
    --text-primary: #f4f4f5;
    --text-secondary: #b4b8c0;
    --text-tertiary: #7a8088;
    --accent: #6ea1ff;
    --accent-hover: #8db4ff;
    --accent-glow: rgba(110,161,255,0.20);
    --success: #4ade80;
    --warning: #fbbf24;
    --danger: #f87171;
    --radius-md: 10px;
    --radius-lg: 16px;
    --shadow-card: 0 8px 30px rgba(0,0,0,0.40);
    --shadow-card-hover: 0 16px 50px rgba(110,161,255,0.18);
  }
  * { box-sizing: border-box; margin: 0; padding: 0; }
  html, body {
    height: 100%;
    background: var(--bg-base);
    color: var(--text-primary);
    font-family: 'Inter', -apple-system, system-ui, "PingFang SC", "Microsoft YaHei", sans-serif;
    font-size: 15px;
    line-height: 1.5;
    -webkit-font-smoothing: antialiased;
  }
  body {
    background:
      radial-gradient(ellipse at 20% 0%, rgba(110,161,255,0.10), transparent 60%),
      radial-gradient(ellipse at 80% 100%, rgba(251,146,60,0.06), transparent 60%),
      var(--bg-base);
    min-height: 100vh;
    overflow-x: hidden;
  }

  /* Top bar */
  .topbar {
    position: sticky; top: 0; z-index: 10;
    padding: 18px 48px;
    display: flex; align-items: center; justify-content: space-between;
    backdrop-filter: blur(8px);
    background: rgba(14,16,24,0.65);
    border-bottom: 1px solid var(--border);
  }
  .brand { display: flex; align-items: center; gap: 12px; font-weight: 600; font-size: 16px; letter-spacing: 0.02em; }
  .brand-dot { width: 10px; height: 10px; border-radius: 50%; background: var(--accent); box-shadow: 0 0 12px var(--accent-glow); }
  .brand-en { color: var(--text-tertiary); font-weight: 400; font-size: 13px; margin-left: 6px; }
  .topnav { display: flex; gap: 28px; font-size: 13px; color: var(--text-secondary); }
  .topnav a { color: inherit; text-decoration: none; }
  .topnav a:hover { color: var(--text-primary); }

  /* Hero */
  .hero {
    padding: 100px 48px 60px;
    max-width: 1280px; margin: 0 auto;
    text-align: center;
  }
  .hero-tag {
    display: inline-block;
    padding: 6px 14px;
    background: var(--accent-glow);
    color: var(--accent);
    border-radius: 999px;
    font-size: 12px; font-weight: 500; letter-spacing: 0.06em;
    margin-bottom: 24px;
    border: 1px solid rgba(110,161,255,0.30);
  }
  .hero h1 {
    font-size: 56px; font-weight: 700; letter-spacing: -0.02em;
    background: linear-gradient(180deg, #ffffff 0%, #b4b8c0 100%);
    -webkit-background-clip: text; -webkit-text-fill-color: transparent;
    background-clip: text;
    margin-bottom: 18px;
  }
  .hero h1 small { display: block; font-size: 22px; font-weight: 400; color: var(--text-tertiary); margin-top: 12px; letter-spacing: 0.04em; }
  .hero p {
    font-size: 17px; color: var(--text-secondary);
    max-width: 720px; margin: 0 auto 8px;
  }

  /* App cards */
  .apps {
    padding: 40px 48px 80px;
    max-width: 1280px; margin: 0 auto;
    display: grid; grid-template-columns: repeat(auto-fit, minmax(380px, 1fr));
    gap: 28px;
  }
  .app-card {
    background: var(--bg-card);
    border: 1px solid var(--border);
    border-radius: var(--radius-lg);
    padding: 36px 32px;
    position: relative;
    cursor: pointer;
    transition: transform 0.28s cubic-bezier(0.16,1,0.3,1), border-color 0.28s, box-shadow 0.28s;
    overflow: hidden;
    box-shadow: var(--shadow-card);
  }
  .app-card::before {
    content: ""; position: absolute; inset: 0;
    background: radial-gradient(circle at 0% 0%, var(--accent-glow), transparent 60%);
    opacity: 0; transition: opacity 0.3s;
    pointer-events: none;
  }
  .app-card:hover { transform: translateY(-6px); border-color: var(--border-hover); box-shadow: var(--shadow-card-hover); }
  .app-card:hover::before { opacity: 1; }
  .app-card-head { display: flex; align-items: flex-start; justify-content: space-between; margin-bottom: 22px; }
  .app-icon {
    width: 56px; height: 56px;
    border-radius: 14px;
    display: flex; align-items: center; justify-content: center;
    font-size: 26px; font-weight: 700;
    background: var(--bg-elevated);
    border: 1px solid var(--border);
    color: var(--accent);
  }
  .app-icon.adore { color: #fb923c; }
  .app-status {
    font-size: 11px; padding: 4px 10px; border-radius: 999px;
    background: rgba(255,255,255,0.04); color: var(--text-tertiary);
    letter-spacing: 0.05em;
  }
  .app-status.running { background: rgba(74,222,128,0.12); color: var(--success); }
  .app-status.preview { background: rgba(251,191,36,0.12); color: var(--warning); }
  .app-name { font-size: 24px; font-weight: 600; margin-bottom: 4px; letter-spacing: -0.01em; }
  .app-zh { font-size: 14px; color: var(--text-tertiary); margin-bottom: 18px; }
  .app-desc { font-size: 14px; color: var(--text-secondary); margin-bottom: 24px; min-height: 64px; }
  .app-meta { display: flex; gap: 18px; margin-bottom: 24px; font-size: 12px; color: var(--text-tertiary); }
  .app-meta-item { display: flex; align-items: center; gap: 6px; }
  .app-meta-dot { width: 5px; height: 5px; border-radius: 50%; background: var(--text-tertiary); }
  .app-launch {
    width: 100%;
    padding: 12px 20px;
    background: var(--accent);
    color: #0b0d12;
    border: none; border-radius: 8px;
    font-size: 14px; font-weight: 600;
    cursor: pointer;
    transition: background 0.2s;
  }
  .app-launch:hover { background: var(--accent-hover); }
  .app-launch:disabled { background: var(--bg-elevated); color: var(--text-tertiary); cursor: not-allowed; }
  .app-card.coming-soon .app-launch { background: var(--bg-elevated); color: var(--text-tertiary); cursor: default; }
  .app-card.coming-soon:hover { transform: none; border-color: var(--border); box-shadow: var(--shadow-card); }
  .app-card.coming-soon:hover::before { opacity: 0; }

  /* Section: features */
  .features {
    padding: 60px 48px;
    max-width: 1280px; margin: 0 auto;
    border-top: 1px solid var(--border);
  }
  .features h2 { font-size: 24px; font-weight: 600; margin-bottom: 8px; letter-spacing: -0.01em; }
  .features h2 small { display: block; font-size: 13px; color: var(--text-tertiary); font-weight: 400; margin-top: 6px; letter-spacing: 0.04em; }
  .feature-grid { margin-top: 36px; display: grid; grid-template-columns: repeat(auto-fit, minmax(240px, 1fr)); gap: 28px; }
  .feature { padding: 24px; background: var(--bg-surface); border: 1px solid var(--border); border-radius: var(--radius-md); }
  .feature-icon { font-size: 22px; margin-bottom: 14px; }
  .feature h3 { font-size: 15px; font-weight: 600; margin-bottom: 8px; }
  .feature p { font-size: 13px; color: var(--text-secondary); line-height: 1.6; }

  /* Footer */
  footer {
    padding: 40px 48px 60px;
    max-width: 1280px; margin: 0 auto;
    border-top: 1px solid var(--border);
    color: var(--text-tertiary); font-size: 12px;
    display: flex; align-items: center; justify-content: space-between;
    flex-wrap: wrap; gap: 20px;
  }
  .footer-badges { display: flex; gap: 16px; font-size: 11px; letter-spacing: 0.04em; }
  .footer-badge { padding: 6px 12px; background: var(--bg-surface); border: 1px solid var(--border); border-radius: 999px; }

  .toast {
    position: fixed; bottom: 24px; left: 50%; transform: translateX(-50%);
    background: var(--bg-elevated); color: var(--text-primary);
    padding: 12px 22px; border-radius: 8px;
    border: 1px solid var(--border);
    font-size: 13px;
    box-shadow: var(--shadow-card);
    opacity: 0; transition: opacity 0.25s, transform 0.25s;
    pointer-events: none; z-index: 100;
  }
  .toast.show { opacity: 1; transform: translateX(-50%) translateY(-4px); }
</style>
</head>
<body>

<div class="topbar">
  <div class="brand">
    <span class="brand-dot"></span>
    爱萌视觉训练中心
    <span class="brand-en">Aimen Visual Training Hub</span>
  </div>
  <div class="topnav">
    <a href="https://github.com/eaglefly628/captureAIshi" target="_blank">GitHub</a>
  </div>
</div>

<section class="hero">
  <div class="hero-tag">v0.3.0 · POWERED BY UNREAL ENGINE 5.6 + NVIDIA COSMOS</div>
  <h1>
    爱萌视觉训练中心
    <small>为具身智能团队生产 photoreal 训练数据</small>
  </h1>
</section>

<section class="apps" id="apps">

  <div class="app-card" data-app="capture">
    <div class="app-card-head">
      <div class="app-icon">C</div>
      <div class="app-status" id="status-capture">未启动</div>
    </div>
    <div class="app-name">captureAIshi</div>
    <div class="app-zh">游戏场景数据捕获</div>
    <div class="app-desc">注入已发行 3A 游戏，按相机轨迹批量导出 RGB + Depth + Normal + trajectory.json，覆盖 23 款 Tier-1 引擎。</div>
    <div class="app-meta">
      <div class="app-meta-item"><span class="app-meta-dot"></span>RenderDoc + ReShade 双路径</div>
      <div class="app-meta-item"><span class="app-meta-dot"></span>UE3/4/5 / Unity / REDengine</div>
    </div>
    <button class="app-launch" onclick="launchApp('capture', this)">启动 captureAIshi</button>
  </div>

  <div class="app-card" data-app="adore_robot">
    <div class="app-card-head">
      <div class="app-icon adore">A</div>
      <div class="app-status preview" id="status-adore_robot">预览版</div>
    </div>
    <div class="app-name">Adore Robot</div>
    <div class="app-zh">机器人训练场景生产</div>
    <div class="app-desc">UE5 PCG 程序化生成 warehouse / 客厅 / 工业一角三类机器人训练场景，对接 Cosmos Transfer photoreal 渲染。</div>
    <div class="app-meta">
      <div class="app-meta-item"><span class="app-meta-dot"></span>UE5.6 + PCG + Robotics Plugin</div>
      <div class="app-meta-item"><span class="app-meta-dot"></span>FRANKA / Unitree H1 / UR5</div>
    </div>
    <button class="app-launch" onclick="launchApp('adore_robot', this)">启动 Adore Robot</button>
  </div>

  <div class="app-card coming-soon">
    <div class="app-card-head">
      <div class="app-icon" style="color: var(--text-tertiary);">+</div>
      <div class="app-status">计划中</div>
    </div>
    <div class="app-name">Data Adapter Studio</div>
    <div class="app-zh">下游数据格式适配器</div>
    <div class="app-desc">把任意 trajectory + RGB/Depth 三元组转 LeRobot dataset / RT-X TFDS / GR00T schema / robomimic HDF5。</div>
    <div class="app-meta">
      <div class="app-meta-item"><span class="app-meta-dot"></span>Q3 2026 · 待启动</div>
    </div>
    <button class="app-launch" disabled>Coming Soon</button>
  </div>

</section>

<footer>
  <div>© 2026 Aimen · captureAIshi v0.3.0</div>
  <div class="footer-badges">
    <span class="footer-badge">UNREAL ENGINE 5.6</span>
    <span class="footer-badge">NVIDIA COSMOS</span>
    <span class="footer-badge">RENDERDOC</span>
    <span class="footer-badge">RESHADE</span>
  </div>
</footer>

<div class="toast" id="toast"></div>

<script>
const APPS = ['capture', 'adore_robot'];

function toast(msg) {
  const t = document.getElementById('toast');
  t.textContent = msg;
  t.classList.add('show');
  setTimeout(() => t.classList.remove('show'), 2400);
}

async function refreshStatus() {
  for (const id of APPS) {
    try {
      const r = await fetch(`/api/status/${id}`);
      const j = await r.json();
      const el = document.getElementById('status-' + id);
      if (j.running) { el.textContent = '运行中'; el.className = 'app-status running'; }
      else { el.textContent = id === 'adore_robot' ? '预览版' : '未启动'; el.className = id === 'adore_robot' ? 'app-status preview' : 'app-status'; }
    } catch (e) {}
  }
}

async function launchApp(id, btn) {
  btn.disabled = true;
  const original = btn.textContent;
  btn.textContent = '启动中…';
  try {
    const r = await fetch(`/api/launch/${id}`, { method: 'POST' });
    const j = await r.json();
    if (!j.ok) { toast('启动失败: ' + (j.error || '未知错误')); btn.textContent = original; btn.disabled = false; return; }
    toast(j.already_running ? '已在运行, 打开浏览器…' : '启动成功, 打开浏览器…');
    window.open(j.url, '_blank');
    btn.textContent = '已启动 ✓';
    setTimeout(() => { btn.textContent = original; btn.disabled = false; }, 2000);
    refreshStatus();
  } catch (e) {
    toast('网络错误: ' + e.message);
    btn.textContent = original; btn.disabled = false;
  }
}

refreshStatus();
setInterval(refreshStatus, 4000);
</script>

</body>
</html>
"""


def main():
    port = 5050
    print(f"[launcher] serving on http://localhost:{port}")
    webbrowser.open(f"http://localhost:{port}")
    app.run(host="127.0.0.1", port=port, debug=False)


if __name__ == "__main__":
    main()
