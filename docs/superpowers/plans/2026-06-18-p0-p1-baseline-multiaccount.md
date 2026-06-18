# P0 + P1: Baseline Safety Net & Multi-Account Supervision — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Lock a green test baseline + comparison artifacts (P0), then give Eden a supervised multi-account system ported from SweepyCL: an `/api/health` heartbeat, an `accounts.json`-driven API, and a `manager.py` supervisor with auto/stale restart (P1).

**Architecture:** Framework-free logic (account validation, health payload) lives in a new focused module `career_bot/cluster.py` so it is unit-testable without importing `main.py` (which imports `frida`). `main.py` adds thin endpoints that delegate to `cluster.py`. The runner gains a heartbeat so the supervisor can detect stuck instances. `manager.py` is ported verbatim from SweepyCL (it was written to supervise Eden instances and already shells out to `main.py <config>.json`, which Eden already supports).

**Tech Stack:** Python 3.11+, FastAPI, pytest, stdlib `urllib`/`subprocess` (no new runtime deps).

---

## File Structure

- Create: `career_bot/cluster.py` — pure helpers: account validation, accounts.json read/write, health payload builder.
- Create: `manager.py` (repo root) — multi-instance supervisor (ported).
- Create: `docs/superpowers/specs/module-comparison-matrix.md` — comparison artifact (P0).
- Create: `career_bot/shadow.py` — A/B decision logger for later decision phases (P0 foundation).
- Modify: `career_bot/runner.py` — add `last_heartbeat`/`recoveries` to status; update on advance/recovery.
- Modify: `main.py` — add `AccountsConfigRequest` model and endpoints `/api/health`, `/api/accounts`, `/api/accounts/status`, `/api/accounts/manager/start`.
- Create tests: `tests/test_p0_baseline.py`, `tests/test_cluster.py`, `tests/test_runner_heartbeat.py`.

Run all tests with: `python -m pytest -q` from the repo root.

---

## P0 — Baseline & Safety Net

### Task 0: Record the green test baseline

**Files:**
- Create: `docs/superpowers/baseline-tests-2026-06-18.txt`

- [ ] **Step 1: Run the existing suite and capture output**

Run: `python -m pytest -q | tee docs/superpowers/baseline-tests-2026-06-18.txt`
Expected: the run completes and the summary line (e.g. `6 passed`) is written to the file. If any test errors on a missing dependency (e.g. `frida`), note it at the top of the file as a known-environment skip — do NOT fix unrelated code.

- [ ] **Step 2: Commit the baseline**

```bash
git add docs/superpowers/baseline-tests-2026-06-18.txt
git commit -m "test: record pre-merge baseline test results"
```

### Task 1: Create the module comparison matrix artifact

**Files:**
- Create: `docs/superpowers/specs/module-comparison-matrix.md`

- [ ] **Step 1: Write the matrix skeleton with the measured data**

```markdown
# Module Comparison Matrix (Eden vs SweepyCL)

Measured 2026-06-18. Verdict legend: ADOPT_SWEEPY / KEEP_EDEN / MERGE.

| Module | SweepyCL LOC | Eden LOC | Verdict | Notes |
|---|---|---|---|---|
| career_bot/delay.py | 183 | 183 | KEEP_EDEN | Identical |
| career_bot/events.py | 605 | 48 | ADOPT_SWEEPY | Eden is a stub |
| career_bot/master_data.py | 2334 | 599 | ADOPT_SWEEPY | Data backbone |
| career_bot/races.py | 890 | 161 | ADOPT_SWEEPY | Smart solver + trackblazer |
| career_bot/skills.py | 1358 | 522 | ADOPT_SWEEPY | |
| career_bot/items.py | 1755 | 1288 | MERGE | Keep Eden MANT fast path |
| career_bot/runner.py | 3549 | 1253 | MERGE | Keep multi-account/MANT deltas |
| career_bot/report.py | 220 | 151 | MERGE | Keep Eden UI fields |
| career_bot/presets.py | 221 | 162 | MERGE | Keep Eden fields |
| uma_api/client.py | 1068 | 1045 | MERGE | Compare endpoints function-by-function |

## Per-function detail (filled in per phase)

(Each phase's Porter agent appends a function-by-function table for the
modules it touches, with the chosen verdict and one-line justification.)
```

- [ ] **Step 2: Commit**

