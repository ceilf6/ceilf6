# wangjinghong.com 站点工程、全站导航与动态账号评论系统（课程作业 1）

本目录（`site/`）是个人网站 [`https://www.wangjinghong.com`](https://www.wangjinghong.com) 的工程根目录，同时作为《Internet应用开发》（课程号 `23306046`）**作业 1：现代全栈动态网站**的交付目录。AI 辅助开发声明见同目录 [`AI_USAGE.md`](./AI_USAGE.md)，后端生产部署细则见 [`deploy/README.md`](./deploy/README.md)。

---

## 一、既有基线与本次作业新增范围

为如实区分本人既有个人主页沉淀与课程期间新增的全栈动态及全站交互开发工作，边界说明如下：

- **既有静态基线（非本次作业新增）**：
  - 首页个人名片与粒子动效长卷（`/`）、获奖证书瀑布流画廊及大图查看器（`/viewer`）、视频外链舞台页（`/vlog`）、构建期编译静态 Markdown 的技术札记阅读页（`/blog`、`/blog/:slug`），以及仓库根目录服务于 GitHub 个人主页的统计卡片流水线（`README.md`、`stats/`、`assets/`）。
- **本次作业 1 新增全栈动态与全站导航能力（全部收敛在 `site/` 内，仓库根目录 `README.md` 零改动）**：
  1. **账号、身份认证与个人设置系统（`site/server/accounts/`、`site/server/templates/account/`）**：邮箱 + 密码 + 公开昵称（`display_name`）注册（`/accounts/signup/`）、邮件验证链接确认（本地默认零外部密钥 `filebased.EmailBackend` 落盘，线上生产通过阿里云邮件推送 `smtpdm.aliyun.com:465` SSL 真实发信；匿名确认邮箱后跳到登录页并提示「邮箱已确认，请登录。」）、密码重置（重设密码后跳回登录页并显示「密码已更新。」toast）、CSRF `POST /accounts/logout/` 退出登录、统一登录入口 `/accounts/login/`（收拢自定义后台入口并严格校验站内 `next` 回跳）、受登录保护的账号设置页 `GET/POST /accounts/settings/`（支持修改公开昵称与「自动 + 8 种深色调色板」头像底色，含无 JS 服务端首字母预览与 PRG 回跳）及当前会话查询接口 `GET /api/me/`（已登录时输出 `avatarColor`）。
  2. **全站统一顶栏、证书画廊独立页与会话联动（`site/src/session/SessionProvider.tsx`、`site/src/components/SiteHeader.tsx`、`site/src/components/AccountPanel.tsx`、`site/src/pages/Awards.tsx`）**：在不破坏首页长卷 `sticky` 窗帘与入场动效结构的前提下，为除沉浸式看图页 `/viewer`（及旧直链 `/viewer.html`）外的全站页面接入统一单行固定顶栏（左侧「首页 · 博客论坛 · 项目视频 · 证书画廊」四栏目统一导航与当前项高亮、已在首页点击「首页」平滑回顶，右侧 GitHub 外链与三种登录态账号区），新增证书画廊独立页 `/awards`、主页两节居中标题跳转（`/awards`、`/blog`）、跨页滚动复位、看图页 `/viewer` 来源锁存回跳及全站统一的 `王景宏 · …` 浏览器标签标题规范。
  3. **札记动态评论与权限系统（`site/server/comments/`）**：支持未登录访客直发（`author = NULL`，固定展示为「未登录用户」，`author.avatarColor` 为 `null`）与已验证账号署名发言（`author.avatarColor` 与 `/api/me/` 同源输出 `#RRGGBB` 头像底色）、服务端 `ALLOW_GUEST_COMMENTS` 环境变量开关、`before` 游标分页、文件缓存原子限频与蜜罐校验、作者本人删评及站主跨札记全站审核。
  4. **前端札记评论交互组件（`site/src/data/avatar.ts`、`site/src/data/comments.ts`、`site/src/components/CommentAvatar.tsx`、`site/src/components/NoteComment*.tsx`）**：在 `/blog/:slug` 正文底部接入评论列表游标分页、每条评论左侧 `28px` 评论者头像（已注册成员显示与顶栏一致的首字母和底色，访客显示统一的灰色人形图标）、纯文本防 XSS 渲染、访客/成员发表、按札记隔离的 `sessionStorage` 草稿保护、跨标签页登录/CSRF 轮换自动同步、与全站顶栏 `SessionProvider` 的双向会话身份同步，以及行内二次确认删评。
  5. **独立持久化部署与回退工具链（`site/deploy/`、`site/scripts/vite-local-proxy.mjs`）**：本地 Vite 同源反代（保护 `/`、`/blog`、`/vlog`、`/awards`、`/viewer` 等前端路由前缀不被后台配置误劫持），以及与静态站点原子切换目录完全隔离的后端版本发布、SQLite WAL 在线热备、兼容纯代码回退的迁移结构安全校验与一键回退脚本。

---

## 二、需求分析与核心业务规则

1. **全站统一顶栏、多栏目导航与浏览器标题规范**：
   - **顶栏挂载与视觉自适应**：除沉浸式证书看图页 `/viewer`（及旧直链 `/viewer.html`）外，`SiteHeader` 在全站固定置顶（所有视口宽度统一为单行高 `56px`，`≤ 560px` 压缩导航字号与按钮内边距、`≤ 359px` 隐藏顶栏 GitHub 图标留足 `320px` 窄屏余量，全视口零横向溢出且导航点击高度均不低于 `32px`；主页首屏透明保留粒子背景，滚动 `scrollY > 8` 或处于二级页时切换深色磨砂玻璃底）。左侧「首页（`/`，已在 `/` 时平滑滚回页顶，`prefers-reduced-motion` 下瞬时回顶） · 博客论坛（`/blog` 及 `/blog/:slug`） · 项目视频（`/vlog`） · 证书画廊（`/awards`）」四项主导航采用同一样式左对齐连续排列，并对当前所在栏目设置 `aria-current="page"` 高亮，二级栏目页统一通过「首页」返回主站；右侧通过 `margin-left: auto` 放置 GitHub 外链（共用 `site/src/data/site.ts` 的 `GITHUB_URL`）与账号状态区。根节点 `overflow-y: scroll` 一直显示站点自定义滚动条，长短页切换时布局不横向跳动；`overflow-x: hidden` 放在 `html` 上，以保证首页 `sticky` 窗帘正常。
   - **三种登录态与 WAI-ARIA Disclosure 账号面板**：会话请求期间渲染等尺寸骨架占位防布局跳动；未登录或 `/api/me/` 请求失败时降级显示带 `next=<pathname+search>` 的原生 `/accounts/login/` 链接；已登录时渲染 32px 首字母圆形头像按钮（优先通过 `Intl.Segmenter` 按字素簇取首字并转大写，无支持环境回退码位扫描并兼容 `Mn`/`Me`/`Mc` 组合符、国旗区域指示符、肤色修饰符及多段 ZWJ Emoji）与常驻 DOM 的 `<div id="account-panel">` Disclosure 面板（显式声明 `#account-panel[hidden] { display: none !important; }`，精确指针设备支持 hover 临时展开与 150 ms 移出收起、点击切换固定展开、`Esc` 收起并归还焦点至头像、点击外部或键盘 Tab 焦点移出容器自动收起）。面板内展示「公开昵称 · 站主/用户」身份标签、带 `next` 的 `/accounts/settings/`「设置」入口，以及携带 `csrfmiddlewaretoken` 与 `next` 的 `POST /accounts/logout/` 退出表单。
   - **全站会话双向同步**：根部 `SessionProvider` 维护 `{ status, session, refresh, syncSession }` 并在后台标签页切回前台（`visibilitychange` 10 秒节流）时自动刷新（后台刷新失败时保留原登录状态）；札记详情页 `NoteComments` 在挂载、重试连接或 `409`/`403` 冲突刷新时调用 `syncSession` 回写顶栏，同时监听 `SessionProvider` 的后台刷新结果反向同步评论区，确保顶栏与评论区始终展示同一身份。
   - **证书画廊独立页、滚动复位与看图来源锁存**：新增 `/awards` 独立页复用 `WaterfallGallery`；主页长卷「证书画廊」与改名后的「博客论坛」两节居中 `<h2>` 标题支持直接点击进入 `/awards` 与 `/blog`；`App.tsx` 在 `AnimatePresence` 退场完成回调（`onExitComplete`）中对非 `POP` 且无 `hash` 的路由跳转复位至页顶（浏览器前进/后退保留原滚动位置）；`Viewer.tsx` 挂载时按站内白名单（`/` 或 `/awards`）锁存 `location.state.from` 并在上下翻页 `replace` 时持续透传，确保多次翻页或页面刷新后关闭仍回到原入口页。全站前后端页面标签标题统一遵循 `王景宏 · <栏目> · <条目>` 格式。
2. **账号设置、头像底色与历史评论署名同步规则**：
   - **受保护的账号设置页（`GET/POST /accounts/settings/`）**：未登录访问时 `302` 跳转 `/accounts/login/` 并完整保留原 `next` 回跳目标；仅允许 `GET` 与 `POST`（其余方法返回 `405`），通过 `base.html` 的 `{% block back_link %}` 渲染唯一「← 返回原页面」链接；登录、退出、确认邮件的提示在 `AccountAdapter.add_message` 源头屏蔽，含 `@` 的残留提示由 `account_feedback` 上下文处理器兜底过滤。
   - **公开昵称校验与 PRG 按列保存**：昵称经 NFKC 规范化与首尾去空白，长度须为 1–64 字符且禁止控制字符、不可见格式字符及网址链接；保存采用 PRG（Post/Redirect/Get）模式重定向至 `/accounts/settings/?next=<安全站内路径>&saved=1`（仅 `GET` 且 `saved=1` 时以顶部纯文字 toast 形式显示「已保存」，约 4.5 秒自动淡出、鼠标悬停时暂停，昵称为空的老账号打开设置页时不预填回退文案而通过 `placeholder` 提示当前对外显示名；表单 `action` 不带查询串而由隐藏域传递经 `is_safe_internal_redirect_url` 校验的 `next`）；字段值未变时跳过写库（零 `UPDATE`），有变更时仅执行 `user.save(update_fields=[...])` 更新变更列，避免并发覆盖 `is_comment_admin` 权限状态。
   - **改名与改色同步历史评论（预期业务规则）**：评论通过外键关联作者账号，`GET` 与 `POST /api/notes/<slug>/comments/` 返回的每条评论 `author` 均携带 `avatarColor`（成员为 `#RRGGBB` 十六进制色值，访客为 `null`）；用户在 `/accounts/settings/` 修改公开昵称或头像底色后，该账号的新发评论与全部历史评论署名及底色均即时同步。
   - **8 色 WCAG AA 深色头像调色板与兼容迁移**：为规避图片上传带来的存储、CDN 缓存与 SVG XSS 攻击面，头像统一采用圆形深色底配白色首字母，`site/server/accounts/avatar.py` 唯一定义「自动（空串）」加 8 种预设深色（靛蓝 `#4F46E5`、紫罗兰 `#7C3AED`、天蓝 `#0369A1`、青绿 `#0F766E`、翠绿 `#047857`、琥珀 `#B45309`、玫红 `#BE123C`、石板灰 `#475569`，与白字对比度均满足 WCAG AA `>= 4.5:1`），设置页内置 `extract_avatar_initial()` 无 JS 服务端首字母预览。`User.avatar_color`（迁移 `0004_user_avatar_color`）同时声明 `default=""` 与 `db_default=""`，在 SQLite 表结构保留 `DEFAULT ''`，确保后端执行不带 `--restore-db` 的纯代码回退时可通过 `sqlite_ops.py` 结构兼容门禁且旧版代码注册写库不中断。
   - **`GET /api/me/` 会话与配色契约**：未登录返回 `{ user: null, csrfToken, guestCommentsAllowed }`；已登录时 `user` 对象返回 `{ id, displayName, isCommentAdmin, avatarColor }`，其中自动模式由服务端按 `AVATAR_PALETTE[id % 8]` 稳定计算 `#RRGGBB`；前端对 `avatarColor` 执行 `/^#[0-9a-f]{6}$/i` 校验，字段缺失或格式异常时自动回退金底深字（`--accent-gold` / `--bg-void`，对比度 `11.51:1`）兜底样式。
3. **双路径发言与访客开关**：
   - 默认 `ALLOW_GUEST_COMMENTS=true`：未登录访客无需注册即可直接在札记下发表评论，`Comment.author` 存为 `NULL`，页面统一渲染为「未登录用户」（附「访客」标识），后续注册或登录不会自动认领历史访客留言。
   - 当运维将服务端 `ALLOW_GUEST_COMMENTS=false` 时：服务端拒绝新访客写请求（返回 `403 guest_comments_disabled`），已有历史评论照常公开可读，前端禁用访客提交按钮并保留已输入草稿引导登录；已验证邮箱的登录账号不受影响，仍可继续发表与管理本人评论。
4. **隐私隔离与服务端会话裁决**：
   - 登录邮箱仅用于身份认证与找回密码，内部 `User.username` 自动生成不透明标识（`u_<hex>`）；任何公开接口、设置回显或管理列表均不向公众暴露用户邮箱。
   - 评论归属与删评权限完全由服务端 Session 裁决，前端仅提交 `expectedAuthorKind`（`"guest"` | `"member"`）用于防止跨标签页会话漂移导致误以非预期身份发言（不一致时返回 `409 author_state_changed`）。
5. **三级删评权限矩阵**：
   - **未登录访客**：无删评按钮，直接请求删评接口返回 `401 authentication_required`。
   - **普通已验证账号**：仅可删除本人发表的账号评论（`204`）；尝试删除访客评论或他人评论均返回 `403 permission_denied`；访问后台管理路径立即返回 `403`（不产生登录重定向死循环）。
   - **站主管理账号（`is_comment_admin=True`）**：既可在任意 `/blog/:slug` 页面逐条删除访客、普通账号与本人的评论，也可通过同一登录态进入自定义路径 Django Admin 跨札记检索、筛选与批量删除全站评论。

---

## 三、技术架构与全链路设计

### 1. 请求与持久化链路

```text
[浏览器 React 19 SPA (SessionProvider + SiteHeader + AccountPanel + NoteComments)]
        │  同源 HTTPS 请求 (Cookie: sessionid, csrftoken + Header: X-CSRFToken)
        ▼
[阿里云全站加速 CDN (Tengine)]
        │  静态资源按规则缓存；动态路径遵循源站 Cache-Control: private, no-store 零缓存回源
        │  注：标准版 CDN 仅透传 GET/POST，故设置页与删评接口均采用 GET/POST 契约
        ▼
[源站 Nginx 1.24 (同源反向代理)]
        ├── /、/blog、/blog/*、/vlog、/awards、/viewer、/static/*  ──► /var/www/wangjinghong (静态构建产物，原子目录切换)
        └── /api/*、/accounts/*、/<admin>/*、/django-static/*
                │  强制响应头 Cache-Control: private, no-store, no-cache, must-revalidate
                ▼
[Gunicorn + Django 5.2 (systemd: wangjinghong-api.service，常驻约 48 MiB RSS)]
        ├── AuthenticationMiddleware + CsrfViewMiddleware (HttpOnly, SameSite=Lax, Secure)
        ├── django-allauth + settings_view (/accounts/settings/) + UnifiedLoginAdminSite
        ├── /api/health/、/api/me/、/api/notes/<slug>/comments/、/api/comments/<id>/delete/
        ├── FileBasedCache 原子限频 + Unicode 控制字符清洗 + note_slugs.json 白名单校验
        └── Django ORM ──► SQLite 3 (WAL 模式 + busy_timeout=5000 + 严格外键、db_default 与 CHECK 约束)
                               └── /var/lib/wangjinghong/db.sqlite3 (独立于静态发布目录持久化)
```

### 2. 关键工程决策

- **同源架构消除跨域复杂度**：本地开发通过 `site/scripts/vite-local-proxy.mjs`（`changeOrigin: false`）将 `/api`、`/accounts`、`/django-static` 与后台前缀转发至本地 Django（并对 `blog`、`vlog`、`awards`、`viewer` 等前端一级路由保留前缀防误劫持）；线上由同一域名下的 Nginx 反代分流。前后端完全同源，无需放宽 CORS 或降低 `SameSite` Cookie 安全策略。
- **CDN 防串号与方法兼容**：动态视图中间件与 Nginx 双重写入 `Cache-Control: private, no-store, no-cache, must-revalidate` 与 `Vary: Cookie`；针对阿里云标准版 CDN 仅允许 `GET/POST` 的约束，账号设置保存采用受 CSRF 保护的 `POST /accounts/settings/`（PRG `302`），删评动作采用 `POST /api/comments/<id>/delete/`（返回 `204 No Content`）。
- **存储型 XSS 与样式注入零信任防护**：前端评论与顶栏昵称仅通过 React 纯文本节点渲染，全程不使用 `dangerouslySetInnerHTML`；头像底色仅允许通过 `/^#[0-9a-f]{6}$/i` 校验的十六进制色值写入 `backgroundColor`，拒绝任意伪造 CSS 字符串注入。
- **静动分离持久化与邮件通道解耦**：前端 `deploy-ecs.yml` 每次仅替换 `/var/www/wangjinghong`；后端代码位于 `/opt/wangjinghong/releases/<id>`，SQLite 数据库、在线热备、文件缓存及备用邮件目录独立存放在 `/var/lib/wangjinghong/`，线上发信凭据独立托管于 `/etc/wangjinghong/server.env`（阿里云邮件推送 `smtpdm.aliyun.com:465` SSL，发信子域 `mail.wangjinghong.com`），静态重发版与后端升级均不会覆盖用户、评论数据或发信配置。

---

## 四、目录结构

```text
site/
├── src/
│   ├── App.tsx                           # 根路由（/、/blog、/blog/:slug、/vlog、/awards、/viewer）、顶栏挂载与跨页滚动复位
│   ├── session/
│   │   └── SessionProvider.tsx           # 全站会话上下文（/api/me/ 拉取、visibilitychange 节流刷新与 syncSession 双向同步）
│   ├── data/
│   │   ├── site.ts                       # 站级共享常量（GITHUB_URL 等）
│   │   ├── avatar.ts                     # 顶栏与评论区共享的首字母字素提取与 avatarColor 十六进制色值校验
│   │   ├── platforms.tsx                 # 博客论坛与项目视频栏目舞台数据及统一标签标题
│   │   └── comments.ts                   # 同源 API 客户端（/api/me/ 与评论 author.avatarColor 校验、分页、发评、删评与草稿存储）
│   ├── components/
│   │   ├── SiteHeader.tsx                # 全站单行固定顶栏（左对齐四栏目导航高亮、首页平滑回顶、GitHub 外链与三种登录态账号区）
│   │   ├── AccountPanel.tsx              # 32px 首字母圆形头像与常驻 DOM 的 WAI-ARIA Disclosure 账号面板
│   │   ├── CommentAvatar.tsx             # 28px 评论者装饰头像组件（成员首字母配色 + 访客人形图标，配 CommentAvatar.css）
│   │   ├── NoteComments.tsx              # 札记评论容器（会话双向同步、游标分页状态机、并发冲突合并重拉）
│   │   ├── NoteCommentComposer.tsx       # 评论发表框（访客/成员身份栏、回跳链接、字数与草稿保护）
│   │   ├── NoteCommentCard.tsx           # 单条评论卡片（左头像右正文两列防溢出网格、纯文本渲染、权限判定与二次确认删评）
│   │   ├── WaterfallGallery.tsx          # 获奖证书瀑布流画廊（携带 state.from 跳转看图页）
│   │   ├── NotesPreview.tsx              # 札记列表卡片组件（支持主页可点击居中标题与栏目页静态标题）
│   │   └── PlatformStage.tsx             # 二级外链平台舞台组件
│   └── pages/
│       ├── Home.tsx                      # 主页长卷（名片粒子首屏、证书画廊与博客论坛居中标题跳转）
│       ├── Awards.tsx                    # 证书画廊独立页（/awards）
│       ├── Blog.tsx                      # 博客论坛列表页（/blog）
│       ├── Note.tsx                      # 札记详情页（/blog/:slug，正文底部挂载评论区）
│       ├── Vlog.tsx                      # 项目视频页（/vlog）
│       └── Viewer.tsx                    # 沉浸式证书查看页（/viewer，隐藏顶栏并按白名单锁存来源页回跳）
├── server/
│   ├── config/                           # Django 配置、urls.py 路由挂载、fail-closed 环境变量解析、no-store 中间件与统一后台
│   ├── accounts/                         # 自定义 User 模型（含 avatar_color）、avatar.py 8 色调色板与首字母提取、settings_view 与 /api/me/
│   ├── comments/                         # Comment 模型、note_slugs.json 白名单、限频器、序列化、读写删视图与 Admin
│   ├── templates/                        # 深色玻璃态认证与设置模板（account/base.html、account/settings.html、login/signup/403 等）
│   └── requirements.txt                  # Python 依赖锁（Django 5.2、django-allauth、gunicorn）
├── deploy/                               # 后端独立发布/回退脚本、SQLite 热备与纯代码回退 schema 校验、Nginx/systemd 模板及沙箱测试
├── scripts/                              # 构建脚本、note_slugs 同步脚本、Vite 同源代理模块（保留 awards 等前端前缀）及 node:test 用例
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

浏览器打开终端输出的本地地址（默认 `http://localhost:5173/` 或 `http://localhost:5173/blog/cc-source-analysis`）：

- **全站顶栏三种状态与 `/awards` 画廊体验**：在首页 `/`、`/blog`、`/vlog`、`/awards` 顶部均可看到统一顶栏（加载态骨架 → 未登录态右侧显示带当前路径 `next` 的「登录」入口）；从首页点击「证书画廊」标题或顶栏导航进入 `/awards`，点开任意证书进入沉浸式 `/viewer`（此时顶栏自动隐藏），翻页后关闭仍准确返回 `/awards`。
- **顶栏登录、账号设置（`/accounts/settings/`）改名选色与退出体验**：在任意页面点击顶栏右上角「登录」，使用上一步创建的 `admin@local.test` 登录后自动回跳原页面，顶栏右侧切换为 32px 首字母圆形头像；悬停或点击头像展开面板，点击「设置」进入 `/accounts/settings/` 修改公开昵称并从「自动 + 8 种深色调色板」中选择头像底色，保存后顶部出现「已保存」toast，点击「← 返回原页面」，可见顶栏头像首字母与底色、评论框身份栏及该账号全部历史评论署名即时同步更新，历史评论的头像底色随之同步；再次展开面板点击「退出登录」（`POST /accounts/logout/`）即可回到原页面并恢复未登录「登录」状态。
- **访客直发体验**：未登录状态下在 `/blog/cc-source-analysis` 底部评论框输入内容点击「发表评论」，即可看到以「未登录用户」身份写入 SQLite 并即时展示；重启 `runserver` 后刷新页面评论依然存在。
- **自助注册与本地验证信查看**：点击登录页或评论区「注册」提交邮箱、公开昵称与密码后，验证邮件会自动写入 `site/server/var/mail/` 目录；打开最新邮件文件中的 `http://localhost:5173/accounts/confirm-email/.../` 链接确认后自动跳回登录页并显示「邮箱已确认，请登录。」toast，登录后即可回跳原页面署名发言并删除本人评论。
- **站主全站管理体验**：使用 `admin@local.test` 登录后，可在任意札记页逐条删除访客或成员评论，也可访问 `http://localhost:5173/admin/` 进入后台跨札记检索管理。
- **测试暂停访客发言开关**：以 `ALLOW_GUEST_COMMENTS=false .venv/bin/python server/manage.py runserver 127.0.0.1:8000` 重启后端，刷新页面可见未登录访客提交被禁用且草稿保留，登录账号仍可正常发表评论。

---

## 六、自动化检查与测试命令

在 `site/` 目录下可执行以下完整验证套件：

```bash
# 1. 前端静态检查、类型检查、组件单元测试与生产构建
npm run lint
npm run type-check
npx vitest run
npm run build

# 2. 后端 Django 配置检查、迁移一致性校验与单元/集成测试
.venv/bin/python server/manage.py check
.venv/bin/python server/manage.py makemigrations --check --dry-run
.venv/bin/python server/manage.py test --verbosity 2

# 3. 札记 slug 同步、本地同源代理与后端发布/纯代码回退沙箱全量回归
node --test scripts/*.test.mjs
python3 -m unittest discover -s deploy/tests -t .
```

---

## 七、线上部署与公网实测验收记录

### 1. 部署方式概要

- **静态前端**：合入 `main` 分支后由 `.github/workflows/deploy-ecs.yml` 自动构建 `site/dist` 并原子切换至源站 `/var/www/wangjinghong`。
- **动态后端**：通过 `DEPLOY_HOST=<ECS_HOST> bash site/deploy/publish-server.sh deploy` 独立打包 `site/server/` 发布至 `/opt/wangjinghong/releases/<release_id>`，自动执行 SQLite 热备、非破坏性迁移校验、`collectstatic`、systemd 重启与回环健康探针检查；异常时支持 `publish-server.sh rollback` 一键回退代码与迁移前数据库快照。
- **生产邮件投递**：因主域名 CNAME 指向阿里云 CDN，线上单独以子域名 `mail.wangjinghong.com` 在腾讯云 DNSPod 配置 SPF、DKIM、DMARC 与 MX 记录，由源站 `/etc/wangjinghong/server.env` 通过阿里云邮件推送 `smtpdm.aliyun.com:465`（SSL，发件地址 `noreply@mail.wangjinghong.com`）真实外发注册验证链接与密码重置邮件。

### 2. 公网端到端与持久化验收证据（2026-11-24 UTC）

在正式域名 `https://www.wangjinghong.com`（经阿里云全站加速 CDN 回源至上海地域 2C2G ECS）已完成以下实测：

1. **三独立会话防串号实测**：使用站主会话 A、公网自助注册并完成文件邮件确认的普通账号会话 B、未登录访客会话 C 按 `A → B → C → A → C → B` 交替请求 `/api/me/`，6 次响应均返回 `200`、`Cache-Control: private, no-store, no-cache, must-revalidate`、`x-swift-cachetime: 0`、`x-cache: MISS TCP_MISS`，零身份串号。
2. **权限矩阵与 CDN `POST` 删评实测**：公网实测访客发评（`201`）与普通账号发评（`201`）后，经 CDN 调用 `POST /api/comments/<id>/delete/`：访客返回 `401`、普通账号删访客评论返回 `403`、普通账号删本人评论返回 `204`、站主账号删访客评论返回 `204`；后台自定义管理入口对站主返回 `200`、普通账号返回 `403`、未登录访客 `302` 跳转统一登录页。
3. **`ALLOW_GUEST_COMMENTS` 在线切换实测**：将源站配置切为 `false` 重启服务后，公网 `/api/me/` 即时返回 `guestCommentsAllowed=false`，访客发评返回 `403 guest_comments_disabled`，普通登录账号发评仍返回 `201`；测试后已恢复为 `true`。
4. **跨进程重启与跨版本发布持久化回读实测**：
   - 前端构建产物 `/static/Note-D9WIIhg5.js` 上线后，于 `2026-11-24T11:10:36.202247Z` 经公网在札记 `/blog/cc-source-analysis` 发表持久化验证评论（返回 `id=7`）；
   - 随后依次执行 `systemctl restart wangjinghong-api` 进程重启，以及运行 `publish-server.sh deploy` 切换全新后端发布目录 `20261124T111034Z-b7cd2603`；
   - 使用全新匿名会话请求 `https://www.wangjinghong.com/api/notes/cc-source-analysis/comments/`，准确读回同一条 `id=7`（`createdAt="2026-11-24T11:10:36.202247Z"`）记录；确认持久化无误后，由站主会话执行 `POST /api/comments/7/delete/`（`204`）清理验收测试评论，保持线上公开札记整洁。

### 3. 生产阿里云邮件推送 SMTP 切换与真实收信验证（2026-11-25 UTC）

完成子域名 `mail.wangjinghong.com` 的 SPF、DKIM（1024 位 RSA）、DMARC 与 MX 权威解析核验后，在不改动任何业务代码的情况下将源站 `/etc/wangjinghong/server.env` 切换为 `django.core.mail.backends.smtp.EmailBackend`（`smtpdm.aliyun.com:465` SSL，发件人 `wangjinghong.com <noreply@mail.wangjinghong.com>`）并重启 `wangjinghong-api`；经真实邮箱公网注册实测，验证链接邮件已正常送达。

### 4. 全站顶栏、证书画廊独立页与账号设置分阶段上线验收（2026-11-25 UTC）

按「先前端 `/awards` 与全站顶栏基础态 → 再后端 `/accounts/settings/` 与 `0004_user_avatar_color` 迁移发布 → 最后前端开放顶栏设置入口与 `avatarColor` 配色」的零断链顺序完成线上演进与公网核验：

1. **全站导航、标题规范与 `/awards` 回跳核验**：公网直链与刷新 `/awards` 返回 `200`，375px 窄屏双行顶栏无横向溢出，主页首屏透明顶栏与长卷 `sticky` 窗帘无回归，从 `/awards` 进入 `/viewer` 翻页后关闭准确返回 `/awards`，全站前后端页面 `<title>` 均统一为 `王景宏 · …`。
2. **账号设置、8 色调色板与无损迁移核验**：经 `publish-server.sh deploy` 在线备份 SQLite 并执行 `0004_user_avatar_color` 迁移后，线上既有账号与历史评论记录完整保留；多独立会话在 `/accounts/settings/` 分别修改公开昵称与预设底色后，`/api/me/` 响应维持 `private, no-store` 零 CDN 串号，顶栏首字母头像、底色及历史评论署名即时同步，验收后测试账号均已恢复原状态。
3. **顶栏改为单行（2026-11-26 UTC）**：全视口统一为单行 `56px` 顶栏，移除独立站名并将「首页」并入左侧四栏目统一导航（`≤ 560px` 压缩导航与操作区尺寸、`≤ 359px` 隐藏顶栏 GitHub 图标）。
4. **账号页纯文字 toast、首屏去滚动提示与常驻滚动条打磨（2026-11-26 UTC）**：账号页操作反馈收敛为纯文字 toast（修复淡出动画点击穿透并统一桌面与 `≤ 480px` 窄屏顶部留白 `4.25rem` 防遮挡页眉），移除首页首屏底部「滚动认识我」提示，并在 `html` 根节点启用 `overflow-y: scroll` 与 `overflow-x: hidden` 消除长短页切换时的横向跳动（线上实测 `/`、`/blog`、`/vlog`、`/awards` 视口 `clientWidth` 恒定零跳动且首页 `sticky` 窗帘无回归）。
