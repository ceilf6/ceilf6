# Linux DO 签名同步 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 自动将每日生成的紧凑 GitHub 贡献图上传到 linux.do，并只更新 ceilf6 的图片签名 URL。

**Architecture:** 一个 Python CLI 串行执行 CSRF 获取、SVG multipart 上传、CDN URL 校验及单个用户 custom field 更新。工作流先独立完成图表提交，再依据变更状态和 Secret 配置决定是否调用该 CLI。Node 的本地 HTTP 服务驱动 CLI 测试，不会请求 linux.do。

**Tech Stack:** Python 3.11、`requests`、Node 22 `node:test`、GitHub Actions。

---

## 文件结构

- Create: `scripts/sync-linuxdo-signature.py` — 受限的 linux.do 签名同步 CLI。
- Create: `tests/linuxdo-signature-sync.test.mjs` — CLI 的本地 HTTP 集成测试。
- Modify: `.github/workflows/update-github-contribution-graph.yml` — 仅在图表变更且 Secret 已配置时调用 CLI。
- Modify: `.github/workflows/verify.yml` — 为 CLI 集成测试提供 Python 和 `requests`。

### Task 1: 用 localhost 测试定义同步协议

**Files:**
- Create: `tests/linuxdo-signature-sync.test.mjs`
- Create later: `scripts/sync-linuxdo-signature.py`

- [ ] **Step 1: 写入失败的成功路径测试**

```js
import assert from "node:assert/strict";
import { execFileSync, spawnSync } from "node:child_process";
import { createServer } from "node:http";
import { mkdtempSync, readFileSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import test from "node:test";

const root = new URL("../", import.meta.url);
const script = new URL("../scripts/sync-linuxdo-signature.py", import.meta.url);

function serve(t, handler) {
  const server = createServer(handler);
  return new Promise((resolve) => server.listen(0, "127.0.0.1", () => {
    t.after(() => server.close());
    resolve(`http://127.0.0.1:${server.address().port}`);
  }));
}

function image() {
  const path = join(mkdtempSync(join(tmpdir(), "linuxdo-sync-")), "graph.svg");
  writeFileSync(path, "<svg />");
  return path;
}

function sync(path, baseUrl, cookie = "_forum_session=test") {
  return execFileSync("python3", [script.pathname, "--image", path, "--username", "ceilf6", "--base-url", baseUrl], {
    cwd: root,
    encoding: "utf8",
    env: { ...process.env, LINUXDO_SESSION_COOKIE: cookie },
  });
}

function syncResult(path, baseUrl, cookie = "_forum_session=test") {
  return spawnSync("python3", [script.pathname, "--image", path, "--username", "ceilf6", "--base-url", baseUrl], {
    cwd: root,
    encoding: "utf8",
    env: { ...process.env, LINUXDO_SESSION_COOKIE: cookie },
  });
}

test("sync performs CSRF, upload, then signature-only update", async (t) => {
  const seen = [];
  const baseUrl = await serve(t, (request, response) => {
    let body = "";
    request.setEncoding("utf8");
    request.on("data", (chunk) => (body += chunk));
    request.on("end", () => {
      seen.push({ method: request.method, url: request.url, headers: request.headers, body });
      response.setHeader("content-type", "application/json");
      if (request.url === "/session/csrf.json") response.end(JSON.stringify({ csrf: "csrf-token" }));
      else if (request.url === "/uploads.json") response.end(JSON.stringify({ url: "https://cdn3.ldstatic.com/original/4X/a/b/c/graph.svg" }));
      else if (request.url === "/u/ceilf6.json") response.end(JSON.stringify({ success: "OK" }));
      else { response.statusCode = 404; response.end("{}"); }
    });
  });

  assert.match(sync(image(), baseUrl), /Linux DO signature updated/);
  assert.deepEqual(seen.map(({ method, url }) => [method, url]), [
    ["GET", "/session/csrf.json"], ["POST", "/uploads.json"], ["PUT", "/u/ceilf6.json"],
  ]);
  assert.equal(seen[0].headers.cookie, "_forum_session=test");
  assert.equal(seen[1].headers["x-csrf-token"], "csrf-token");
  assert.match(seen[1].body, /name="upload_type"\r\n\r\ncomposer/);
  assert.match(seen[2].body, /custom_fields%5Bsignature_url%5D=/);
});

test("sync rejects an untrusted upload URL without profile update", async (t) => {
  const seen = [];
  const baseUrl = await serve(t, (request, response) => {
    seen.push([request.method, request.url]);
    response.setHeader("content-type", "application/json");
    response.end(request.url === "/session/csrf.json" ? JSON.stringify({ csrf: "csrf-token" }) : JSON.stringify({ url: "https://example.invalid/graph.svg" }));
  });
  const result = syncResult(image(), baseUrl);
  assert.notEqual(result.status, 0);
  assert.match(result.stderr, /not an allowed Linux DO SVG URL/);
  assert.deepEqual(seen, [["GET", "/session/csrf.json"], ["POST", "/uploads.json"]]);
});

