# 部署爱萌官网 (WordPress) 到同一台 ECS

WordPress + MySQL 8 (tuned) + Nginx，跟 captureaishi-demo 共用一台 2 GB ECS。
WP 监听 8081，demo 占 8080。两个互不干扰。

## RAM 预算

| 组件 | 上限 |
|------|------|
| MySQL 8 (tuned) | 280 MB |
| WordPress (PHP-FPM) | 220 MB |
| Nginx | 50 MB |
| Demo container | 120 MB |
| 系统 + Docker | 250 MB |
| **总计** | **~920 MB** ≪ 2 GB |

## 一次性部署

SSH 进 ECS：

```bash
cd ~/captureaishi/wp-stack
cp .env.example .env
nano .env       # 替换两个密码（强随机串）
ls -la          # 确认 .env 存在
docker compose up -d
docker compose ps
```

`docker compose ps` 应该看到三行 (db / wordpress / nginx) 都是 `running` 或 `Up`。

`db` 第一次会做 init，10-30 秒可能 `(unhealthy)`，等下再看变 `(healthy)`。

## 阿里云控制台开 8081 入向

ECS → 实例 → 安全组 → 入方向 → 加一条：
- 协议 TCP
- 端口 `8081/8081`
- 源 `0.0.0.0/0`
- 描述 `wordpress`

## 浏览器首次安装

```
http://139.224.204.231:8081/wp-admin/install.php
```

填：
- 站点标题：爱萌
- 用户名：admin（或你想要的）
- 密码：自动生成的强随机串，复制存到密码管理器
- 你的电邮
- 「安装 WordPress」

登录 `http://139.224.204.231:8081/wp-admin`。

## 选个轻主题（半小时建好站）

后台 → **外观 → 主题 → 添加新主题**：

- **Astra**（推荐）→ 启用 → 安装配套 **Starter Templates** 插件 → 选 "Agency" / "Tech Startup" / "Software Company" 类模板 → 一键导入 → 替换文字 + 公司 logo

模板里的"Get Started" / "Try Demo" 按钮链接改成：
```
http://139.224.204.231:8080
```

或更优雅：在 Astra 里建一个 "Demo" 页面，里面放 `<iframe src="http://139.224.204.231:8080" width="100%" height="900px">` 或直接一个大按钮跳过去。

## 必装的两个插件

1. **WP Super Cache** 或 **W3 Total Cache** — 页面缓存，国内 ECS 单核扛 10x 流量
2. **Limit Login Attempts Reloaded** — 防 wp-admin 爆破

可选：
- **Yoast SEO** — 基础 SEO（不开高级才不吃 RAM）
- **Contact Form 7** — 留言表单

**装完一定停用所有未用的默认插件**（Akismet、Hello Dolly 等），WP 越精简越轻。

## 日常维护

**重启**：
```bash
cd ~/captureaishi/wp-stack
docker compose restart
```

**看日志**：
```bash
docker compose logs -f --tail 50 nginx
docker compose logs -f --tail 50 wordpress
docker compose logs -f --tail 50 db
```

**升级 WP 核心 / 主题 / 插件**：在后台直接点 "更新"。

**升级镜像**（半年一次）：
```bash
cd ~/captureaishi/wp-stack
docker compose pull
docker compose up -d
```

**备份数据**（每月一次推荐）：
```bash
# DB 导出
docker compose exec db mysqldump -u root -p<DB_ROOT_PASSWORD> aimeng_wp > ~/wp-backup-$(date +%F).sql
# 文件备份（uploads + theme 改动）
tar czf ~/wp-files-$(date +%F).tar.gz wp-data/wp-content/uploads wp-data/wp-content/themes/<你用的主题>
```

## RAM 不够 / 卡了怎么办

**先看占用**：
```bash
docker stats --no-stream
```

**MySQL 占用过高**：MySQL 8 真的吃，切到 MariaDB 几乎零成本：
```bash
# 1) 备份 DB
docker compose exec db mysqldump -u root -p<密码> aimeng_wp > /tmp/wp.sql
# 2) 改 docker-compose.yml: 把 'image: mysql:8.0' 改成 'image: mariadb:10.11', 'command:' 那段保持, 'MYSQL_*' 环境变量改成 'MARIADB_*'
# 3) docker compose down
# 4) sudo rm -rf db-data/   <-- 旧 MySQL 数据弃用
# 5) docker compose up -d
# 6) 等 db healthy 后导回 SQL
docker compose exec -T db mysql -u root -p<密码> aimeng_wp < /tmp/wp.sql
```

**或直接升 ECS 内存到 4G**（控制台升级，要重启，约 3 分钟）。

## 后续：解开 80/443 端口

国内 ECS 走 80/443 + 自定义域名必须 ICP 备案：
1. 阿里云域名注册控制台 → 备案 → 跟着流程交资料
2. 备案号下来后改 nginx 监听 80 + 申请 SSL（Let's Encrypt 或阿里云免费证书）
3. 改 docker-compose.yml 端口 `"80:80"`, `"443:443"`

香港/海外 region 不需备案，可直接走 80/443。