```bash
git add docs/superpowers/specs/module-comparison-matrix.md
git commit -m "docs: add module comparison matrix skeleton"
```

### Task 2: Add the shadow decision logger

**Files:**
- Create: `career_bot/shadow.py`
- Test: `tests/test_p0_baseline.py`

- [ ] **Step 1: Write the failing test**

```python
import json
from pathlib import Path
from career_bot.shadow import ShadowLogger

def test_shadow_logger_records_disagreement(tmp_path):
    log = tmp_path / "shadow.jsonl"
    sl = ShadowLogger(str(log), enabled=True)
    sl.record(turn=5, context="train", authoritative="speed", shadow="power",
              detail={"score_a": 1.0, "score_b": 1.2})
    lines = Path(log).read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 1
    row = json.loads(lines[0])
    assert row["turn"] == 5
    assert row["authoritative"] == "speed"
    assert row["shadow"] == "power"
    assert row["agree"] is False

def test_shadow_logger_disabled_writes_nothing(tmp_path):
    log = tmp_path / "shadow.jsonl"
    sl = ShadowLogger(str(log), enabled=False)
    sl.record(turn=1, context="train", authoritative="x", shadow="x")
    assert not log.exists()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_p0_baseline.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'career_bot.shadow'`

- [ ] **Step 3: Write the implementation**

```python
"""Shadow-mode A/B decision logger.

Used by later decision phases (training scorer, race solver, events) to run a
candidate decision path alongside the authoritative one and record where they
disagree, without affecting gameplay. Append-only JSONL, thread-safe.
"""
from __future__ import annotations

import json
import os
import threading
import time


class ShadowLogger:
    def __init__(self, path: str, enabled: bool = False):
        self.path = path
        self.enabled = bool(enabled)
        self._lock = threading.Lock()

    def record(self, turn, context, authoritative, shadow, detail=None):
        if not self.enabled:
            return
        row = {
            "ts": time.time(),
            "turn": int(turn or 0),
            "context": str(context or ""),
            "authoritative": authoritative,
            "shadow": shadow,
            "agree": authoritative == shadow,
            "detail": detail or {},
        }
        line = json.dumps(row, ensure_ascii=False)
        with self._lock:
            os.makedirs(os.path.dirname(self.path) or ".", exist_ok=True)
            with open(self.path, "a", encoding="utf-8") as fh:
                fh.write(line + "\n")
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_p0_baseline.py -v`
Expected: PASS (2 passed)

- [ ] **Step 5: Commit**

```bash
git add career_bot/shadow.py tests/test_p0_baseline.py
git commit -m "feat: add shadow-mode A/B decision logger"
```

---

## P1 — Multi-Account Supervision

### Task 3: Add a heartbeat and recovery counter to the runner

**Files:**
- Modify: `career_bot/runner.py` (status dicts ~line 64 and ~line 116; `_advance` ~line 414; `_recover_blocked_state` ~line 517)
- Test: `tests/test_runner_heartbeat.py`

- [ ] **Step 1: Write the failing test**

```python
import time
from pathlib import Path
from career_bot.runner import CareerRunner

ROOT = Path(__file__).resolve().parent.parent

def test_snapshot_exposes_heartbeat_and_recoveries():
    r = CareerRunner(str(ROOT))
    snap = r.snapshot()
    assert "last_heartbeat" in snap
    assert "recoveries" in snap
    assert snap["recoveries"] == 0

def test_advance_updates_heartbeat():
    r = CareerRunner(str(ROOT))
    before = r.snapshot().get("last_heartbeat") or 0
    time.sleep(0.01)
    r._advance("train")
    after = r.snapshot().get("last_heartbeat") or 0
    assert after > before
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_runner_heartbeat.py -v`
Expected: FAIL — `assert "last_heartbeat" in snap` (KeyError / assertion).

- [ ] **Step 3: Add the fields to both status dicts**

In `career_bot/runner.py`, the `__init__` status dict (around line 64) ends with:

```python
            "log": [],
            "action_history": [],
        }
```

Change it to:

```python
            "log": [],
            "action_history": [],
            "last_heartbeat": time.time(),
            "recoveries": 0,
        }
```

Apply the identical change to the second status dict assigned inside `start()` (around line 116), which currently also ends with `"log": [], "action_history": [], }`.

- [ ] **Step 4: Update `_advance` to refresh the heartbeat**

The current method (around line 414):

