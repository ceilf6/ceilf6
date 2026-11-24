# `site/server` 独立发布、热备份与故障回退运维指南

本目录提供 `wangjinghong.com` 动态后端（`site/server/`）的原子发布、SQLite 在线一致性热备份、健康探测与自动/手动回退工具链。动态后端与静态前端发布链路（仓库根 `deploy/publish.sh site` -> `/var/www/wangjinghong`）完全解耦，前后端任意一方发布、重启或回退均互不覆盖、互不中断持久化数据。

---

## 1. 目录与持久化隔离约定

| 路径 | 属主与权限 | 用途说明 |
| --- | --- | --- |
| `/var/www/wangjinghong` | 静态前端专用 | 由前端发布脚本管理；**后端发布与回退全程绝不触碰** |
| `/opt/wangjinghong/releases/<release_id>/server` | `root:root` (`0755` / `0644`) | 不可变后端历史版本目录（含 `staticfiles/` 与激活标记 `.activated`） |
| `/opt/wangjinghong/shared/venvs/<req_sha>` | `root:root` (`0755`) | 按 `requirements.txt` 哈希隔离的 Python >= 3.12 虚拟环境 |
| `/opt/wangjinghong/shared/venv` | 原子软链 | 指向当前生效版本对应的 `venvs/<req_sha>`（发布与回退同步原子切换） |
| `/opt/wangjinghong/shared/.maintenance` | 瞬态维护屏障 | 含迁移发布或数据库恢复期间由脚本自动创建，Nginx 动态路由返回 `503 no-store`，验活通过后自动解除 |
| `/opt/wangjinghong/current` | 原子软链 | 指向当前生效的 `releases/<release_id>`（维护 `.release-history` 激活栈） |
| `/etc/wangjinghong/server.env` | `root:root` (`0600` 或 `root:www-data 0640`) | `systemd` `EnvironmentFile` 格式生产配置（严禁 `export ` 前缀或宽于 `0640` 的权限） |
| `/var/lib/wangjinghong/db.sqlite3` | `www-data:www-data` (`0640`) | SQLite WAL 主数据库（含 `-wal`、`-shm`） |
| `/var/lib/wangjinghong/backups/` | `www-data:www-data` (`0750`，快照 `0600`) | 每次发布及 `--restore-db` 前生成的在线一致性备份（自动按配额清理） |
| `/var/lib/wangjinghong/cache/` | `www-data:www-data` (`0700`) | Django 文件缓存（跨重启保留登录/注册与接口限流计数） |
| `/var/lib/wangjinghong/mail/` | `www-data:www-data` (`0700`) | `filebased.EmailBackend` 邮件落盘目录 |
| `/var/lock/wangjinghong-server-deploy.lock` | `root:root` (`0600`) | 后端独立 `flock` 互斥锁，防止并发发布或回退冲突 |

---

## 2. 源站首次上线初始化步骤

在源站 ECS（Ubuntu 24.04，以下用 `<ECS_HOST>` 表示服务器地址）以 `root` 执行一次性初始化：

1. **准备生产环境变量文件 `/etc/wangjinghong/server.env`**（采用子壳 `(umask 077 && ...)` 写入，避免污染当前 root 会话的默认 `umask`；语法严格遵循 `systemd` `KEY=VALUE`，勿加 `export `）：

   ```bash
   install -d -m 0750 -o root -g root /etc/wangjinghong
   (
     umask 077
     python3 -c 'import secrets; print("DJANGO_SECRET_KEY=" + secrets.token_urlsafe(48))' > /etc/wangjinghong/server.env
     cat >> /etc/wangjinghong/server.env <<'EOF'
   DJANGO_DEBUG=false
   DJANGO_ALLOWED_HOSTS=www.wangjinghong.com,wangjinghong.com,127.0.0.1,localhost
   # 直连源站单层 Nginx 反代时设为 1；若前方经过阿里云 CDN + 源站 Nginx 双层反代，请设为 2
   DJANGO_TRUSTED_PROXY_COUNT=1
   DJANGO_ADMIN_PATH=ops-console/
   SQLITE_PATH=/var/lib/wangjinghong/db.sqlite3
   DJANGO_CACHE_PATH=/var/lib/wangjinghong/cache
   DJANGO_EMAIL_BACKEND=django.core.mail.backends.filebased.EmailBackend
   EMAIL_FILE_PATH=/var/lib/wangjinghong/mail
   ALLOW_GUEST_COMMENTS=true
   EOF
     chown root:root /etc/wangjinghong/server.env
     chmod 0600 /etc/wangjinghong/server.env
   )
   ```

   > 若启用外部加密 SMTP 发信，请按 `site/server/.env.example` 方案 B 将 `DJANGO_EMAIL_BACKEND` 切换为 `django.core.mail.backends.smtp.EmailBackend` 并配置 465（SSL）或 587（TLS）凭据。

2. **安装 systemd 服务单元**：

   ```bash
   install -m 0644 wangjinghong-api.service /etc/systemd/system/wangjinghong-api.service
   systemctl daemon-reload
   systemctl enable wangjinghong-api
   ```

