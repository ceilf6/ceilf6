# AI使用声明

> 本文件依据《Internet应用开发》（23306046）教师《AI使用声明（模板）》填写。因本仓库根目录 `README.md` 承担 GitHub 个人主页展示，网站工程根目录位于 `site/`，故公开仓库声明置于 `site/AI_USAGE.md`；提交课程云盘时将同步附上填写本人学号并经本人核对签字的版本。
>
> 课程原则：**可用AI、须声明、能解释**。未声明或声明不实，一经查实按学术不端处理。

## 一、基本信息

| 项目 | 内容 |
| --- | --- |
| 作业名称 | 作业1（动态网站：wangjinghong.com 登录、身份与评论系统） |
| 学号 | 见课程云盘随作业提交的 `AI_USAGE.md`；公开仓库不展示学号 |
| 姓名 | 王景宏 |
| 提交日期 | |

## 二、总体声明

以下两项请勾选且仅勾选一项：

- [ ] 本次作业我**未使用**任何AI工具。
- [ ] 本次作业我**使用了**AI工具，已在下方如实、完整声明，并能解释所提交的代码与设计。

## 三、所用AI工具清单

若勾选"未使用"，本节可留空。

| 工具名称 | 提供方/来源 | 用途概述 |
| --- | --- | --- |
| Antigravity (`Gemini 4 Carbon` / 内置订阅 `Claude Opus 5.5`) | Google DeepMind（含内置跨厂商模型订阅） | 使用 `Gemini 4 Carbon` 按分步计划执行前后端模块初稿编写、单元/集成测试与本地/公网联调验证，并通过同一账号内置订阅调用异构模型 `Claude Opus 5.5` 执行跨厂商独立代码审查（CR） |
| Claude Code | Anthropic | 前期线上建站与部署上下文梳理、全站顶栏与账号设置增量实施方案多轮评审收敛、生产邮件外发排查与 DNS/SMTP 配置核验 |
| Repo Guard (Codex) | OpenAI / GitHub Actions (`ceilf6/repo-guard`) | 针对每个 Issue 与 Pull Request 自动执行开放式代码审查、级联风险分析与边界缺陷排查 |

## 四、使用明细

请对每个主要使用AI辅助的环节填写一行；如某模块完全由AI生成初稿，务必注明。