```python
    def _advance(self, action):
        with self.lock:
            self.status["steps"] += 1
            self.status["last_action"] = action
```

becomes:

```python
    def _advance(self, action):
        with self.lock:
            self.status["steps"] += 1
            self.status["last_action"] = action
            self.status["last_heartbeat"] = time.time()
```

- [ ] **Step 5: Bump the recovery counter on blocked-state recovery**

In `_recover_blocked_state` (around line 517), at the very start of the method body (first line inside the method, before the existing logic), add:

```python
        with self.lock:
            self.status["recoveries"] = int(self.status.get("recoveries", 0)) + 1
            self.status["last_heartbeat"] = time.time()
```

(Confirm `time` is already imported at the top of `runner.py` — it is, used by `_log_locked`.)

- [ ] **Step 6: Run tests to verify they pass**

Run: `python -m pytest tests/test_runner_heartbeat.py -v`
Expected: PASS (2 passed)

- [ ] **Step 7: Commit**

```bash
git add career_bot/runner.py tests/test_runner_heartbeat.py
git commit -m "feat: expose runner heartbeat and recovery counter"
```

### Task 4: Add framework-free cluster helpers

**Files:**
- Create: `career_bot/cluster.py`
- Test: `tests/test_cluster.py`

- [ ] **Step 1: Write the failing test**

```python
import json
import pytest
from career_bot import cluster

def test_validate_rejects_duplicate_port():
    with pytest.raises(ValueError):
        cluster.validate_accounts_config([
            {"name": "a", "port": 1616},
            {"name": "b", "port": 1616},
        ])

def test_validate_rejects_out_of_range_port():
    with pytest.raises(ValueError):
        cluster.validate_accounts_config([{"name": "a", "port": 80}])

def test_validate_normalizes_and_defaults():
    clean = cluster.validate_accounts_config([{"name": "Main Acct!", "port": 1616}])
    assert clean[0]["name"] == "Main_Acct"
    assert clean[0]["auto_restart"] is True
    assert clean[0]["stale_restart_seconds"] == 900
    assert clean[0]["config"] == "Main_Acct.json"

def test_read_write_roundtrip(tmp_path):
    p = tmp_path / "accounts.json"
    cluster.write_accounts_config(str(p), [{"name": "x", "port": 1700}])
    got = cluster.read_accounts_config(str(p), default_name="x", default_port=1700)
    assert got[0]["port"] == 1700

def test_read_creates_default_when_missing(tmp_path):
    p = tmp_path / "accounts.json"
    got = cluster.read_accounts_config(str(p), default_name="main", default_port=1616)
    assert got == [{"name": "main", "port": 1616, "auto_restart": True, "stale_restart_seconds": 900, "config": "main.json"}]
    assert p.exists()

def test_build_health_payload_running_and_stale():
    snap = {"running": True, "last_heartbeat": 1000.0, "last_error": "", "recoveries": 2, "turn": 12, "last_action": "train"}
    out = cluster.build_health_payload(snap, logged_in=True, profile="main", port=1616, now=1100.0)
    assert out["runner_running"] is True
    assert out["runner_stale_seconds"] == 100
    assert out["state"] == "running"
    assert out["recoveries"] == 2
    assert out["profile"] == "main"

def test_build_health_payload_idle_not_stale():
    snap = {"running": False, "last_heartbeat": 0, "last_error": ""}
    out = cluster.build_health_payload(snap, logged_in=True, profile="main", port=1616, now=1100.0)
    assert out["runner_running"] is False
    assert out["runner_stale_seconds"] == 0
    assert out["state"] == "logged-in"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_cluster.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'career_bot.cluster'`

- [ ] **Step 3: Write the implementation**

