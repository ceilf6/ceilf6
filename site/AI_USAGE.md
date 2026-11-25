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
| Antigravity (Gemini) | Google DeepMind | 按分步计划执行前后端模块初稿编写、单元测试与本地/公网联调验证，并组织独立子代理代码审查 |
| Claude Code | Anthropic | 前期线上建站与部署上下文梳理、技术架构对比与实施步骤拆解、生产邮件外发排查与 DNS/SMTP 配置核验 |
| Repo Guard (Codex) | OpenAI / GitHub Actions (`ceilf6/repo-guard`) | 针对每个 Pull Request 自动执行开放式代码审查、级联风险分析与边界缺陷排查 |

## 四、使用明细

请对每个主要使用AI辅助的环节填写一行；如某模块完全由AI生成初稿，务必注明。

| 对应模块/文件 | 用途（解决了什么问题） | 提示词或交互要点 | 采用程度 |
| --- | --- | --- | --- |
| `site/server/config/`（`settings.py`、`env.py`、`middleware.py`、`http.py`、`wsgi.py`） | 搭建 Django 5.2 + SQLite WAL 后端骨架、生产环境 fail-closed 配置校验、动态路由 `Cache-Control: private, no-store` 防 CDN 缓存串号及 `.maintenance` 维护屏障（AI 生成初稿） | 指定 2C2G 服务器内存约束、同源 Cookie/CSRF 模型与阿里云 CDN 禁缓存头要求，审查修正反代头与维护态探针放行逻辑 | 修改后采用 |
| `site/server/accounts/`、`site/server/templates/` | 实现邮箱 + 密码 + 公开昵称注册、邮件验证链接确认（本地默认 `filebased.EmailBackend` 零外部密钥落盘，同时预留生产加密 SMTP 后端）、统一登录入口（收拢自定义后台路由并拦截开放重定向）、站主授权命令与 `GET /api/me/` 接口（AI 生成初稿） | 要求登录邮箱绝不对外暴露、内部 `username` 使用不透明标识、普通登录用户访问后台返回 `403` 而非循环跳转 | 修改后采用 |
| `site/server/comments/` | 实现支持 `author=NULL`（未登录访客）与已验证账号的评论模型、构建期 `note_slugs.json` 白名单同步、`before` 游标分页、文件缓存原子限频、`ALLOW_GUEST_COMMENTS` 开关、兼容标准版 CDN 的 `POST /api/comments/<id>/delete/` 删评及后台全站审核（AI 生成初稿） | 明确阿里云标准版 CDN 仅透传 `GET/POST`，要求服务端完全按会话判定署名与删评权限（访客评论显示「未登录用户」，站主可跨札记管理任意评论） | 修改后采用 |
| `site/deploy/`（`publish-server.sh`、`remote_server.py`、`sqlite_ops.py`、`nginx-wangjinghong.conf` 等） | 实现独立于 `/var/www/wangjinghong` 静态目录的后端版本化发布、SQLite 在线热备、破坏性迁移拦截、自动回退及 Nginx 同源反代配置与沙箱单测（AI 生成初稿） | 要求数据库固定在 `/var/lib/wangjinghong/` 不受静态重发版影响，按 CR 反馈补齐 `O_NOFOLLOW` 路径防护与进程隔离的 canonical DDL 对账 | 修改后采用 |
| `site/scripts/vite-local-proxy.*`、`site/vite.config.ts` | 配置本地 `vite` 与 `vite preview` 同源后端代理，保持 `changeOrigin: false` 对齐浏览器 `Origin` 与后端 `Host`（AI 生成初稿） | 要求段边界匹配不误劫持相邻前端路由、联动读取 `site/server/.env` 的后台前缀，并补齐回环代理集成测试 | 修改后采用 |
| `site/src/data/comments.ts`、`site/src/components/NoteComment*.tsx`、`site/src/pages/Note.tsx` | 实现札记详情页底部评论列表与游标分页、纯文本防 XSS 渲染、访客直发与成员发评、`sessionStorage` 按札记草稿保留、跨标签页 `409`/`403 csrf_failed` 自动同步及行内二次确认删评（AI 生成初稿） | 要求不改动首页/列表/画廊/统计卡片等既有页面，按多轮 CR 修正切页首帧重复请求、分页合并、并发 `/api/me/` 重拉与非 `comment_not_found` 的 404 防误删 | 修改后采用 |
| `site/deploy/README.md`、`site/server/.env.example`（生产发信排查与运维配置） | 协助定位线上注册未收到验证邮件的根因（原生产配置仍为 `filebased.EmailBackend` 本地落盘），核对 `mail.wangjinghong.com` 子域 SPF/DKIM/DMARC/MX 解析并切换源站 `server.env` 至阿里云邮件推送 `smtpdm.aliyun.com:465` SSL（云服务开通与 DNS 记录由本人人工配置） | 排查主域名 CDN CNAME 与 TXT 记录冲突后改用独立子域发信，保持验证链接机制不改动业务代码，真实收信确认后再同步文档 | 修改后采用 |
| `site/README.md`、`site/AI_USAGE.md` | 编写课程作业 1 架构说明、零密钥干净环境复现指南、真实联调与发信验收记录及本 AI 使用声明（AI 生成初稿） | 严格区分既有静态站点基线与本次作业新增动态范围，逐条在干净目录实测启动命令，保留本人复核勾选与手写签名项为空 | 修改后采用 |

"采用程度"取其一：直接采用 / 修改后采用 / 仅作参考。

## 五、可解释性确认

- [ ] 我能说明本作业的整体设计、各模块作用与关键代码的实现思路；
- [ ] 教师抽查答辩时，我能复现并回答与AI生成内容相关的问题。

本人确认以上声明真实、准确。

学号/姓名：＿＿＿＿＿＿＿＿　日期：＿＿＿＿＿＿＿＿