| 对应模块/文件 | 用途（解决了什么问题） | 提示词或交互要点 | 采用程度 |
| --- | --- | --- | --- |
| `site/server/config/`（`settings.py`、`env.py`、`middleware.py`、`http.py`、`wsgi.py`） | 搭建 Django 5.2 + SQLite WAL 后端骨架、生产环境 fail-closed 配置校验、动态路由 `Cache-Control: private, no-store` 防 CDN 缓存串号及 `.maintenance` 维护屏障（AI 生成初稿） | 指定 2C2G 服务器内存约束、同源 Cookie/CSRF 模型与阿里云 CDN 禁缓存头要求，审查修正反代头与维护态探针放行逻辑 | 修改后采用 |
| `site/server/accounts/`、`site/server/templates/` | 实现邮箱 + 密码 + 公开昵称注册、邮件验证链接确认（本地默认 `filebased.EmailBackend` 零外部密钥落盘，同时预留生产加密 SMTP 后端）、统一登录入口（收拢自定义后台路由并拦截开放重定向）、站主授权命令与 `GET /api/me/` 接口（AI 生成初稿） | 要求登录邮箱绝不对外暴露、内部 `username` 使用不透明标识、普通登录用户访问后台返回 `403` 而非循环跳转 | 修改后采用 |
| `site/server/comments/` | 实现支持 `author=NULL`（未登录访客）与已验证账号的评论模型、构建期 `note_slugs.json` 白名单同步、`before` 游标分页、文件缓存原子限频、`ALLOW_GUEST_COMMENTS` 开关、兼容标准版 CDN 的 `POST /api/comments/<id>/delete/` 删评及后台全站审核（AI 生成初稿） | 明确阿里云标准版 CDN 仅透传 `GET/POST`，要求服务端完全按会话判定署名与删评权限（访客评论显示「未登录用户」，站主可跨札记管理任意评论） | 修改后采用 |
| `site/deploy/`（`publish-server.sh`、`remote_server.py`、`sqlite_ops.py`、`nginx-wangjinghong.conf` 等） | 实现独立于 `/var/www/wangjinghong` 静态目录的后端版本化发布、SQLite 在线热备、破坏性迁移拦截、自动回退及 Nginx 同源反代配置与沙箱单测（AI 生成初稿） | 要求数据库固定在 `/var/lib/wangjinghong/` 不受静态重发版影响，按 CR 反馈补齐 `O_NOFOLLOW` 路径防护与进程隔离的 canonical DDL 对账 | 修改后采用 |
| `site/scripts/vite-local-proxy.*`、`site/vite.config.ts` | 配置本地 `vite` 与 `vite preview` 同源后端代理，保持 `changeOrigin: false` 对齐浏览器 `Origin` 与后端 `Host`（AI 生成初稿） | 要求段边界匹配不误劫持相邻前端路由、联动读取 `site/server/.env` 的后台前缀，并补齐回环代理集成测试 | 修改后采用 |
| `site/src/data/comments.ts`、`site/src/components/NoteComment*.tsx`、`site/src/pages/Note.tsx` | 实现札记详情页底部评论列表与游标分页、纯文本防 XSS 渲染、访客直发与成员发评、`sessionStorage` 按札记草稿保留、跨标签页 `409`/`403 csrf_failed` 自动同步及行内二次确认删评（AI 生成初稿） | 首期接入评论区时聚焦 `/blog/:slug` 底部挂载并保持仓库根目录统计卡片流水线零改动，按多轮 CR 修正切页首帧重复请求、分页合并、并发 `/api/me/` 重拉与非 `comment_not_found` 的 404 防误删 | 修改后采用 |
| `site/deploy/README.md`、`site/server/.env.example`（生产发信排查与运维配置） | 协助定位线上注册未收到验证邮件的根因（原生产配置仍为 `filebased.EmailBackend` 本地落盘），核对 `mail.wangjinghong.com` 子域 SPF/DKIM/DMARC/MX 解析并切换源站 `server.env` 至阿里云邮件推送 `smtpdm.aliyun.com:465` SSL（云服务开通与 DNS 记录由本人人工配置） | 排查主域名 CDN CNAME 同名记录冲突后改用独立子域发信，保持验证链接机制不改动业务代码，真实收信确认后再同步文档 | 修改后采用 |
| `site/src/pages/Awards.*`、`site/src/pages/Home.tsx`、`site/src/pages/Viewer.tsx`、`site/src/pages/Note.tsx`、`site/src/data/platforms.tsx`、`site/src/App.tsx`、`site/scripts/vite-local-proxy.mjs` | 新增证书画廊独立页 `/awards`、主页「证书画廊」「博客论坛」两节居中标题跳转、`AnimatePresence` 跨页滚动复位、看图页 `/viewer` 来源白名单锁存回跳、本地代理 `awards` 前缀保护及全站统一的 `王景宏 · …` 浏览器标签标题规范（AI 生成初稿） | 要求保持主页长卷 `sticky` 窗帘与入场编排不回归、居中标题不附加右侧箭头、上下翻页 `replace` 保留 `history.state.from`、测试环境补齐 `window.scrollTo` 桩消除 jsdom 告警 | 修改后采用 |
| `site/src/session/SessionProvider.*`、`site/src/components/SiteHeader.*`、`site/src/components/AccountPanel.*`、`site/src/components/NoteComments.tsx`、`site/src/data/comments.ts`、`site/src/data/site.ts` | 实现全站固定顶栏（`/viewer`、`/viewer.html` 除外）、三种登录态展示、32px 首字母圆形头像与常驻 DOM 的 WAI-ARIA Disclosure 账号面板、`avatarColor` 十六进制安全校验与金底深字兜底，以及顶栏与札记评论区的双向会话身份同步（AI 生成初稿） | 指定 `#account-panel[hidden] { display: none !important; }` 防作者样式覆盖、375px 窄屏两行无横向溢出；按跨厂商独立 CR 反馈补齐 `SessionProvider` 后台切回前台刷新向 `NoteComments` 的双向同步，并对齐前端回退首字母提取对 Unicode `Mc` 间距组合符的支持 | 修改后采用 |
| `site/server/accounts/avatar.py`、`site/server/accounts/forms.py`、`site/server/accounts/views.py`、`site/server/accounts/models.py`、`site/server/accounts/migrations/0004_user_avatar_color.py`、`site/server/config/urls.py`、`site/server/templates/account/base.html`、`site/server/templates/account/settings.html`、`site/deploy/tests/` | 实现受登录保护的账号设置页 `GET/POST /accounts/settings/`（公开昵称校验、PRG 保存、按列 `update_fields` 写入、未变零 `UPDATE`、站内 `next` 回跳校验）、「自动 + 8 种 WCAG AA 深色」头像调色板、无 JS 服务端首字母预览、`GET /api/me/` 输出 `avatarColor`，以及 `db_default=""` 纯代码回退兼容迁移与沙箱测试（AI 生成初稿） | 要求不做图片上传收敛攻击面、`User.avatar_color` 声明 `db_default=""` 通过 `sqlite_ops.py` 纯代码回退门禁；按跨厂商独立 CR 反馈在 `settings.html` 静默消费 Django `messages` 队列防登录提示残留或泄露确认邮箱，统一 `Mc` 间距组合符与多段 ZWJ Emoji 首字母提取并泛化回退沙箱测试迁移编号 | 修改后采用 |
| `site/README.md`、`site/AI_USAGE.md` | 编写并同步更新课程作业 1 架构说明、全站顶栏与账号设置业务规则（含改名同步历史评论署名）、零密钥干净环境复现指南、真实联调验收记录及本 AI 使用声明（AI 生成初稿） | 严格区分既有静态站点基线与本次作业新增范围，在临时干净目录从零执行文档命令复现顶栏三态、设置页改名选色与退出闭环，保留本人复核勾选与手写签名项为空 | 修改后采用 |
| `site/server/accounts/adapter.py`、`site/server/accounts/context_processors.py`、`site/server/accounts/forms.py`、`site/server/accounts/views.py`、`site/server/config/settings.py`、`site/server/config/urls.py`、`site/server/templates/account/` | 将账号页操作反馈改为视口顶部独立 toast、源头屏蔽登录/退出/确认邮件冗余或含邮箱提示、重设密码完成直跳登录页并统一提示文案、修正空昵称老账号设置页初始值与占位符（AI 生成初稿） | 指定 toast 挂载于 `.auth-card` 之外避开 `backdrop-filter` 固定定位陷阱，`prefers-reduced-motion` 使用 `step-end` 关键帧隐藏；按跨厂商独立 CR 反馈将 `account_feedback` 改为 `SimpleLazyObject` 惰性求值防止邮件模板渲染提前消费消息，并拦截确认邮箱冲突失败误跳 `?confirmed=1` | 修改后采用 |
| `site/src/session/SessionProvider.*` | 优化顶栏后台会话刷新容错：首次加载失败仍降级显示「登录」，已获取或 `syncSession` 同步过会话后若后台刷新遭遇网络波动/`5xx`/格式异常则保留已登录状态与头像，真实登出返回 `user: null` 正常切回「登录」（AI 生成初稿） | 要求将 `lastFetchedAtRef` 初值改为 `0` 避免断网恢复后被 10 秒节流拦截，并在 `refresh` 成功与 `syncSession` 两处同步置位 `hasReadySessionRef` | 修改后采用 |
| `site/src/components/SiteHeader.*`、`site/src/styles/global.css` | 将全站顶栏统一为单行 `56px` 固定高度，移除独立品牌字并将「首页」并入左侧四栏目统一导航，补充 `≤ 560px` 与 `≤ 359px` 窄屏防溢出压缩及 `text-size-adjust: 100%`（AI 生成初稿） | 保持首页点击平滑回顶与修饰键放行逻辑，基础规则保证导航点击高度 `>= 32px`，并在 `1280px`–`320px` 多档视口实测零横向溢出 | 修改后采用 |
| `site/server/comments/serializers.py`、`site/server/comments/views.py`、`site/src/data/avatar.*`、`site/src/data/comments.*`、`site/src/components/CommentAvatar.*`、`site/src/components/AccountPanel.*`、`site/src/components/NoteCommentCard.tsx`、`site/src/components/NoteComments.css` | 在评论查询/发表接口返回 `author.avatarColor`（成员 `#RRGGBB`、访客 `null`）并在 `.only()` 补齐字段防 N+1；前端抽离共享 `avatar.ts`，新增 `28px` `CommentAvatar`（成员首字母配色、访客灰色人形图标、非法色值回退兜底）与评论卡两列防溢出网格（AI 生成初稿） | 使用 `assertNumQueries` 锁定 20 条成员评论列表查询次数不增加，右列声明 `min-width: 0` 防止长无空格网址撑破窄屏布局，并同步更新 `site/README.md` 与本声明（学号、勾选框与签名留空） | 修改后采用 |

"采用程度"取其一：直接采用 / 修改后采用 / 仅作参考。

## 五、可解释性确认

- [ ] 我能说明本作业的整体设计、各模块作用与关键代码的实现思路；
- [ ] 教师抽查答辩时，我能复现并回答与AI生成内容相关的问题。

本人确认以上声明真实、准确。

学号/姓名：＿＿＿＿＿＿＿＿　日期：＿＿＿＿＿＿＿＿