```python
"""Framework-free helpers for Eden's multi-account cluster.

Kept import-light (stdlib only) so it is unit-testable without importing
main.py (which imports frida). main.py wraps these and translates ValueError
into HTTP 400.
"""
from __future__ import annotations

import json
import re
from pathlib import Path


def normalize_account_name(value, fallback):
    name = re.sub(r"[^a-zA-Z0-9_-]+", "_", str(value or fallback)).strip("_")
    return name or fallback


def normalize_config_name(value, fallback_name):
    raw = str(value or f"{fallback_name}.json").strip()
    raw = raw.replace("\\", "/").split("/")[-1]
    raw = re.sub(r"[^a-zA-Z0-9_.-]+", "_", raw).strip("._")
    if not raw:
        raw = f"{fallback_name}.json"
    if not raw.lower().endswith(".json"):
        raw = f"{raw}.json"
    return raw


def validate_accounts_config(accounts):
    if not isinstance(accounts, list):
        raise ValueError("Accounts payload must be a list.")
    clean = []
    seen_ports = {}
    seen_names = {}
    for idx, account in enumerate(accounts):
        if not isinstance(account, dict):
            raise ValueError(f"Account row {idx + 1} must be an object.")
        name = normalize_account_name(account.get("name"), f"account{idx + 1}")
        key = name.lower()
        if key in seen_names:
            raise ValueError(f"Duplicate account name '{name}'. Names must be unique.")
        seen_names[key] = idx
        try:
            port = int(account.get("port"))
        except Exception:
            raise ValueError(f"Account '{name}' has an invalid port (use 1024-65535).")
        if port < 1024 or port > 65535:
            raise ValueError(f"Account '{name}' port {port} is outside 1024-65535.")
        if port in seen_ports:
            raise ValueError(f"Duplicate port {port} used by '{seen_ports[port]}' and '{name}'.")
        seen_ports[port] = name
        stale = account.get("stale_restart_seconds", 900)
        try:
            stale = int(stale)
        except Exception:
            raise ValueError(f"Account '{name}' stale_restart_seconds must be a number.")
        stale = max(60, min(stale, 86400))
        clean.append({
            "name": name,
            "config": normalize_config_name(account.get("config"), name),
            "port": port,
            "auto_restart": bool(account.get("auto_restart", True)),
            "stale_restart_seconds": stale,
        })
    if not clean:
        raise ValueError("At least one account is required.")
    return clean


def _default_accounts(default_name, default_port):
    return [{
        "name": default_name, "port": int(default_port),
        "auto_restart": True, "stale_restart_seconds": 900,
        "config": f"{default_name}.json",
    }]


def read_accounts_config(path, default_name="default", default_port=1616):
    p = Path(path)
    if not p.exists():
        accounts = _default_accounts(default_name, default_port)
        p.write_text(json.dumps(accounts, indent=2), encoding="utf-8")
        return accounts
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
        if isinstance(data, list):
            return validate_accounts_config(data)
    except ValueError:
        raise
    except Exception:
        pass
    return _default_accounts(default_name, default_port)


def write_accounts_config(path, accounts):
    clean = validate_accounts_config(accounts)
    p = Path(path)
    tmp = p.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(clean, indent=2), encoding="utf-8")
    tmp.replace(p)
    return clean


def build_health_payload(snapshot, logged_in, profile, port, now):
    running = bool(snapshot.get("running"))
    hb = float(snapshot.get("last_heartbeat") or 0)
    stale = int(max(0, now - hb)) if (running and hb) else 0
    if running:
        state = "running"
    elif logged_in:
        state = "logged-in"
    else:
        state = "booted"
    return {
        "success": True,
        "profile": profile,
        "port": int(port),
        "state": state,
        "logged_in": bool(logged_in),
        "runner_running": running,
        "runner_stale_seconds": stale,
        "runner_last_error": snapshot.get("last_error", ""),
        "recoveries": int(snapshot.get("recoveries", 0)),
        "turn": int(snapshot.get("turn", 0)),
        "last_action": snapshot.get("last_action", ""),
        "last_heartbeat": hb,
        "updated_at": now,
    }
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_cluster.py -v`
Expected: PASS (7 passed)

- [ ] **Step 5: Commit**

```bash
git add career_bot/cluster.py tests/test_cluster.py
git commit -m "feat: add framework-free multi-account cluster helpers"
```

### Task 5: Wire the cluster endpoints into main.py

**Files:**
- Modify: `main.py` (add import near other `career_bot` imports ~line 26; add `AccountsConfigRequest` near other `BaseModel` classes ~line 1130; add endpoints near other `@app.get` routes)

- [ ] **Step 1: Add the import and the request model**

Near the top imports of `main.py` (after `from career_bot.runner import CareerRunner`), add:

```python
from career_bot import cluster
```

Near the other `class ...Request(BaseModel)` definitions (e.g. by line 1130), add:

```python
class AccountsConfigRequest(BaseModel):
    accounts: list
```

- [ ] **Step 2: Add the `/api/health` endpoint**

Add this route (place it next to the other `@app.get` routes):

