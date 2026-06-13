import sys, types, threading, time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

# ---- stub heavy/Windows-only deps before imports ----
for name in ("curl_cffi",):
    if name not in sys.modules:
        m = types.ModuleType(name)
        m.requests = types.SimpleNamespace(Session=lambda: types.SimpleNamespace(headers={}, post=None, close=lambda: None))
        sys.modules[name] = m

import career_bot.delay as delay
delay.dna_sleep = lambda *a, **k: None  # no real sleeping in tests

from career_bot.runner import CareerRunner

class Decision:
    def __init__(self, action, payload=None, reason=""):
        self.action, self.payload, self.reason = action, payload or {}, reason

def make_runner():
    r = CareerRunner(str(ROOT))
    r.report = None
    return r

# ---------- Phase 1: _race_progress never returns junk state ----------

def test_race_progress_returns_fresh_state_on_graceful_exit():
    r = make_runner()
    fresh = {"data": {"chara_info": {"turn": 61, "playing_state": 1}}}
    class C:
        def race_out(self, current_turn):
            raise Exception("API error 102 on race_out")
        def race_end(self, current_turn):
            raise Exception("API error 102 on race_end")
        def race_start(self, is_short, current_turn):
            return {}
        def load_career(self):
            return fresh
    payload = {"current_turn": 60, "phase": "end", "chara_info": {"playing_state": 2}}
    out = r._race_progress(C(), payload, None)
    assert (out.get("data") or {}).get("chara_info", {}).get("turn") == 61

def test_race_progress_not_in_race_refreshes():
    r = make_runner()
    fresh = {"data": {"chara_info": {"turn": 5}}}
    class C:
        def load_career(self):
            return fresh
    out = r._race_progress(C(), {"current_turn": 5, "chara_info": {"playing_state": 1}}, None)
    assert out is fresh

# ---------- Phase 1: main loop survives state without chara_info ----------

def test_run_loop_recovers_from_chara_less_state():
    r = make_runner()
    good = {"data": {"chara_info": {"turn": 60, "playing_state": 1, "vital": 50, "max_vital": 100}}}
    calls = []
    class C:
        def load_career(self):
            calls.append("load")
            return good
        def wait_turn_delay(self):
            pass
    class S:
        def next_decision(self, state, preset):
            return Decision("idle", {}, "test stop")
        def _choice(self, e):
            return 1
    # state lacking chara_info entirely (e.g. race_out response)
    r.status["running"] = True
    r._run(C(), {"name": "t", "scenario_id": 4}, {"data": {}}, S(), max_steps=3)
    assert "load" in calls, "should refresh when chara_info missing"
    assert r.status["last_error"] == "", f"unexpected error: {r.status['last_error']}"

def test_record_action_without_current_turn_does_not_crash():
    r = make_runner()
    r._record_action(Decision("race", {"program_id": 101}), {"turn": 33})
    assert r.status["action_history"][-1]["turn"] == 33

# ---------- Phase 1: race entry 208 reconciliation ----------

def test_race_entry_208_resumes_when_server_entered_race():
    r = make_runner()
    rejected = []
    r.race_planner.reject = lambda turn, pid: rejected.append(pid)
    fresh = {"data": {"chara_info": {"turn": 60, "playing_state": 2}, "race_start_info": {"program_id": 7}}}
    class C:
        api_jitter = 0.0
        def race_entry(self, **kw):
            raise Exception("API error 208 on single_mode_free/race_entry")
        def load_career(self):
            return fresh
    out = r._race(C(), {"data": {}}, {"scenario_id": 4}, {"program_id": 7, "current_turn": 60})
    assert out is fresh
    assert rejected == [], "must not reject a race that actually entered"

def test_race_entry_208_rejects_when_not_in_race():
    r = make_runner()
    rejected = []
    r.race_planner.reject = lambda turn, pid: rejected.append(pid)
    fresh = {"data": {"chara_info": {"turn": 60, "playing_state": 1}}}
    class C:
        api_jitter = 0.0
        def race_entry(self, **kw):
            raise Exception("API error 208 on single_mode_free/race_entry")
        def load_career(self):
            return fresh
    out = r._race(C(), {"data": {}}, {"scenario_id": 4}, {"program_id": 7, "current_turn": 60})
    assert out is fresh
    assert rejected == [7]

# ---------- Phase 2: client retry loop ----------

import uma_api.client as uc

def make_client():
    c = uc.UmaClient.__new__(uc.UmaClient)
    c.viewer_id = 1
    c.udid_str = "00000000-0000-0000-0000-000000000000"
    c.auth_key_hex = ""
    c.steam_id = ""
    c.steam_ticket = ""
    c.device_id = "x"; c.device_name = "x"; c.graphics_device = "x"
    c.ip_address = "1.1.1.1"; c.platform_os = "x"; c.locale = "JPN"
    c.unity_ver = "u"; c.app_ver = ""; c.res_ver = ""
    c.sid = bytes(16)
    c.cached_load_data = {}; c.tp_info = {}; c.coin_info = {}; c.item_map = {}
    c.current_scenario_id = None
    c.on_api_log = None
    c.trace_file = None
    c.api_jitter = 0.0
    return c

