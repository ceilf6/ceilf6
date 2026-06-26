import assert from "node:assert/strict";
import { spawn } from "node:child_process";
import { mkdtempSync, readFileSync, writeFileSync } from "node:fs";
import { createServer } from "node:http";
import { tmpdir } from "node:os";
import { join } from "node:path";
import test from "node:test";

const repoRoot = new URL("../", import.meta.url);
const syncScript = new URL("../scripts/sync-linuxdo-signature.py", import.meta.url);

function createSvg() {
  const directory = mkdtempSync(join(tmpdir(), "linuxdo-signature-sync-"));
  const image = join(directory, "graph.svg");
  writeFileSync(image, '<svg xmlns="http://www.w3.org/2000/svg" />');
  return image;
}

function startServer(t, handler) {
  const server = createServer(handler);
  return new Promise((resolve) => {
    server.listen(0, "127.0.0.1", () => {
      t.after(() => server.close());
      resolve(`http://127.0.0.1:${server.address().port}`);
    });
  });
}

function runSync({ image, baseUrl, cookie = "_forum_session=test-session" }) {
  return new Promise((resolve, reject) => {
    const child = spawn(
      "python3",
      [syncScript.pathname, "--image", image, "--username", "ceilf6", "--base-url", baseUrl],
      {
        cwd: repoRoot,
        env: { ...process.env, LINUXDO_SESSION_COOKIE: cookie },
      },
    );
    let stdout = "";
    let stderr = "";
    child.stdout.on("data", (chunk) => (stdout += chunk));
    child.stderr.on("data", (chunk) => (stderr += chunk));
    child.on("error", reject);
    child.on("close", (status) => resolve({ status, stdout, stderr }));
  });
}

function runBaseUrlValidation(baseUrl) {
  const source = [
    "import importlib.util, sys",
    "spec = importlib.util.spec_from_file_location('linuxdo_sync', sys.argv[1])",
    "module = importlib.util.module_from_spec(spec)",
    "spec.loader.exec_module(module)",
    "try:",
    "    module.normalized_base_url(sys.argv[2])",
    "except module.SyncError as exc:",
    "    print(exc, file=sys.stderr)",
    "    raise SystemExit(1)",
  ].join("\n");
  return new Promise((resolve, reject) => {
    const child = spawn("python3", ["-c", source, syncScript.pathname, baseUrl], {
      cwd: repoRoot,
    });
    let stderr = "";
    child.stderr.on("data", (chunk) => (stderr += chunk));
    child.on("error", reject);
    child.on("close", (status) => resolve({ status, stderr }));
  });
}

test("sync uploads the compact SVG then updates only signature_url", async (t) => {
  const requests = [];
  const baseUrl = await startServer(t, (request, response) => {
    let body = "";
    request.setEncoding("utf8");
    request.on("data", (chunk) => (body += chunk));
    request.on("end", () => {
      requests.push({ method: request.method, url: request.url, headers: request.headers, body });
      response.setHeader("content-type", "application/json");
      if (request.method === "GET" && request.url === "/session/csrf.json") {
        response.end(JSON.stringify({ csrf: "csrf-token" }));
      } else if (request.method === "POST" && request.url === "/uploads.json") {
        response.end(JSON.stringify({ url: "https://cdn3.ldstatic.com/original/4X/a/b/c/graph.svg" }));
      } else if (request.method === "PUT" && request.url === "/u/ceilf6.json") {
        response.end(JSON.stringify({ success: "OK" }));
      } else {
        response.statusCode = 404;
        response.end(JSON.stringify({ error: "unexpected request" }));
      }
    });
  });

  const result = await runSync({ image: createSvg(), baseUrl });

  assert.equal(result.status, 0, result.stderr);
  assert.match(result.stdout, /Linux DO signature updated/);
  assert.deepEqual(requests.map(({ method, url }) => [method, url]), [
    ["GET", "/session/csrf.json"],
    ["POST", "/uploads.json"],
    ["PUT", "/u/ceilf6.json"],
  ]);
  assert.equal(requests[0].headers.cookie, "_forum_session=test-session");
  assert.equal(requests[1].headers["x-csrf-token"], "csrf-token");
  assert.match(requests[1].body, /name="upload_type"\r\n\r\ncomposer/);
  assert.match(requests[1].body, /name="synchronous"\r\n\r\ntrue/);
  assert.equal(requests[2].headers["x-csrf-token"], "csrf-token");
  assert.match(requests[2].body, /custom_fields%5Bsignature_url%5D=/);
  assert.match(requests[2].body, /cdn3.ldstatic.com/);
});

test("sync rejects a missing Cookie before opening a network connection", async () => {
  const result = await runSync({ image: createSvg(), baseUrl: "http://127.0.0.1:9", cookie: "" });

  assert.notEqual(result.status, 0);
  assert.match(result.stderr, /LINUXDO_SESSION_COOKIE is required/);
});

test("sync rejects an untrusted upload URL without updating the profile", async (t) => {
  const requests = [];
  const baseUrl = await startServer(t, (request, response) => {
    request.resume();
    requests.push([request.method, request.url]);
    response.setHeader("content-type", "application/json");
    if (request.method === "GET" && request.url === "/session/csrf.json") {
      response.end(JSON.stringify({ csrf: "csrf-token" }));
    } else if (request.method === "POST" && request.url === "/uploads.json") {
      response.end(JSON.stringify({ url: "https://example.invalid/graph.svg" }));
    } else {
      response.statusCode = 500;
      response.end(JSON.stringify({ error: "profile update must not occur" }));
    }
  });

  const result = await runSync({ image: createSvg(), baseUrl });

  assert.notEqual(result.status, 0);
  assert.match(result.stderr, /not an allowed Linux DO SVG URL/);
  assert.deepEqual(requests, [
    ["GET", "/session/csrf.json"],
    ["POST", "/uploads.json"],
  ]);
});

test("sync stops after a failed request without retrying", async (t) => {
  const requests = [];
  const baseUrl = await startServer(t, (request, response) => {
    request.resume();
    requests.push([request.method, request.url]);
    response.statusCode = 403;
    response.setHeader("content-type", "application/json");
    response.end(JSON.stringify({ error: "forbidden" }));
  });

  const result = await runSync({ image: createSvg(), baseUrl });

  assert.notEqual(result.status, 0);
  assert.match(result.stderr, /CSRF request failed with HTTP 403/);
  assert.deepEqual(requests, [["GET", "/session/csrf.json"]]);
});

test("sync refuses an insecure Linux DO base URL before sending a Cookie", async () => {
  const result = await runBaseUrlValidation("http://linux.do");

  assert.notEqual(result.status, 0);
  assert.match(result.stderr, /--base-url is not an allowed Linux DO endpoint/);
});

test("contribution workflow syncs configured changed graphs only after git push", () => {
  const workflow = readFileSync(
    new URL("../.github/workflows/update-github-contribution-graph.yml", import.meta.url),
    "utf8",
  );

  assert.match(workflow, /LINUXDO_SESSION_COOKIE/);
  assert.match(workflow, /LINUXDO_SYNC_ENABLED/);
  assert.match(workflow, /sync_linuxdo/);
  assert.match(workflow, /github\.event_name == 'workflow_dispatch'/);
  assert.match(workflow, /git diff --quiet -- assets\/github-contribution-graph-compact\.svg/);
  assert.match(workflow, /scripts\/sync-linuxdo-signature\.py/);
  assert.ok(workflow.indexOf("git push") < workflow.indexOf("scripts/sync-linuxdo-signature.py"));
});
