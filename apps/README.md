# 爱萌视觉训练中心 — Apps Suite

Monorepo 子目录结构。三个 web app 独立端口，互不阻塞。

| App | 端口 | 入口 | 状态 |
|---|---|---|---|
| **launcher** | 5050 | `python apps/launcher/server.py` | 已实装 |
| **captureAIshi** | 5000 | `python web_ui.py` (仓根) | 已有 |
| **adore_robot** | 5001 | `python apps/adore_robot/main.py` | preview stub |

## 启动顺序

只起 launcher 就行——它会按需 spawn 另外两个：

```bash
python apps/launcher/server.py
# 浏览器自动开 http://localhost:5050
# 点 "启动 captureAIshi" -> 后台启 web_ui.py + 开新 tab
# 点 "启动 Adore Robot" -> 后台启 apps/adore_robot/main.py + 开新 tab
```

## 共享

- 配色 / 字体 / 圆角 / shadow tokens：三个 app 都用同一组 CSS variables（`--bg-base #0e1018` / `--accent #6ea1ff` for capture / `--accent #fb923c` for adore_robot）
- 顶部 brand bar 风格一致：左 logo + 中央或右导航
- Inter 字体（Latin）+ PingFang SC / Microsoft YaHei（中文 fallback）

## 仓库布局原则

- `apps/<name>/` 各 app 自己的 Python entry + templates + static
- `core/` `drivers/` `grabbers/` 等现有顶层目录暂时仍归 captureAIshi 使用，后期视情况挪到 `apps/capture/`
- `.claude/` `docs/` `agents/` 全 app 共享