```python
@app.get("/api/health")
async def api_health():
    snap = career_runner.snapshot()
    return cluster.build_health_payload(
        snap,
        logged_in=active_client is not None,
        profile=PROFILE_NAME,
        port=PORT,
        now=time.time(),
    )
```

- [ ] **Step 3: Add the accounts read/write endpoints**

```python
def _accounts_path():
    return os.path.join(DIR, "accounts.json")


@app.get("/api/accounts")
async def api_accounts():
    accounts = cluster.read_accounts_config(_accounts_path(), default_name=PROFILE_NAME or "default", default_port=int(PORT))
    return {"success": True, "accounts": accounts, "path": _accounts_path()}


@app.post("/api/accounts")
async def api_save_accounts(req: AccountsConfigRequest):
    try:
        accounts = cluster.write_accounts_config(_accounts_path(), req.accounts)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return {"success": True, "accounts": accounts, "path": _accounts_path()}
```

- [ ] **Step 4: Add the status and manager-start endpoints**

```python
def _health_for_port(port):
    import urllib.request
    url = f"http://127.0.0.1:{int(port)}/api/health"
    try:
        with urllib.request.urlopen(url, timeout=1.5) as res:
            payload = json.loads(res.read().decode("utf-8"))
            payload["reachable"] = True
            return payload
    except Exception as exc:
        return {"success": False, "reachable": False, "detail": str(exc)}


manager_process = None


@app.get("/api/accounts/status")
async def api_accounts_status():
    accounts = cluster.read_accounts_config(_accounts_path(), default_name=PROFILE_NAME or "default", default_port=int(PORT))
    status_path = Path(DIR) / "uma_runtime" / "manager_status.json"
    manager_status = None
    if status_path.exists():
        try:
            manager_status = json.loads(status_path.read_text(encoding="utf-8"))
        except Exception:
            manager_status = None
    live = {int(a["port"]): _health_for_port(a["port"]) for a in accounts}
    return {"success": True, "accounts": accounts, "manager_status": manager_status, "health": live}


@app.post("/api/accounts/manager/start")
async def api_accounts_manager_start():
    global manager_process
    if manager_process and manager_process.poll() is None:
        return {"success": True, "already_running": True, "pid": manager_process.pid}
    log_dir = Path(DIR) / "uma_runtime" / "manager_logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    log_file = open(log_dir / "dashboard-manager.log", "a", encoding="utf-8")
    manager_process = subprocess.Popen(
        [sys.executable, "manager.py"],
        cwd=DIR,
        stdout=log_file,
        stderr=subprocess.STDOUT,
        creationflags=getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0),
    )
    return {"success": True, "pid": manager_process.pid}
```

- [ ] **Step 5: Smoke-check that main.py still imports/compiles**

Run: `python -c "import ast; ast.parse(open('main.py', encoding='utf-8').read()); print('main.py parses OK')"`
Expected: `main.py parses OK`

(Confirm `os`, `json`, `sys`, `subprocess`, `time`, and `Path` are already imported at the top of `main.py` — they are.)

- [ ] **Step 6: Commit**

```bash
git add main.py
git commit -m "feat: add health and multi-account API endpoints"
```

### Task 6: Port the supervisor (manager.py)

**Files:**
- Create: `manager.py` (repo root)
- Test: `tests/test_manager.py`

- [ ] **Step 1: Write the failing test**

```python
import json
from pathlib import Path
import importlib.util

ROOT = Path(__file__).resolve().parent.parent
spec = importlib.util.spec_from_file_location("eden_manager", ROOT / "manager.py")
manager = importlib.util.module_from_spec(spec)
spec.loader.exec_module(manager)

def test_safe_name_sanitizes():
    assert manager.safe_name("Main Acct!") == "Main_Acct"
    assert manager.safe_name("") == "default"

def test_atomic_write_json(tmp_path):
    p = tmp_path / "x.json"
    manager.atomic_write_json(p, {"a": 1})
    assert json.loads(p.read_text(encoding="utf-8")) == {"a": 1}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_manager.py -v`
Expected: FAIL — `manager.py` does not exist (FileNotFoundError in spec loading).

- [ ] **Step 3: Create `manager.py` with this exact content**

