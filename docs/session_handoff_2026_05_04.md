# Session Handoff -- 2026-05-04

## 项目状态

阿里云 ECS 部署 captureaishi demo (Batman 7 帧虚拟场景) + 一个未完成的
WordPress 营销站,共存于一台 2c2g 机器。Demo 单机能跑,WP 起来后**手机
访问 demo 失败**(PC 不受影响)未修。

## 部署资源

- **ECS**: 阿里云 华东2 上海 / 99元包月 / 2vCPU 2GB RAM / 40GB ESSD Entry / 3Mbps 固定带宽 / Ubuntu 22.04 LTS / Docker 预装
- **公网 IP**: `139.224.204.231`
- **私网 IP**: `172.27.174.187`
- **SSH**: `ssh root@139.224.204.231` (密码用户已存密码管理器)

## 跑着的容器

| Container | 主机端口 | 容器端口 | Stack |
|-----------|---------|---------|-------|
| `aishi-demo` | 9000 | 8080 | `docker run` 单独 |
| `wp-stack-nginx-1` | 8081 | 80 | `wp-stack/docker-compose.yml` |
| `wp-stack-wordpress-1` | -- (内部) | 9000 (PHP-FPM) | wp-stack |
| `wp-stack-db-1` | -- (内部) | 3306 (MySQL 8 tuned) | wp-stack |

阿里云安全组入向已开: 22 / 8081 / 9000 / 0.0.0.0。8080 历史规则可清理。

## 验收状态

| 功能 | PC | 手机 (WP 跑) | 手机 (WP 停) |
|------|----|----|----|
| `http://IP:9000` demo | ✅ | ❌ | ✅ |
| `http://IP:8081` WP | ✅ | ✅ | -- |
| Demo Start 按钮 → 7 帧节奏 + 3D 渐进路径 | ✅ | -- | ✅ |
| 注入菜单按钮 canned ok | ✅ | -- | ✅ |

**手机访问 demo 失败的现象**:WP 起来时手机 (Chrome/Safari) 都不能开 9000;
WP 停掉手机就能开 9000。Safari 第二次访问也失败,说明不是浏览器缓存。
PC 任意时候都能开。怀疑 docker 双 bridge 网络在手机端的特定场景下路由
冲突。详细症状未捕捉(见下"待办")。

## 用户决定

- **演示场景**: Batman: Arkham Knight (已实现, 7 帧虚拟 + orbit 路径)
- **真帧上传**: 用户**计划在新 session 之前**把 7 张真帧 PNG 三联组扔进
  `demo/scenarios/batman_ak/frames/`(替换 `.gitkeep`)
- **营销站方案**: **路 1** -- 我设计 HTML,用户粘贴到 WP 页面编辑器
  - 单页营销页结构: Hero + About + 业务 (3-5 项) + Demo CTA + Contact
  - 自包含 (内联 CSS, 不依赖外链)
  - Demo CTA 按钮链接 `http://139.224.204.231:9000` (新标签打开)
- **路线 A vs B 选择**: 选 A (真 WP 同 ECS), MySQL 8 tuned 跑得很省 (~138MB)

## 下一 session 工作清单

按优先级:

### P0: 跟用户确认真帧已上传

```bash
ls demo/scenarios/batman_ak/frames/
```
应能看到 ~21 个 PNG (7 组 × RGB+Depth+Normal),或类似数量。

跑 demo 验证 Output gallery 三联布局 + 3D 进度同步。手机 + PC 都试。

### P0: 设计爱萌营销 HTML 单页

**自包含格式** (一段 `<!DOCTYPE html>` 起的完整 HTML, 内联 CSS):
- Hero: "爱萌 / AiMeng" + 一句话定位 + Demo CTA 按钮
- About: 1 段公司简介
- Services: 3-5 个业务卡片 (例: 游戏数据捕捉 / RGB+Depth+Normal 三联 / AI 训练数据集 / VLM 场景理解)
- Demo CTA 大按钮: `http://139.224.204.231:9000`
- Contact: 邮箱 / 微信 / 二维码占位

用户业务素材待问 (公司一句话定位 / 业务列表 / 目标客户)。如果用户没给,
按通用 "AI 训练数据捕捉服务商" 写,后续再调。

### P0: 用户粘到 WP

后台 → 页面 → 首页 → 右上 ⋮ → 代码编辑器 → 整段粘贴 → 更新。
或在块编辑器加一个 "自定义 HTML" 块包整段。