3. **执行首次后端发布**（在开发机或 CI 中执行）：

   ```bash
   DEPLOY_HOST=<ECS_HOST> bash site/deploy/publish-server.sh deploy
   ```

   若宿主机尚未安装 `python3-venv` / `ensurepip`，`remote_server.py` 会在 root 权限下自动执行 `apt-get install -y python3-venv` 并完成虚拟环境初始化、静态收集、数据库迁移、软链切换、服务启动与本机健康检查。

4. **挂载 Nginx 同域反代片段**：

   将 `site/deploy/nginx-wangjinghong.conf` 复制至 `/etc/nginx/snippets/wangjinghong-api.conf`，确认其中后台路径（默认 `/ops-console/`）与 `/etc/wangjinghong/server.env` 中的 `DJANGO_ADMIN_PATH` 一致，然后在源站 HTTPS `server { ... }` 块中加入：

   ```nginx
   include /etc/nginx/snippets/wangjinghong-api.conf;
   ```

   校验配置无误后平滑重载 Nginx：

   ```bash
   nginx -t && systemctl reload nginx
   ```

---

## 3. 日常独立发布与健康验证

- **发布新版本后端**（严禁硬编码真实 IP，统一通过环境变量注入 `DEPLOY_HOST`）：

  ```bash
  DEPLOY_HOST=<ECS_HOST> bash site/deploy/publish-server.sh deploy
  ```

  可选环境变量：`DEPLOY_KEY`（默认 `~/.ssh/wangjinghong-mac-2026.pem`）、`DEPLOY_USER`（默认 `root`）、`RELEASE_ID`（默认 `<UTC时间>-<git短SHA>`）。

  发布流程会自动完成：
  1. 本地运行 `node site/scripts/update-note-slugs.mjs --check` 校验札记 slug 白名单同步；
  2. 远端获取 `/var/lock/wangjinghong-server-deploy.lock` 排他锁并校验 `/etc/wangjinghong/server.env` 权限与语法；
  3. 按 `requirements.txt` 哈希准备独立虚拟环境 `shared/venvs/<req_sha>`（不干扰正在运行的旧进程），在新版本目录执行 `collectstatic --noinput` 与 `check --deploy`；
  4. 通过 `manage.py migrate --check --noinput` 检测是否存在待执行迁移：
     - **无新迁移**：在线生成常规备份 `db-<ts>-<release_id>.sqlite3` 后直接切换 `shared/venv` 与 `current`、重启并探测健康接口；
     - **含新迁移或首次建库**：先暂停旧服务关闭写入窗口，生成迁移前快照后执行 `migrate --noinput`，再切换软链、重启并探测健康接口；
  5. 激活成功后写入 `.activated` 与 `.release-history`，并自动清理超配额的旧版本、未引用 `shared/venvs/*` 及历史备份（`db-*.sqlite3` 与 `pre-rollback-*.sqlite3`）。

- **手工健康检查命令**：

  ```bash
  # 源站本机回环探测
  curl -i --noproxy '*' -H 'Host: www.wangjinghong.com' -H 'X-Forwarded-Proto: https' http://127.0.0.1:8000/api/health/

  # 公网同域反代探测
  curl -i https://www.wangjinghong.com/api/health/
  ```

---

## 4. 自动回退机制与手动故障回退

- **发布期失败自动回退**：
  - 若本次发布**未执行数据库迁移**（`migrate --check` 为空）而重启或健康探测失败：仅将 `shared/venv` 与 `current` 原子切回上一稳定版本并重启验活，**绝不覆盖数据库**，100% 保留发布窗口内新产生的线上评论、注册与会话；
  - 若本次发布**已进入迁移阶段**且失败：自动停止异常进程，使用停服后生成的迁移前快照通过 `sqlite3.Connection.backup()` 恢复数据库（首次建库失败则清理脏库文件），切回旧版 `shared/venv` 与 `current` 并重启验活，同时清理失败版本目录。

- **手动回退到上一稳定版本**（沿 `.release-history` 激活栈依次回退，连续执行可从 `v3 -> v2 -> v1` 逐级后退）：

  ```bash
  DEPLOY_HOST=<ECS_HOST> bash site/deploy/publish-server.sh rollback
  ```

  > **表结构兼容性提示**：不带 `--restore-db` 的 `rollback` 仅回退后端代码与 `shared/venv` 依赖，保留当前数据库中的全部新评论与用户数据（适用于常规代码回退或向后兼容的新增列/索引迁移）。若待回退的新版本曾执行过**不向后兼容的表结构破坏性变更**（如重命名/删除旧代码仍依赖的列），请按下述命令配合 `--restore-db` 同步恢复对应版本的迁移前数据库快照。

- **回退到指定历史版本并恢复指定数据库快照**（注意：`db-<timestamp>-<migrating_release_id>.sqlite3` 保存的是 `<migrating_release_id>` **执行迁移之前**的数据库状态，因此 `--to` 应指定与之表结构匹配的**前一稳定版本 `<previous_release_id>`**；工具会在开放流量前对目标版本强制执行 `sqlite_ops.py verify-schema` 校验双向迁移图与 ORM 业务表读取兼容性，不匹配或中途异常将自动自愈恢复原版本与原服务）：

  ```bash
  DEPLOY_HOST=<ECS_HOST> bash site/deploy/publish-server.sh rollback \
    --to <previous_release_id> \
    --restore-db db-<timestamp>-<migrating_release_id>.sqlite3
  ```