```python
"""Launch, health-check, and supervise multiple Eden bot instances.

Example accounts.json:
[
  {"name": "main", "port": 1616, "auto_restart": true, "stale_restart_seconds": 900},
  {"name": "alt", "port": 1617, "auto_restart": true}
]
"""
from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent
ACCOUNTS = ROOT / "accounts.json"
RUNTIME = ROOT / "uma_runtime"
LOG_DIR = RUNTIME / "manager_logs"
STATUS_PATH = RUNTIME / "manager_status.json"


def load_accounts():
    if not ACCOUNTS.exists():
        sample = [
            {"name": "main", "port": 1616, "auto_restart": True, "stale_restart_seconds": 900},
            {"name": "alt", "port": 1617, "auto_restart": True, "stale_restart_seconds": 900},
        ]
        ACCOUNTS.write_text(json.dumps(sample, indent=2), encoding="utf-8")
        print(f"Created {ACCOUNTS}. Edit it, then run manager.py again.")
        return []
    data = json.loads(ACCOUNTS.read_text(encoding="utf-8"))
    if not isinstance(data, list):
        raise SystemExit("accounts.json must be a list of account objects")
    return data


def safe_name(value):
    return "".join(ch if ch.isalnum() or ch in "_-" else "_" for ch in str(value or "default")).strip("_") or "default"


def atomic_write_json(path: Path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    tmp.replace(path)


def write_instance_config(account):
    name = safe_name(account.get("name") or "default")
    port = int(account.get("port") or 1616)
    path = ROOT / f"{name}.json"
    current = {}
    if path.exists():
        try:
            current = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            backup = path.with_suffix(path.suffix + f".bad-{int(time.time())}")
            path.replace(backup)
            print(f"Invalid JSON in {path.name}; moved it to {backup.name}")
            current = {}
    current.update(account)
    current["name"] = name
    current["port"] = port
    atomic_write_json(path, current)
    return path, port


def start_child(account):
    cfg, port = write_instance_config(account)
    env = os.environ.copy()
    if account.get("stuck_turn_threshold"):
        env["UMA_STUCK_TURN_THRESHOLD"] = str(account.get("stuck_turn_threshold"))
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    log_path = LOG_DIR / f"{cfg.stem}.log"
    log = log_path.open("a", encoding="utf-8", buffering=1)
    log.write(f"\n--- start {time.strftime('%Y-%m-%d %H:%M:%S')} port={port} ---\n")
    cmd = [sys.executable, "main.py", str(cfg)]
    print(f"Starting {cfg.stem} on http://127.0.0.1:{port}  log={log_path}")
    proc = subprocess.Popen(cmd, cwd=str(ROOT), env=env, stdout=log, stderr=subprocess.STDOUT)
    return {
        "account": account,
        "config": cfg,
        "port": port,
        "proc": proc,
        "log": log,
        "log_path": str(log_path),
        "restarts": 0,
        "last_start": time.time(),
        "last_health": {},
        "last_health_at": 0,
        "last_health_error": "",
    }


def fetch_health(port: int, timeout: float = 6.0):
    url = f"http://127.0.0.1:{port}/api/health"
    with urllib.request.urlopen(url, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def stop_child(child, kill_after=6):
    proc = child["proc"]
    if proc.poll() is None:
        proc.terminate()
        deadline = time.time() + kill_after
        while time.time() < deadline and proc.poll() is None:
            time.sleep(0.25)
    if proc.poll() is None:
        proc.kill()
    try:
        child["log"].close()
    except Exception:
        pass


def restart_child(children, child, reason: str):
    account = child["account"]
    name = child["config"].stem
    print(f"Restarting {name}: {reason}")
    stop_child(child)
    child["restarts"] += 1
    delay = min(180, 5 * (2 ** min(child["restarts"] - 1, 5)))
    time.sleep(delay)
    replacement = start_child(account)
    replacement["restarts"] = child["restarts"]
    children[children.index(child)] = replacement


def write_status(children):
    rows = []
    for child in children:
        proc = child["proc"]
        rows.append({
            "name": child["config"].stem,
            "port": child["port"],
            "pid": proc.pid,
            "running": proc.poll() is None,
            "returncode": proc.returncode,
            "restarts": child["restarts"],
            "last_start": child["last_start"],
            "last_health_at": child.get("last_health_at", 0),
            "last_health_error": child.get("last_health_error", ""),
            "last_health": child.get("last_health", {}),
            "log_path": child.get("log_path", ""),
        })
    atomic_write_json(STATUS_PATH, {"updated_at": time.time(), "children": rows})


def main():
    accounts = load_accounts()
    if not accounts:
        return 1
    children = [start_child(account) for account in accounts]
    stopping = False

    def stop_all(*_):
        nonlocal stopping
        stopping = True
        print("Stopping bot instances...")
        for child in list(children):
            stop_child(child)
        write_status(children)
        raise SystemExit(0)

    signal.signal(signal.SIGINT, stop_all)
    signal.signal(signal.SIGTERM, stop_all)

    while True:
        for child in list(children):
            proc = child["proc"]
            account = child["account"]
            auto_restart = bool(account.get("auto_restart", True))
            name = child["config"].stem

            if proc.poll() is not None:
                runtime = time.time() - child["last_start"]
                print(f"{name} exited with code {proc.returncode} after {int(runtime)}s")
                try:
                    child["log"].close()
                except Exception:
                    pass
                if stopping or not auto_restart:
                    children.remove(child)
                    continue
                restart_child(children, child, f"process exited code={proc.returncode}")
                continue

            interval = int(account.get("health_check_interval_seconds") or 30)
            if time.time() - float(child.get("last_health_at") or 0) >= interval:
                try:
                    health = fetch_health(child["port"])
                    child["last_health"] = health
                    child["last_health_error"] = ""
                    child["last_health_at"] = time.time()
                    stale_limit = int(account.get("stale_restart_seconds") or 0)
                    stale = int(health.get("runner_stale_seconds") or 0)
                    runner_running = bool(health.get("runner_running"))
                    if auto_restart and stale_limit > 0 and runner_running and stale >= stale_limit:
                        restart_child(children, child, f"runner stale for {stale}s")
                except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, OSError) as exc:
                    child["last_health_error"] = str(exc)
                    child["last_health_at"] = time.time()
                    grace = int(account.get("startup_grace_seconds") or 120)
                    if auto_restart and (time.time() - child["last_start"]) > grace:
                        failures = int(child.setdefault("health_failures", 0)) + 1
                        child["health_failures"] = failures
                        if failures >= int(account.get("health_failure_restart_count") or 5):
                            restart_child(children, child, f"health endpoint failed {failures} times: {exc}")
                    continue
                child["health_failures"] = 0

        write_status(children)
        if not children:
            return 0
        time.sleep(5)


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_manager.py -v`
Expected: PASS (2 passed)