### P1: 修手机访问 9000 失败的根因

候选诊断 (按代价低到高):

1. **看 docker 网络**:
   ```bash
   docker network ls
   docker network inspect wp-stack_default
   docker network inspect bridge
   ```
2. **看 iptables NAT 表**:
   ```bash
   sudo iptables -t nat -L -n | grep -E "9000|8080|8081"
   ```
3. **MTU 检查**: 手机 cellular MTU 通常 1280-1400, docker bridge 默认 1500。
   双 bridge 时 MTU 协商有时挂。`/etc/docker/daemon.json` 加 `{"mtu":1400}`,
   重启 docker 看是否解决。
4. **conntrack 表溢出**:
   ```bash
   cat /proc/sys/net/netfilter/nf_conntrack_count
   cat /proc/sys/net/netfilter/nf_conntrack_max
   ```
5. **改架构**: 把 aishi-demo 加入 wp-stack 网络,统一在一个 docker compose 里
   管理。或反代:WP nginx 加 `/demo/` location 指向 demo 容器,统一 8081 端口。
   后者要求改 Flask 静态资源路径,工作量大。

### P2: 备份 + 域名 (后续)

- WP 数据备份: `~/captureaishi/wp-stack/wp-data/` + DB dump
- 备案: 国内 ECS 走 80/443 + 域名要 ICP

## 关键文件 / 路径

```
captureaishi/
├── Dockerfile                  demo 镜像
├── requirements-demo.txt       3 条依赖
├── .dockerignore
├── web_ui.py                   Flask 入口
├── web/
│   ├── demo.py                 DemoSession + canned 响应 (DEMOAISHI=1 时启用)
│   ├── routes/
│   │   ├── capture.py          /api/start /api/status (含 demo_pose)
│   │   ├── bridge.py hacks.py obs.py tools.py trajectory.py  (canned 短路)
│   │   └── ...
│   └── templates/
│       └── index.html          UI (含 3D viewer + demo ribbon)
├── demo/
│   └── scenarios/
│       └── batman_ak/
│           ├── manifest.json   total_poses=7, dwell=2.0
│           ├── script.json     11 行 preamble + 13 行 postamble
│           ├── frames/
│           │   ├── trajectory.json    7 orbit waypoints
│           │   └── .gitkeep    (真帧待用户上传)
│           └── README.md
├── wp-stack/
│   ├── docker-compose.yml      MySQL 8 tuned + WP fpm-alpine + nginx
│   ├── nginx.conf
│   ├── .env                    DB 密码 (gitignore)
│   └── .env.example
└── docs/
    ├── deploy_demo.md
    ├── deploy_wp.md
    └── session_handoff_2026_05_04.md   <-- 本文件
```

## Git 工作流

- **GitHub origin**: `https://github.com/eaglefly628/captureaishi.git` (private)
- **Gitee 镜像**: `https://gitee.com/eaglefly628/captureaishi.git` (private, 国内 ECS pull 用)
- **分支**: 始终在 `claudeMainBranch`(CLAUDE.md 强制规定,不能新建 feature 分支)

更新流程:
1. Windows 改完代码 → `git push origin claudeMainBranch && git push gitee claudeMainBranch`
2. ECS → `cd ~/captureaishi && git pull && docker build -t captureaishi-demo . && docker stop aishi-demo && docker rm aishi-demo && docker run -d --restart=unless-stopped --name aishi-demo -p 9000:8080 captureaishi-demo`

## 最近 commits

```
a0f2869  wp-stack: MySQL 8 tuned + WP + Nginx + 部署 doc
b3ae149  Demo Mode: 7-pose Batman + 3D progressive draw
9381c91  vscode: Demo Mode launch config
74eed58  Dockerfile + deploy_demo.md
c6a3199  Batman scenario step 2 (manifest + script + trajectory)
d1015d9  Demo Mode step 1 scaffolding
```

## 给新 session 的开场提示

复制以下内容作为新 session 的第一条消息:

> 接前一 session,继续做爱萌项目。状态见
> `docs/session_handoff_2026_05_04.md`,先读这个文件。
> 我刚把 7 张真帧上传到 `demo/scenarios/batman_ak/frames/`,
> 验证下 Output gallery 显示是否正确;如果 OK,继续设计
> 爱萌营销 HTML 单页 (路 1: 自包含 HTML 我粘到 WP)。
