# Linux DO 每日签名同步设计

## 目标

在现有 GitHub 贡献图工作流生成 `assets/github-contribution-graph-compact.svg` 后，将该 SVG 上传到 linux.do，并将用户 `ceilf6` 的图片签名更新为上传返回的 CDN URL。

一次成功同步只会在 linux.do 产生两次写操作：一次图片上传、一次用户资料更新。同步每天最多执行一次，并且仅在紧凑 SVG 的内容发生变化时执行。

## 非目标

- 不发帖、回复、私信、点赞或变更其他用户资料。
- 不绕过 linux.do 的外站图片白名单，也不使用嵌套外站资源的 SVG。
- 不在仓库、提交记录或 Actions 日志中保存 Cookie、CSRF token 或完整 API 响应。
- 不自动重试失败的 linux.do 请求。

## 已确认的站点行为

linux.do 使用 Discourse Signatures 插件。该插件把图片签名保存为用户 `custom_fields.signature_url`；Discourse 的个人资料页保存请求为 `PUT /u/:username.json`，其中允许更新 `custom_fields`。图片上传使用 `POST /uploads.json`，并返回 CDN 图片 URL。

## 组件与数据流

```text
GitHub contribution data
        |
        v
generate-github-contribution-graph.py
        |
        v
assets/github-contribution-graph-compact.svg
        |
        | (only if Git diff detects a change)
        v
sync-linuxdo-signature.py
  GET  linux.do/session/csrf.json
  POST linux.do/uploads.json
  PUT  linux.do/u/ceilf6.json
        |
        v
linux.do CDN SVG URL stored as signature_url
```

### 同步脚本

新增 `scripts/sync-linuxdo-signature.py`，只接受以下运行时输入：

- `--image`：待上传的本地 SVG 路径。
- `--username`：目标 linux.do 用户名；工作流固定为 `ceilf6`。
- `LINUXDO_SESSION_COOKIE`：GitHub Actions Secret 提供的完整 Cookie header 值。

脚本按以下顺序执行：

1. 验证输入文件存在、扩展名为 `.svg` 且 Cookie 非空。
2. 以 Cookie 请求 `https://linux.do/session/csrf.json`，读取 CSRF token。
3. 以 `upload_type=composer` 和 `synchronous=true` 上传 SVG 到 `https://linux.do/uploads.json`。
4. 验证响应 URL 是 HTTPS 且主机严格为 `cdn3.ldstatic.com`，扩展名为 `.svg`。
5. 请求 `PUT https://linux.do/u/ceilf6.json`，只提交 `custom_fields[signature_url]`。
6. 仅在资料更新成功后输出不含敏感信息的成功摘要。

脚本不读取、不打印或修改当前签名以外的用户资料字段。所有 HTTP 请求设定短超时；任一非成功响应、缺失字段或 URL 校验失败都立即以非零状态退出。上传成功而资料更新失败时停止，不重试，也不改变当前签名。

### 工作流集成

在 `.github/workflows/update-github-contribution-graph.yml` 中，图表生成后、Git 提交前增加同步步骤：

- 使用 `git diff --quiet -- assets/github-contribution-graph-compact.svg` 跳过无变化同步。
- 仅在 `LINUXDO_SESSION_COOKIE` 已配置时运行；缺失时在工作流摘要中标示为未配置，而非伪造同步成功。
- 将 Cookie 作为环境变量传给脚本；不启用 shell tracing，且不输出 HTTP 响应内容。
- 不增加新的第三方依赖：工作流已经安装 `requests`，同步脚本复用它。

## 安全与运维

- `LINUXDO_SESSION_COOKIE` 只能配置为 GitHub Actions Secret，绝不写入 `.env`、代码、测试 fixture 或 workflow 输出。
- Cookie 等同于登录态。能修改默认分支工作流的协作者也可能令其外泄，因此必须限制仓库写权限；Cookie 过期或发现异常后立即在 linux.do 退出该会话并更换 Secret。
- 工作流不试图绕过 Cloudflare、验证码、403 或 429。遇到这些响应会失败并等待人工介入。
- 部署后首个真实请求必须由用户在 Actions 运行前确认。部署脚本和测试本身不向 linux.do 发出写请求。

## 测试与验收

新增离线单元测试，mock HTTP 会话并覆盖：

1. CSRF 获取、SVG 上传和签名更新的成功顺序与请求载荷。
2. 缺少 Cookie 或输入 SVG 时不产生网络请求。
3. CSRF、上传或资料更新的非 2xx 响应会失败且不会重试。
4. 上传响应缺少 URL、URL 非 HTTPS、非 `cdn3.ldstatic.com` 或非 SVG 时，不更新个人资料。

验收条件：

- 现有贡献图生成测试和新增同步单元测试均通过。
- 未配置 Secret 时，现有图表生成与提交行为不受影响，且不会触达 linux.do。
- 配置有效 Secret 且用户确认真实运行后，手动触发工作流能将签名替换为一个 `cdn3.ldstatic.com` SVG URL；后续定时运行遵循相同限制。