class FakeResp:
    def __init__(self, status=200, text="x"):
        self.status_code = status
        self.text = text

def run_call(c, responses, rcs):
    """responses: list of FakeResp; rcs: result_code per successful unpack"""
    seq = {"i": 0, "j": 0}
    def post(url, data=None, headers=None, timeout=None):
        r = responses[min(seq["i"], len(responses) - 1)]
        seq["i"] += 1
        if isinstance(r, Exception):
            raise r
        return r
    c.session = types.SimpleNamespace(post=post, headers={})
    real_unpack = uc.unpack
    def fake_unpack(text, udid):
        rc = rcs[min(seq["j"], len(rcs) - 1)]
        seq["j"] += 1
        return {"data_headers": {"result_code": rc, "sid": "abc"}, "data": {}}
    uc.unpack = fake_unpack
    uc.dna_sleep = lambda *a, **k: None
    try:
        return c.call("single_mode_free/race_entry", {}), seq
    finally:
        uc.unpack = real_unpack

def test_call_retries_205_then_succeeds():
    c = make_client()
    res, seq = run_call(c, [FakeResp()], [205, 205, 1])
    assert res["data_headers"]["result_code"] == 1
    assert seq["j"] == 3

def test_call_retries_208_then_succeeds():
    c = make_client()
    res, seq = run_call(c, [FakeResp()], [208, 208, 1])
    assert res["data_headers"]["result_code"] == 1

def test_call_205_budget_not_reset_by_208():
    c = make_client()
    # alternate 208/205 forever -> must terminate with an exception, not loop
    try:
        res, seq = run_call(c, [FakeResp()], [208, 205, 208, 205, 208, 205, 208, 205, 208, 205, 208, 205, 208, 205, 208, 205, 205, 205, 205])
        raised = False
    except Exception:
        raised = True
    assert raised, "alternating 205/208 must eventually raise once budgets are spent"

def test_call_retries_http_5xx():
    c = make_client()
    res, seq = run_call(c, [FakeResp(500, "boom"), FakeResp(503, "busy"), FakeResp()], [1])
    assert res["data_headers"]["result_code"] == 1
    assert seq["i"] == 3

def test_call_http_5xx_budget_exhausted_raises():
    c = make_client()
    try:
        run_call(c, [FakeResp(500, "boom")], [1])
        raised = False
    except Exception as e:
        raised = "HTTP 500" in str(e)
    assert raised

def test_call_network_error_retry():
    c = make_client()
    res, seq = run_call(c, [ConnectionError("reset"), FakeResp()], [1])
    assert res["data_headers"]["result_code"] == 1

# ---------- Phase 3: safe_public_path (extracted from main.py source) ----------

def _load_safe_public_path(tmp_base):
    import ast, textwrap
    src = (ROOT / "main.py").read_text(encoding="utf-8", errors="replace")
    tree = ast.parse(src)
    fn = next(n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == "safe_public_path")
    code = ast.get_source_segment(src, fn)
    ns = {"base_dir": tmp_base, "Path": Path}
    exec(compile(textwrap.dedent(code), "main.py", "exec"), ns)
    return ns["safe_public_path"]

def test_safe_public_path_blocks_traversal(tmp_path):
    (tmp_path / "public" / "races").mkdir(parents=True)
    (tmp_path / "public" / "races" / "ok.png").write_text("x")
    (tmp_path / "secret.txt").write_text("top secret")
    fn = _load_safe_public_path(tmp_path)
    assert fn("races", "ok.png") is not None
    assert fn("races", "../../secret.txt") is None
    assert fn("races", "..\\..\\secret.txt") is None
    assert fn("races", "nope.png") is None

def test_call_retries_394_then_succeeds():
    c = make_client()
    res, seq = run_call(c, [FakeResp()], [394, 394, 1])
    assert res["data_headers"]["result_code"] == 1

def test_race_entry_event_drain_394_recovers():
    r = make_runner()
    fresh = {"data": {"chara_info": {"turn": 61, "playing_state": 1}}}
    class C:
        api_jitter = 0.0
        def race_entry(self, **kw):
            return {"data": {"unchecked_event_array": [{"event_id": 1}], "race_start_info": {}}}
        def check_event(self, **kw):
            raise Exception("API error 394 on single_mode_free/check_event")
        def load_career(self):
            return fresh
    class S:
        def _choice(self, e):
            return 1
        def choose_from_event(self, e, t):
            return 1
    out = r._race(C(), {"data": {}}, {"scenario_id": 4}, {"program_id": 7, "current_turn": 60, "_strategy": S()})
    assert out is fresh, "should refresh instead of crashing on 394"
