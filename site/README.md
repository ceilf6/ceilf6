# wangjinghong.com 站点工程与动态账号评论系统（课程作业 1）

本目录（`site/`）是个人网站 [`https://www.wangjinghong.com`](https://www.wangjinghong.com) 的工程根目录，同时作为《Internet应用开发》（课程号 `23306046`）**作业 1：现代全栈动态网站**的交付目录。AI 辅助开发声明见同目录 [`AI_USAGE.md`](./AI_USAGE.md)，后端生产部署细则见 [`deploy/README.md`](./deploy/README.md)。

---

## 一、既有基线与本次作业新增范围

为如实区分本人既有个人主页沉淀与课程期间新增的全栈动态开发工作，边界说明如下：

- **既有静态基线（非本次作业新增）**：
  - 首页个人名片、获奖证书瀑布流画廊（`/viewer`）、Vlog 页（`/vlog`）、构建期编译静态 Markdown 的技术札记阅读页（`/blog`、`/notes/:slug`），以及仓库根目录服务于 GitHub 个人主页的统计卡片流水线（`README.md`、`stats/`、`assets/`）。
- **本次作业 1 新增全栈动态能力（全部位于 `site/` 内）**：
  1. **账号与身份认证系统（`site/server/accounts/`）**：邮箱 + 密码 + 公开昵称（`display_name`）注册、零外部密钥的文件邮件验证（`filebased.EmailBackend`，生产可选加密 SMTP）、密码重置、CSRF `POST` 退出登录、统一登录入口 `/accounts/login/`（收拢自定义后台入口并严格校验站内 `next` 回跳）及当前会话查询接口 `GET /api/me/`。
  2. **札记动态评论与权限系统（`site/server/comments/`）**：支持未登录访客直发（`author = NULL`，固定展示为「未登录用户」）与已验证账号署名发言、服务端 `ALLOW_GUEST_COMMENTS` 环境变量开关、`before` 游标分页、文件缓存原子限频与蜜罐校验、作者本人删评及站主跨札记全站审核。
  3. **前端札记评论交互组件（`site/src/data/comments.ts`、`site/src/components/NoteComment*.tsx`）**：在不改动首页/画廊等既有页面的前提下，于 `/notes/:slug` 正文底部接入评论列表分页、纯文本防 XSS 渲染、访客/成员发表、按札记隔离的 `sessionStorage` 草稿保护、跨标签页登录/CSRF 轮换自动同步与行内二次确认删评。
  4. **独立持久化部署与回退工具链（`site/deploy/`、`site/scripts/vite-local-proxy.mjs`）**：本地 Vite 同源反代，以及与静态站点原子切换目录完全隔离的后端版本发布、SQLite WAL 在线热备、迁移结构安全校验与一键回退脚本。

---

## 二、需求分析与核心业务规则

1. **双路径发言与访客开关**：
   - 默认 `ALLOW_GUEST_COMMENTS=true`：未登录访客无需注册即可直接在札记下发表评论，`Comment.author` 存为 `NULL`，页面统一渲染为「未登录用户」（附「访客」标识），后续注册或登录不会自动认领历史访客留言。
   - 当运维将服务端 `ALLOW_GUEST_COMMENTS=false` 时：服务端拒绝新访客写请求（返回 `403 guest_comments_disabled`），已有历史评论照常公开可读，前端禁用访客提交按钮并保留已输入草稿引导登录；已验证邮箱的登录账号不受影响，仍可继续发表与管理本人评论。
2. **隐私隔离与服务端会话裁决**：
   - 登录邮箱仅用于身份认证与找回密码，内部 `User.username` 自动生成不透明标识（`u_<hex>`）；任何公开接口或管理列表均不向公众暴露用户邮箱。
   - 评论归属与删评权限完全由服务端 Session 裁决，前端仅提交 `expectedAuthorKind`（`"guest"` | `"member"`）用于防止跨标签页会话漂移导致误以非预期身份发言（不一致时返回 `409 author_state_changed`）。
3. **三级删评权限矩阵**：
   - **未登录访客**：无删评按钮，直接请求删评接口返回 `401 authentication_required`。
   - **普通已验证账号**：仅可删除本人发表的账号评论（`204`）；尝试删除访客评论或他人评论均返回 `403 permission_denied`；访问后台管理路径立即返回 `403`（不产生登录重定向死循环）。
   - **站主管理账号（`is_comment_admin=True`）**：既可在任意 `/notes/:slug` 页面逐条删除访客、普通账号与本人的评论，也可通过同一登录态进入自定义路径 Django Admin 跨札记检索、筛选与批量删除全站评论。

---

## 三、技术架构与全链路设计

### 1. 请求与持久化链路

```text
[浏览器 React 19 SPA (/notes/:slug -> NoteComments)]
        │  同源 HTTPS 请求 (Cookie: sessionid, csrftoken + Header: X-CSRFToken)
        ▼
[阿里云全站加速 CDN (Tengine)]
        │  静态资源按规则缓存；动态路径遵循源站 Cache-Control: private, no-store 零缓存回源
        │  注：标准版 CDN 仅透传 GET/POST，故删评接口设计为 POST /api/comments/<id>/delete/
        ▼
[源站 Nginx 1.24 (同源反向代理)]
        ├── /、/blog、/notes/*、/static/*  ──► /var/www/wangjinghong (静态构建产物，原子目录切换)
        └── /api/*、/accounts/*、/<admin>/*、/django-static/*
                │  强制响应头 Cache-Control: private, no-store, no-cache, must-revalidate
                ▼
[Gunicorn + Django 5.2 (systemd: wangjinghong-api.service，常驻约 48 MiB RSS)]
        ├── AuthenticationMiddleware + CsrfViewMiddleware (HttpOnly, SameSite=Lax, Secure)
        ├── django-allauth + UnifiedLoginAdminSite (统一登录与安全内部 next 回跳校验)
        ├── FileBasedCache 原子限频 + Unicode 控制字符清洗 + note_slugs.json 白名单校验
        └── Django ORM ──► SQLite 3 (WAL 模式 + busy_timeout=5000 + 严格外键与 CHECK 约束)
                               └── /var/lib/wangjinghong/db.sqlite3 (独立于静态发布目录持久化)
```

### 2. 关键工程决策

- **同源架构消除跨域复杂度**：本地开发通过 `site/scripts/vite-local-proxy.mjs`（`changeOrigin: false`）将 `/api`、`/accounts`、`/django-static` 与后台前缀转发至本地 Django；线上由同一域名下的 Nginx 反代分流。前后端完全同源，无需放宽 CORS 或降低 `SameSite` Cookie 安全策略。
- **CDN 防串号与方法兼容**：动态视图中间件与 Nginx 双重写入 `Cache-Control: private, no-store, no-cache, must-revalidate` 与 `Vary: Cookie`；针对阿里云标准版 CDN 仅允许 `GET/POST` 的约束，删评动作采用受 CSRF 保护的 `POST /api/comments/<comment_id>/delete/`，返回 `204 No Content`。
- **存储型 XSS 零信任渲染**：前端评论组件仅通过 React 纯文本节点渲染 `body` 与 `displayName`，全程不使用 `dangerouslySetInnerHTML`。
- **静动分离持久化**：前端 `deploy-ecs.yml` 每次仅替换 `/var/www/wangjinghong`；后端代码位于 `/opt/wangjinghong/releases/<id>`，SQLite 数据库、在线热备与本地邮件独立存放在 `/var/lib/wangjinghong/`，静态重发版与后端升级均不会覆盖用户与评论数据。

---

## 四、目录结构

```text
site/
├── src/
│   ├── data/comments.ts                  # 同源 API 客户端（/api/me/、列表分页、发评、删评、草稿存储）
│   ├── components/
│   │   ├── NoteComments.tsx              # 札记评论容器（会话与分页状态机、并发冲突合并重拉）
│   │   ├── NoteCommentComposer.tsx       # 评论发表框（访客/成员身份栏、回跳链接、字数与草稿保护）
│   │   ├── NoteCommentCard.tsx           # 单条评论卡片（纯文本渲染、权限判定与行内二次确认删评）
│   │   └── NoteComments*.test.tsx        # 列表、发表、异常恢复与删评 Vitest 组件单测
│   └── pages/Note.tsx                    # 札记详情页（正文就绪后挂载底部评论区）
├── server/
│   ├── config/                           # Django 配置、生产 fail-closed 环境变量解析、no-store 中间件、统一后台站点
│   ├── accounts/                         # 自定义 User 模型、allauth 适配器、表单、管理命令与 /api/me/
│   ├── comments/                         # Comment 模型、note_slugs.json 白名单、限频器、序列化、读写删视图与 Admin
│   ├── templates/                        # 与主站深色玻璃态风格一致的登录/注册/邮件确认/密码重置/403 模板
│   └── requirements.txt                  # Python 依赖锁（Django 5.2、django-allauth、gunicorn）
├── deploy/                               # 后端独立发布/回退脚本、SQLite 热备与 schema 校验、Nginx/systemd 模板及沙箱测试
├── scripts/                              # 构建脚本、note_slugs 同步脚本、Vite 同源代理模块及 node:test 用例
├── README.md                             # 本说明文档
└── AI_USAGE.md                           # 课程作业 AI 使用声明（按教师模板填写）
```

---

## 五、从干净环境零密钥本地运行指南

本地开发**不需要任何第三方密钥、外部数据库或 SMTP 账号**：`manage.py` 在开发模式下默认使用本地 `site/server/var/db.sqlite3`（自动开启 WAL）、本地文件缓存 `site/server/var/cache/` 与本地文件邮件目录 `site/server/var/mail/`。

### 1. 环境准备

- **Node.js** `>= 22`（含 `npm`）
- **Python** `>= 3.12`（含标准库 `venv` 与 `sqlite3`）

### 2. 初始化并启动 Django 后端（终端 1）

```bash
cd site

# 创建虚拟环境并安装依赖
python3 -m venv .venv
.venv/bin/pip install -r server/requirements.txt

# 初始化 SQLite 数据库表结构与约束
.venv/bin/python server/manage.py migrate

# （可选）一键创建已验证邮箱的本地站主管理账号
printf '%s\n' 'LocalDemo!2026' | .venv/bin/python server/manage.py ensure_verified_user \
  --email admin@local.test --display-name "本地站主" --password-stdin
.venv/bin/python server/manage.py grant_comment_admin --email admin@local.test

# 启动本地后端服务（默认监听 127.0.0.1:8000）
.venv/bin/python server/manage.py runserver 127.0.0.1:8000
```

### 3. 启动前端同源开发服务器（终端 2）

```bash
cd site
npm ci
npm run dev
```

浏览器打开终端输出的本地地址（默认 `http://localhost:5173/notes/cc-source-analysis`）：

- **访客直发体验**：未登录状态下直接在底部评论框输入内容点击「发表评论」，即可看到以「未登录用户」身份写入 SQLite 并即时展示；重启 `runserver` 后刷新页面评论依然存在。
- **自助注册与本地验证信查看**：点击评论区右上角「注册」提交邮箱、公开昵称与密码后，验证邮件会自动写入 `site/server/var/mail/` 目录；打开最新邮件文件中的 `http://localhost:5173/accounts/confirm-email/.../` 链接确认后，即可登录回跳原札记署名发言并删除本人评论。
- **站主全站管理体验**：使用上一步创建的 `admin@local.test` 登录后，可在任意札记页逐条删除访客或成员评论，也可访问 `http://localhost:5173/admin/` 进入后台跨札记检索管理。
- **测试暂停访客发言开关**：以 `ALLOW_GUEST_COMMENTS=false .venv/bin/python server/manage.py runserver 127.0.0.1:8000` 重启后端，刷新页面可见未登录访客提交被禁用且草稿保留，登录账号仍可正常发表评论。

---

## 六、自动化检查与测试命令

在 `site/` 目录下可执行以下完整验证套件：

```bash
# 1. 前端静态检查、类型检查、组件单元测试（25 files / 115 tests）与生产构建
npm run lint
npm run type-check
npx vitest run
npm run build

# 2. 后端 Django 配置检查、迁移一致性校验与单元/集成测试
.venv/bin/python server/manage.py check
.venv/bin/python server/manage.py makemigrations --check --dry-run
.venv/bin/python server/manage.py test --verbosity 2

# 3. 札记 slug 同步、本地同源代理与后端发布/回退沙箱全量回归
node --test scripts/*.test.mjs
```

---

## 七、线上部署与公网实测验收记录

### 1. 部署方式概要

- **静态前端**：合入 `main` 分支后由 `.github/workflows/deploy-ecs.yml` 自动构建 `site/dist` 并原子切换至源站 `/var/www/wangjinghong`。
- **动态后端**：通过 `DEPLOY_HOST=<ECS_HOST> bash site/deploy/publish-server.sh deploy` 独立打包 `site/server/` 发布至 `/opt/wangjinghong/releases/<release_id>`，自动执行 SQLite 热备、非破坏性迁移校验、`collectstatic`、systemd 重启与回环健康探针检查；异常时支持 `publish-server.sh rollback` 一键回退代码与迁移前数据库快照。

### 2. 公网端到端与持久化验收证据（2026-11-24 UTC）

在正式域名 `https://www.wangjinghong.com`（经阿里云全站加速 CDN 回源至上海地域 2C2G ECS）已完成以下实测：

1. **三独立会话防串号实测**：使用站主会话 A、公网自助注册并完成文件邮件确认的普通账号会话 B、未登录访客会话 C 按 `A → B → C → A → C → B` 交替请求 `/api/me/`，6 次响应均返回 `200`、`Cache-Control: private, no-store, no-cache, must-revalidate`、`x-swift-cachetime: 0`、`x-cache: MISS TCP_MISS`，零身份串号。
2. **权限矩阵与 CDN `POST` 删评实测**：公网实测访客发评（`201`）与普通账号发评（`201`）后，经 CDN 调用 `POST /api/comments/<id>/delete/`：访客返回 `401`、普通账号删访客评论返回 `403`、普通账号删本人评论返回 `204`、站主账号删访客评论返回 `204`；后台自定义管理入口对站主返回 `200`、普通账号返回 `403`、未登录访客 `302` 跳转统一登录页。
3. **`ALLOW_GUEST_COMMENTS` 在线切换实测**：将源站配置切为 `false` 重启服务后，公网 `/api/me/` 即时返回 `guestCommentsAllowed=false`，访客发评返回 `403 guest_comments_disabled`，普通登录账号发评仍返回 `201`；测试后已恢复为 `true`。
4. **跨进程重启与跨版本发布持久化回读实测**：
   - 前端构建产物 `/static/Note-D9WIIhg5.js` 上线后，于 `2026-11-24T11:10:36.202247Z` 经公网在 `/notes/cc-source-analysis` 发表持久化验证评论（返回 `id=7`）；
   - 随后依次执行 `systemctl restart wangjinghong-api` 进程重启，以及运行 `publish-server.sh deploy` 切换全新后端发布目录 `20261124T111034Z-b7cd2603`；
   - 使用全新匿名会话请求 `https://www.wangjinghong.com/api/notes/cc-source-analysis/comments/`，准确读回同一条 `id=7`（`createdAt="2026-11-24T11:10:36.202247Z"`）记录；确认持久化无误后，由站主会话执行 `POST /api/comments/7/delete/`（`204`）清理验收测试评论，保持线上公开札记整洁。
