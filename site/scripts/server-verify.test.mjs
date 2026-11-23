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

const CHECK_REQUIREMENTS_PY = `
import importlib.metadata as m
import pathlib
import re
import sys

REQ_RE = re.compile(r"^([A-Za-z0-9][A-Za-z0-9._-]*)(?:\\[([^\\]]+)\\])?$")
DEP_RE = re.compile(r"^([A-Za-z0-9][A-Za-z0-9._-]*)(?:\\[([^\\]]+)\\])?")

def norm(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()

def verify_extras(pkg_name: str, extras: list[str], seen: set[tuple[str, str]]) -> None:
    dist = m.distribution(pkg_name)
    declared_extras = {
        norm(v) for v in (dist.metadata.get_all("Provides-Extra") or [])
    }
    reqs = dist.requires or []
    for extra in extras:
        extra_norm = norm(extra)
        if (norm(pkg_name), extra_norm) in seen:
            continue
        seen.add((norm(pkg_name), extra_norm))
        extra_pat = re.compile(
            r"""extra\\s*==\\s*['"]""" + re.escape(extra.strip()) + r"""['"]""",
            re.IGNORECASE,
        )
        matched = extra_norm in declared_extras
        for req_line in reqs:
            if ";" not in req_line:
                continue
            dep_spec, marker = req_line.split(";", 1)
            if not extra_pat.search(marker):
                continue
            matched = True
            dep_match = DEP_RE.match(dep_spec.strip())
            if not dep_match:
                raise SystemExit(1)
            sub_pkg = dep_match.group(1)
            sub_extras = [
                e.strip() for e in (dep_match.group(2) or "").split(",") if e.strip()
            ]
            m.distribution(sub_pkg)
            if sub_extras:
                verify_extras(sub_pkg, sub_extras, seen)
        if not matched:
            raise SystemExit(1)

req_path = pathlib.Path(sys.argv[1])
for raw in req_path.read_text(encoding="utf-8").splitlines():
    line = raw.split("#", 1)[0].strip()
    if not line:
        continue
    spec = line.split(";", 1)[0].strip()
    if "==" not in spec:
        raise SystemExit(1)
    name_part, expected_ver = spec.split("==", 1)
    parsed = REQ_RE.match(name_part.strip())
    if not parsed:
        raise SystemExit(1)
    pkg_name = parsed.group(1)
    extras = [
        e.strip() for e in (parsed.group(2) or "").split(",") if e.strip()
    ]
    if m.version(pkg_name) != expected_ver.strip():
        raise SystemExit(1)
    if extras:
        verify_extras(pkg_name, extras, set())
`;

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
  extraEnv = {},
) {
  const probe = spawnSync(
    pythonBin,
    ["-c", CHECK_REQUIREMENTS_PY, requirementsPath],
    {
      encoding: "utf8",
      env: { ...process.env, ...extraEnv },
    },
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
      const distInfoDir = join(scratchDir, "demo_pkg-1.0.0.dist-info");
      mkdirSync(distInfoDir, { recursive: true });
      writeFileSync(
        join(distInfoDir, "METADATA"),
        [
          "Metadata-Version: 2.1",
          "Name: demo-pkg",
          "Version: 1.0.0",
          "Provides-Extra: satisfied",
          'Requires-Dist: sqlparse>=0.3.1; extra == "satisfied"',
          "Provides-Extra: missing",
          'Requires-Dist: missing-sub-dep>=1.0; extra == "missing"',
        ].join("\n"),
        "utf8",
      );

      const satisfiedReq = join(scratchDir, "satisfied-requirements.txt");
      writeFileSync(
        satisfiedReq,
        [
          "# comment line",
          "Django==5.2.19 # inline comment",
          'django-allauth==65.22.1 ; python_version >= "3.12"',
          "demo-pkg[satisfied]==1.0.0",
        ].join("\n"),
        "utf8",
      );
      assert.equal(
        hasPinnedRequirementsInstalled(python, satisfiedReq, {
          PYTHONPATH: scratchDir,
        }),
        true,
      );

      const missingExtraReq = join(scratchDir, "missing-extra-requirements.txt");
      writeFileSync(
        missingExtraReq,
        ["django-allauth[socialaccount]==65.22.1"].join("\n"),
        "utf8",
      );
      assert.equal(
        hasPinnedRequirementsInstalled(python, missingExtraReq),
        false,
      );

      const missingSyntheticExtraReq = join(
        scratchDir,
        "missing-synth-extra.txt",
      );
      writeFileSync(
        missingSyntheticExtraReq,
        ["demo-pkg[missing]==1.0.0"].join("\n"),
        "utf8",
      );
      assert.equal(
        hasPinnedRequirementsInstalled(python, missingSyntheticExtraReq, {
          PYTHONPATH: scratchDir,
        }),
        false,
      );

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