test("sync rejects an empty Cookie before any network request", () => {
  const result = syncResult(image(), "http://127.0.0.1:9", "");
  assert.notEqual(result.status, 0);
  assert.match(result.stderr, /LINUXDO_SESSION_COOKIE is required/);
});

test("sync stops after one HTTP failure without retrying", async (t) => {
  const seen = [];
  const baseUrl = await serve(t, (request, response) => {
    seen.push([request.method, request.url]);
    response.statusCode = 403;
    response.setHeader("content-type", "application/json");
    response.end(JSON.stringify({ error: "forbidden" }));
  });
  const result = syncResult(image(), baseUrl);
  assert.notEqual(result.status, 0);
  assert.match(result.stderr, /CSRF request failed with HTTP 403/);
  assert.deepEqual(seen, [["GET", "/session/csrf.json"]]);
});
```

- [ ] **Step 2: 运行测试，确认因 CLI 尚不存在而失败**

Run: `node --test tests/linuxdo-signature-sync.test.mjs`

Expected: FAIL，Python 报告无法打开 `scripts/sync-linuxdo-signature.py`。

### Task 2: 实现最小且无重试的同步 CLI

**Files:**
- Create: `scripts/sync-linuxdo-signature.py`
- Test: `tests/linuxdo-signature-sync.test.mjs`

- [ ] **Step 1: 创建完整 CLI**

```python
#!/usr/bin/env python3
import argparse
import os
import sys
from pathlib import Path
from urllib.parse import urljoin, urlparse

import requests

DEFAULT_BASE_URL = "https://linux.do"
ALLOWED_CDN_HOST = "cdn3.ldstatic.com"
TIMEOUT_SECONDS = 20


class SyncError(RuntimeError):
    pass


def parse_args():
    parser = argparse.ArgumentParser(description="Upload compact SVG and update Linux DO signature.")
    parser.add_argument("--image", type=Path, required=True)
    parser.add_argument("--username", required=True)
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL)
    return parser.parse_args()


def json_response(response, operation):
    if not response.ok:
        raise SyncError(f"{operation} failed with HTTP {response.status_code}")
    try:
        return response.json()
    except ValueError as exc:
        raise SyncError(f"{operation} returned invalid JSON") from exc


def allowed_svg_url(value):
    parsed = urlparse(value) if isinstance(value, str) else None
    if not parsed or parsed.scheme != "https" or parsed.hostname != ALLOWED_CDN_HOST or not parsed.path.lower().endswith(".svg"):
        raise SyncError("upload response URL is not an allowed Linux DO SVG URL")
    return value


def sync_signature(image, username, base_url, cookie):
    if not image.is_file() or image.suffix.lower() != ".svg":
        raise SyncError("--image must point to an existing .svg file")
    if not cookie:
        raise SyncError("LINUXDO_SESSION_COOKIE is required")
    session = requests.Session()
    session.headers.update({"Accept": "application/json", "Cookie": cookie, "User-Agent": "ceilf6-linuxdo-signature-sync/1.0", "X-Requested-With": "XMLHttpRequest"})
    base_url = f"{base_url.rstrip('/')}/"
    try:
        csrf = json_response(session.get(urljoin(base_url, "session/csrf.json"), timeout=TIMEOUT_SECONDS), "CSRF request").get("csrf")
        if not isinstance(csrf, str) or not csrf:
            raise SyncError("CSRF response did not include a token")
        with image.open("rb") as handle:
            uploaded = json_response(session.post(urljoin(base_url, "uploads.json"), data={"upload_type": "composer", "synchronous": "true"}, files={"file": (image.name, handle, "image/svg+xml")}, headers={"X-CSRF-Token": csrf}, timeout=TIMEOUT_SECONDS), "upload")
        signature_url = allowed_svg_url(uploaded.get("url"))
        json_response(session.put(urljoin(base_url, f"u/{username}.json"), data={"custom_fields[signature_url]": signature_url}, headers={"X-CSRF-Token": csrf}, timeout=TIMEOUT_SECONDS), "profile update")
    except requests.RequestException as exc:
        raise SyncError("Linux DO request failed") from exc


def main():
    args = parse_args()
    try:
        sync_signature(args.image, args.username, args.base_url, os.environ.get("LINUXDO_SESSION_COOKIE", ""))
    except SyncError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    print("Linux DO signature updated")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 2: 运行协议测试，确认三条路径通过**

Run: `node --test tests/linuxdo-signature-sync.test.mjs`

Expected: PASS；localhost 只观察到 CSRF → upload → PUT，非 `cdn3.ldstatic.com` URL 没有 PUT。