- [ ] **Step 5: Commit**

```bash
git add manager.py tests/test_manager.py
git commit -m "feat: port multi-instance supervisor (manager.py)"
```

### Task 7: Full-suite regression + .gitignore for runtime artifacts

**Files:**
- Modify: `.gitignore`

- [ ] **Step 1: Ignore manager runtime artifacts**

Append to `.gitignore`:

```
accounts.json
*.json.bad-*
uma_runtime/manager_logs/
uma_runtime/manager_status.json
```

(Per-instance `<name>.json` configs contain ports/hardware and should not be committed; `accounts.json` is user-specific.)

- [ ] **Step 2: Run the full suite**

Run: `python -m pytest -q`
Expected: all prior baseline tests still pass, plus the new `test_p0_baseline.py`, `test_runner_heartbeat.py`, `test_cluster.py`, `test_manager.py`.

- [ ] **Step 3: Commit**

```bash
git add .gitignore
git commit -m "chore: ignore multi-account runtime artifacts"
```

---

## Self-Review notes

- **Spec coverage:** P0 (baseline, comparison matrix, shadow harness) → Tasks 0–2. P1 (`/api/health`, `accounts.json` API, `manager.py`, runner heartbeat) → Tasks 3–7. Covered.
- **Type consistency:** `build_health_payload` emits `runner_stale_seconds` and `runner_running`, the exact keys `manager.py` reads in its stale-restart check. `read_accounts_config`/`write_accounts_config`/`validate_accounts_config` signatures are consistent across `cluster.py` and `main.py` call sites.
- **No placeholders:** every code step contains full content; `manager.py` is reproduced in full.
- **Manual gap (documented, not automatable here):** Task 5 endpoints depend on `main.py` globals (`career_runner`, `active_client`, `PROFILE_NAME`, `PORT`, `DIR`) — all confirmed present in Eden's `main.py`. End-to-end verification of the live endpoints happens in P9 (running instance), since importing `main.py` in unit tests requires `frida`.
