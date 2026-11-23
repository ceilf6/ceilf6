import test from "node:test";
import assert from "node:assert/strict";
import { spawnSync } from "node:child_process";
import {
  chmodSync,
  existsSync,
  mkdirSync,
  mkdtempSync,
  rmSync,
  writeFileSync,
} from "node:fs";
import { tmpdir } from "node:os";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const SCRIPTS_DIR = dirname(fileURLToPath(import.meta.url));
const SITE_DIR = resolve(SCRIPTS_DIR, "..");
const SERVER_DIR = resolve(SITE_DIR, "server");
const DEFAULT_VENV_DIR = resolve(SITE_DIR, ".venv");
const MANAGE_PY = resolve(SERVER_DIR, "manage.py");
const REQUIREMENTS_TXT = resolve(SERVER_DIR, "requirements.txt");

function venvPythonPath(venvDir = DEFAULT_VENV_DIR) {
  return process.platform === "win32"
    ? resolve(venvDir, "Scripts", "python.exe")
    : resolve(venvDir, "bin", "python");
}

function isVenvPythonCompatible(pythonBin) {
  const probe = spawnSync(
    pythonBin,
    ["-c", "import sys; raise SystemExit(0 if sys.version_info >= (3, 12) else 1)"],
    { encoding: "utf8" },
  );
  return probe.status === 0;
}

function isBasePythonCompatible(pythonBin) {
  const probe = spawnSync(
    pythonBin,
    [
      "-c",
      "import sys, venv, ensurepip; raise SystemExit(0 if sys.version_info >= (3, 12) else 1)",
    ],
    { encoding: "utf8" },
  );
  return probe.status === 0;
}

function hasPinnedRequirementsInstalled(
  pythonBin,
  requirementsPath = REQUIREMENTS_TXT,
) {
  const probe = spawnSync(
    pythonBin,
    [
      "-c",
      [
        "import importlib.metadata as m, pathlib, sys",
        "req_path = pathlib.Path(sys.argv[1])",
        "for raw in req_path.read_text(encoding='utf-8').splitlines():",
        "    line = raw.split('#', 1)[0].strip()",
        "    if not line:",
        "        continue",
        "    spec = line.split(';', 1)[0].strip()",
        "    if '==' not in spec:",
        "        raise SystemExit(1)",
        "    name_part, expected_ver = spec.split('==', 1)",
        "    pkg_name = name_part.split('[', 1)[0].strip()",
        "    if m.version(pkg_name) != expected_ver.strip():",
        "        raise SystemExit(1)",
      ].join("\n"),
      requirementsPath,
    ],
    { encoding: "utf8" },
  );
  return probe.status === 0;
}

function findBasePython() {
  const candidates = [
    process.env.SITE_PYTHON,
    "python3.12",
    "python3.13",
    "python3.14",
    "/opt/homebrew/bin/python3",
    "/usr/local/bin/python3",
    "/usr/bin/python3",
    "python3",
  ].filter(Boolean);

  for (const candidate of candidates) {
    if (isBasePythonCompatible(candidate)) {
      return candidate;
    }
  }
  throw new Error(
    "未找到可用的 Python >= 3.12（需包含 venv 与 ensurepip 模块）；可通过 SITE_PYTHON 指定解释器路径。",
  );
}

function runChecked(bin, args, options = {}) {
  const result = spawnSync(bin, args, {
    encoding: "utf8",
    ...options,
  });
  if (result.status !== 0) {
    const details = [
      `Command failed (${result.status ?? "signal"}): ${bin} ${args.join(" ")}`,
      result.stdout ? `--- stdout ---\n${result.stdout}` : "",
      result.stderr ? `--- stderr ---\n${result.stderr}` : "",
    ]
      .filter(Boolean)
      .join("\n");
    throw new Error(details);
  }
  return result;
}

