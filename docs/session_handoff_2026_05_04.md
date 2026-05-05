# Session Handoff -- 2026-05-04

> **新 session 入口**: 读完本文件即可恢复完整上下文。无需再翻其他文档。
> **基线 commit**: `906f06f` (本文件首版) -- 后续可能已有真帧/UI 微调,见 `git log`。

## 1. 项目状态一句话

阿里云 ECS 上跑 captureaishi demo (Batman: Arkham Knight, 7 帧真抓数据 +
orbit 路径) 和一个 WordPress 营销站,共存于 2c2g 单机。Demo 单机能跑,
**WP 起来后手机访问 demo 会失败** (PC 不受影响) -- 根因未定位。

## 2. 部署资源

- **ECS**: 阿里云 华东2 上海 / 99元包月 / 2vCPU 2GB RAM / 40GB ESSD Entry / 3Mbps 固定带宽 / Ubuntu 22.04 LTS / Docker 预装
- **公网 IP**: `139.224.204.231`
- **私网 IP**: `172.27.174.187`
- **SSH**: `ssh root@139.224.204.231` (密码用户已存密码管理器)
- **安全组入向**: 22 / 8081 / 9000 已开 0.0.0.0;8080 历史规则可清理

## 3. 跑着的容器

| Container | 主机端口 | 容器端口 | Stack |
|-----------|---------|---------|-------|
| `aishi-demo` | 9000 | 8080 | `docker run` 单独 |
| `wp-stack-nginx-1` | 8081 | 80 | `wp-stack/docker-compose.yml` |
| `wp-stack-wordpress-1` | -- (内部) | 9000 (PHP-FPM) | wp-stack |
| `wp-stack-db-1` | -- (内部) | 3306 (MySQL 8 tuned, ~138MB) | wp-stack |

## 4. 验收状态

| 功能 | PC | 手机 (WP 跑) | 手机 (WP 停) |
|------|----|----|----|
| `http://IP:9000` demo 加载 | OK | 失败 | OK |
| `http://IP:8081` WP 加载 | OK | OK | -- |
| Demo Start -> 7 帧节奏 + 3D 渐进路径 | OK | -- | OK |
| 注入菜单按钮 canned 响应 | OK | -- | OK |
| Output gallery 三联布局 (RGB/Depth/Normal) | 待验 | -- | 待验 |

**手机失败现象**: WP 容器在跑时,手机 (Chrome/Safari) 都打不开 9000;
WP 停掉手机就能打开。Safari 第二次访问也失败 -> 排除浏览器缓存。
PC 任意时候都正常。怀疑 docker 双 bridge 网络在手机 cellular 链路上的
路由/MTU 冲突。详细抓包未做 (见 6.4)。

## 5. 已完成的关键里程碑 (2026-05)

- `d1015d9` Demo Mode 短路 (DEMOAISHI=1, web/demo.py + canned 路由)
- `c6a3199` Batman scenario bundle (manifest + script + trajectory)
- `74eed58` Dockerfile + deploy_demo.md
- `9381c91` VSCode launch config "Web UI (Demo Mode)"
- `b3ae149` 7-pose Batman + 3D progressive draw
- `a0f2869` wp-stack: MySQL 8 tuned + WP fpm-alpine + nginx (route A)
- `a78a0d3` demo png update -- **真帧已上传到 `frames/`** (7 组 RGB+Depth+Normal,
  命名 `frame_frameXXXX.png` / `_d.png` / `_n.png`)
- `906f06f` 本文件首版

## 6. 下一 session 工作清单

按优先级。

### 6.1 P0 -- 验证 Output gallery 显示

真帧已在仓库 (commit `a78a0d3`),但 ECS 端不一定 pull 了最新镜像。先:

```bash
ssh root@139.224.204.231
cd ~/captureaishi && git pull
docker build -t captureaishi-demo .
docker stop aishi-demo && docker rm aishi-demo
docker run -d --restart=unless-stopped --name aishi-demo \
  -p 9000:8080 captureaishi-demo
```

然后浏览器开 `http://139.224.204.231:9000`,点 Start,等 7 帧跑完,看
Output gallery 是否每行都有 RGB + Depth + Normal 三张缩略图。

> **命名说明**: 当前 `frames/` 里是 `frame_frame4556.png` / `frame_frame4556_d.png`
> / `frame_frame4556_n.png` 这种格式 (来自实际抓帧文件名)。manifest 没强制
> 命名规则,demo.py 把整个 `frames/` 目录指给 `/api/captures`。如果未来要换
> 命名 (例 `0001_main.png` / `0001_main_d.png` / `0001_main_n.png`),
> 直接替换文件即可,无需改代码。

### 6.2 P0 -- 设计爱萌营销 HTML 单页

**路 1 自包含格式** -- 我吐出一段从 `<!DOCTYPE html>` 起的完整 HTML
(内联 CSS, 不依赖外链), 用户复制粘到 WP 后台:

> 后台 -> 页面 -> 首页 -> 右上 ⋮ -> 代码编辑器 -> 整段粘贴 -> 更新
> (或新增 "自定义 HTML" 块)

**页面结构**:
- Hero: "爱萌 / AiMeng" + 一句话定位 + Demo CTA 按钮
- About: 1 段公司简介
- Services: 3-5 张业务卡片
- Demo CTA 大按钮 -> `http://139.224.204.231:9000` (target=_blank)
- Contact: 邮箱 / 微信 / 二维码占位

**用户业务素材待问** (新 session 开场要问这三条):
1. 公司一句话定位 (例: "为大模型提供高质量游戏场景训练数据")
2. 主要业务列 3-5 条
3. 目标客户 (B2B SaaS / AI 实验室 / 高校研究组 / 游戏厂 ...)