- [ ] **Step 3: 提交 CLI 与协议测试**

Run: `git add scripts/sync-linuxdo-signature.py tests/linuxdo-signature-sync.test.mjs && git commit -m "feat: add linuxdo signature sync client"`

Expected: 一个仅包含 CLI 与离线测试的提交。

### Task 3: 把受保护的 CLI 接入工作流

**Files:**
- Modify: `tests/linuxdo-signature-sync.test.mjs`
- Modify: `.github/workflows/update-github-contribution-graph.yml`
- Modify: `.github/workflows/verify.yml`

- [ ] **Step 1: 添加失败的 workflow 契约测试**

在测试文件中追加：

```js
test("contribution workflow syncs only configured changed graphs after git push", () => {
  const workflow = readFileSync(new URL("../.github/workflows/update-github-contribution-graph.yml", import.meta.url), "utf8");
  assert.match(workflow, /LINUXDO_SESSION_COOKIE/);
  assert.match(workflow, /git diff --quiet -- assets\/github-contribution-graph-compact\.svg/);
  assert.match(workflow, /scripts\/sync-linuxdo-signature\.py/);
  assert.ok(workflow.indexOf("git push") < workflow.indexOf("scripts/sync-linuxdo-signature.py"));
});
```

- [ ] **Step 2: 运行契约测试，确认当前 workflow 失败**

Run: `node --test tests/linuxdo-signature-sync.test.mjs`

Expected: FAIL，因为 workflow 尚没有 Linux DO Secret、变更检测或同步 CLI。

- [ ] **Step 3: 修改两个 workflow**

在贡献图生成后增加检测步骤：

```yaml
      - name: Detect Linux DO sync configuration
        id: linuxdo-sync
        env:
          LINUXDO_SESSION_COOKIE: ${{ secrets.LINUXDO_SESSION_COOKIE }}
        run: |
          if git diff --quiet -- assets/github-contribution-graph-compact.svg; then
            echo "changed=false" >> "$GITHUB_OUTPUT"
            echo "Linux DO sync skipped: compact graph is unchanged."
          else
            echo "changed=true" >> "$GITHUB_OUTPUT"
          fi
          if [ -z "$LINUXDO_SESSION_COOKIE" ]; then
            echo "configured=false" >> "$GITHUB_OUTPUT"
            echo "::notice::Linux DO sync is not configured; add LINUXDO_SESSION_COOKIE to enable it."
          else
            echo "configured=true" >> "$GITHUB_OUTPUT"
          fi
```

保留原有的提交和 push 步骤，并在它之后增加：

```yaml
      - name: Sync Linux DO signature
        if: ${{ steps.linuxdo-sync.outputs.changed == 'true' && steps.linuxdo-sync.outputs.configured == 'true' }}
        env:
          LINUXDO_SESSION_COOKIE: ${{ secrets.LINUXDO_SESSION_COOKIE }}
        run: python scripts/sync-linuxdo-signature.py --image assets/github-contribution-graph-compact.svg --username ceilf6
```

在 `verify.yml` 的测试前增加 `actions/setup-python@v5`（Python 3.11）及 `python -m pip install requests`。

- [ ] **Step 4: 运行聚焦测试并提交工作流接入**

Run: `node --test tests/linuxdo-signature-sync.test.mjs`

Expected: PASS，测试确认 `git push` 早于同步调用。

Run: `git add .github/workflows/update-github-contribution-graph.yml .github/workflows/verify.yml tests/linuxdo-signature-sync.test.mjs && git commit -m "ci: sync linuxdo signature after graph updates"`

Expected: 一个包含工作流和契约测试的提交。

### Task 4: 完整验证，不触发真实上传

**Files:**
- Verify: `scripts/sync-linuxdo-signature.py`
- Verify: `tests/linuxdo-signature-sync.test.mjs`
- Verify: workflow YAML files

- [ ] **Step 1: 运行全部测试**

Run: `node --test tests/*.mjs`

Expected: PASS，既有测试和新的 localhost 协议测试全部通过。

- [ ] **Step 2: 静态检查敏感信息和语法**

Run: `python3 -m py_compile scripts/sync-linuxdo-signature.py && git diff --check && rg -n 'LINUXDO_SESSION_COOKIE|csrf|Cookie' scripts/sync-linuxdo-signature.py .github/workflows/update-github-contribution-graph.yml`

Expected: Python 编译成功、diff 检查无输出，Cookie 仅作为环境变量或 GitHub Secret 出现。

- [ ] **Step 3: 等待首次真实同步的单独确认**

Run: `git status --short && git log --oneline -4`

Expected: 仅计划内改动。除非用户已在 GitHub 添加 `LINUXDO_SESSION_COOKIE` 并再次明确确认，否则不手动 dispatch workflow，不上传任何文件，也不修改 linux.do 签名。