function ensureServerVenv({
  venvDir = DEFAULT_VENV_DIR,
  requirementsPath = REQUIREMENTS_TXT,
} = {}) {
  const existingPython = venvPythonPath(venvDir);

  if (existsSync(venvDir)) {
    if (!existsSync(existingPython) || !isVenvPythonCompatible(existingPython)) {
      throw new Error(
        `检测到已有虚拟环境不可用或 Python 版本低于 3.12: ${venvDir}。请手动删除该目录后重试，或使用 SITE_PYTHON 指定 Python >= 3.12 重新创建。`,
      );
    }
    if (hasPinnedRequirementsInstalled(existingPython, requirementsPath)) {
      return existingPython;
    }
    runChecked(
      existingPython,
      [
        "-m",
        "pip",
        "install",
        "--disable-pip-version-check",
        "--retries",
        "1",
        "--timeout",
        "15",
        "-r",
        requirementsPath,
      ],
      { cwd: SITE_DIR },
    );
    return existingPython;
  }

  const basePython = findBasePython();
  runChecked(basePython, ["-m", "venv", venvDir], { cwd: SITE_DIR });

  const createdPython = venvPythonPath(venvDir);
  runChecked(
    createdPython,
    [
      "-m",
      "pip",
      "install",
      "--disable-pip-version-check",
      "--retries",
      "1",
      "--timeout",
      "15",
      "-r",
      requirementsPath,
    ],
    { cwd: SITE_DIR },
  );
  return createdPython;
}

test("已有不兼容虚拟环境时报错提示且绝不删除用户目录", () => {
  const tempRoot = mkdtempSync(join(tmpdir(), "site-venv-guard-"));
  const fakeVenv = join(tempRoot, ".venv");
  const binDir = join(
    fakeVenv,
    process.platform === "win32" ? "Scripts" : "bin",
  );
  mkdirSync(binDir, { recursive: true });
  const sentinelFile = join(fakeVenv, "keep-me.txt");
  writeFileSync(sentinelFile, "user data", "utf8");

  if (process.platform !== "win32") {
    const fakePy = join(binDir, "python");
    writeFileSync(fakePy, "#!/bin/sh\nexit 1\n", "utf8");
    chmodSync(fakePy, 0o755);
  }

  try {
    assert.throws(
      () => ensureServerVenv({ venvDir: fakeVenv }),
      /SITE_PYTHON/,
    );
    assert.equal(existsSync(sentinelFile), true);
  } finally {
    rmSync(tempRoot, { recursive: true, force: true });
  }
});

test(
  "site/server Django check、迁移一致性校验与单元测试全部通过",
  { timeout: 180_000 },
  () => {
    const python = ensureServerVenv();
    const scratchDir = mkdtempSync(join(tmpdir(), "site-server-verify-"));

    try {
      const customReq = join(scratchDir, "extras-requirements.txt");
      writeFileSync(
        customReq,
        [
          "# comment line",
          "Django==5.2.19 # inline comment",
          'django-allauth[socialaccount]==65.22.1 ; python_version >= "3.12"',
          "packaging==26.3",
        ].join("\n"),
        "utf8",
      );
      assert.equal(hasPinnedRequirementsInstalled(python, customReq), true);

      const env = {
        ...process.env,
        DJANGO_DOTENV_PATH: join(scratchDir, ".env.isolated"),
        DJANGO_DEBUG: "true",
        SQLITE_PATH: join(scratchDir, "verify.sqlite3"),
        EMAIL_FILE_PATH: join(scratchDir, "mail"),
      };
      delete env.DJANGO_SECRET_KEY;
      delete env.DJANGO_ALLOWED_HOSTS;

      runChecked(python, [MANAGE_PY, "check"], { cwd: SERVER_DIR, env });

      runChecked(
        python,
        [MANAGE_PY, "makemigrations", "--check", "--dry-run"],
        { cwd: SERVER_DIR, env },
      );

      const testRun = runChecked(
        python,
        [MANAGE_PY, "test", "--verbosity", "2"],
        {
          cwd: SERVER_DIR,
          env,
        },
      );
      const countMatch = `${testRun.stdout}\n${testRun.stderr}`.match(
        /Ran (\d+) tests?/,
      );
      assert.ok(
        countMatch && Number(countMatch[1]) > 0,
        "Django manage.py test 未发现或未执行任何测试用例",
      );
    } finally {
      rmSync(scratchDir, { recursive: true, force: true });
    }
  },
);