如果用户暂时不想确定,先按通用 "AI 训练数据捕捉服务商" 写,后续再调。

### 6.3 P1 -- 修手机访问 9000 失败的根因

候选诊断 (代价低 -> 高):

1. **看 docker 网络拓扑**:
   ```bash
   docker network ls
   docker network inspect wp-stack_default
   docker network inspect bridge
   ```
2. **看 iptables NAT 表**:
   ```bash
   sudo iptables -t nat -L -n | grep -E "9000|8080|8081"
   ```
3. **MTU 检查**: 手机 cellular MTU 通常 1280-1400,docker bridge 默认 1500。
   双 bridge 时 MTU 协商有时挂。`/etc/docker/daemon.json` 加 `{"mtu":1400}`,
   重启 docker 看是否解决。
4. **conntrack 表溢出**:
   ```bash
   cat /proc/sys/net/netfilter/nf_conntrack_count
   cat /proc/sys/net/netfilter/nf_conntrack_max
   ```
5. **改架构** (重活,最后选项): aishi-demo 加入 wp-stack 网络,统一 docker
   compose;或 WP nginx 加 `/demo/` location 反代到 demo 容器。后者要求改
   Flask 静态资源 base_url,工作量大。

### 6.4 P2 -- 备份 + 域名 (后续)

- WP 数据备份: `~/captureaishi/wp-stack/wp-data/` + `docker exec wp-stack-db-1 mysqldump ...`
- 备案: 国内 ECS 走 80/443 + 域名要 ICP

## 7. 关键文件 / 路径

```
captureaishi/
+-- Dockerfile                       demo 镜像 (python:3.11-slim + requirements-demo.txt)
+-- requirements-demo.txt            3 条依赖 (Flask + 必需)
+-- .dockerignore
+-- web_ui.py                        Flask 入口
+-- web/
|   +-- demo.py                      DemoSession + canned 响应 (DEMOAISHI=1 启用)
|   +-- routes/
|   |   +-- capture.py               /api/start /api/status (含 demo_pose)
|   |   +-- bridge.py hacks.py obs.py tools.py trajectory.py  (canned 短路)
|   |   +-- ...
|   +-- templates/
|       +-- index.html               UI (含 3D viewer + demo ribbon)
+-- demo/
|   +-- scenarios/
|       +-- batman_ak/
|           +-- manifest.json        total_poses=7, dwell=2.0
|           +-- script.json          11 行 preamble + 13 行 postamble
|           +-- frames/
|           |   +-- trajectory.json  7 orbit waypoints
|           |   +-- frame_frame4556.png      RGB
|           |   +-- frame_frame4556_d.png    Depth
|           |   +-- frame_frame4556_n.png    Normal
|           |   +-- ... (共 7 组真帧)
|           +-- README.md
+-- wp-stack/
|   +-- docker-compose.yml           MySQL 8 tuned + WP fpm-alpine + nginx
|   +-- nginx.conf
|   +-- .env                         DB 密码 (gitignore)
|   +-- .env.example
+-- docs/
    +-- deploy_demo.md
    +-- deploy_wp.md
    +-- session_handoff_2026_05_04.md   <-- 本文件
```

**Windows 本地路径** (用户机器):
```
D:\project\captureAIshi\demo\scenarios\batman_ak\frames\
```

## 8. Git 工作流

- **GitHub origin**: `https://github.com/eaglefly628/captureaishi.git` (private)
- **Gitee 镜像**: `https://gitee.com/eaglefly628/captureaishi.git` (private, 国内 ECS pull 用)
- **分支**: 始终在 `claudeMainBranch` (CLAUDE.md 强制规定,不准开 feature 分支或推 `claude/xxx` 自动分支)

**更新流程** (Windows 改完代码):
```cmd
git push origin claudeMainBranch
git push gitee claudeMainBranch
```

**ECS 重建** (一行,失败可分步):
```bash
cd ~/captureaishi && git pull && docker build -t captureaishi-demo . && \
  docker stop aishi-demo && docker rm aishi-demo && \
  docker run -d --restart=unless-stopped --name aishi-demo \
  -p 9000:8080 captureaishi-demo
```

## 9. 最近 commit 链 (近 -> 远)

```
906f06f  docs: session handoff 2026-05-04 (本文件,可能已被本次更新覆盖)
a78a0d3  demo png update (真帧 7x3 入库)
a0f2869  wp-stack: MySQL 8 tuned + WP + Nginx + 部署 doc
b3ae149  Demo Mode: 7-pose Batman + 3D progressive draw
9381c91  vscode: Demo Mode launch config
74eed58  Dockerfile + deploy_demo.md
c6a3199  Batman scenario step 2 (manifest + script + trajectory)
d1015d9  Demo Mode step 1 scaffolding
```

## 10. 给新 session 的开场提示 (用户复制粘贴用)

> 接前一 session,继续做爱萌项目。状态见 `docs/session_handoff_2026_05_04.md`,
> 先读这个文件。我刚把 7 张真帧上传到 `demo/scenarios/batman_ak/frames/`,
> 验证下 Output gallery 显示是否正确;如果 OK,继续设计爱萌营销 HTML 单页
> (路 1: 自包含 HTML 我粘到 WP)。

新 session 应自动:
1. 读本文件全文
2. 跑第 6.1 节的验收命令 (或让用户在 ECS 上跑)
3. 问用户第 6.2 节的三条业务素材
4. 直接给出 HTML 单页代码块
