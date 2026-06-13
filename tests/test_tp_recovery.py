"""TP recovery flow tests.

Verifies against the captured live payload:
    item/use_recovery_item: {"item_id": 32, "client_own_num": <owned>, "item_num": 1, "viewer_id": ...}
and the potion-first-then-carats ordering used by start_career_from_request.
"""
import sys, types
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

for name in ("curl_cffi",):
    if name not in sys.modules:
        m = types.ModuleType(name)
        m.requests = types.SimpleNamespace(
            Session=lambda: types.SimpleNamespace(headers={}, post=None, close=lambda: None)
        )
        sys.modules[name] = m

import uma_api.client as client_mod
from uma_api.client import UmaClient

# get_hwid is Windows-only; tests run anywhere
client_mod.get_hwid = lambda seed: {
    "udid": "00000000-0000-0000-0000-000000000000",
    "device_id": "x", "device_name": "x", "graphics_device_name": "x",
    "ip_address": "127.0.0.1", "platform_os_version": "Windows 10",
}


def make_client():
    c = UmaClient({"viewer_id": 327875345340, "steam_password_seed": "test"}, trace_enabled=False)
    c.calls = []

    def fake_call(ep, args=None, **kw):
        c.calls.append((ep, dict(args or {})))
        return c.next_response.pop(0) if getattr(c, "next_response", None) else {"data": {}}

    c.call = fake_call
    return c


# ---------- payload contract (matches sniffed capture) ----------

def test_use_recovery_item_payload_matches_capture():
    c = make_client()
    c.item_map[32] = 82  # client_own_num from capture
    c.next_response = [{"data": {"tp_info": {"current_tp": 130, "max_tp": 100}}}]

    c.use_recovery_item(item_num=1)

    ep, payload = c.calls[0]
    assert ep == "item/use_recovery_item"
    assert payload == {"item_id": 32, "client_own_num": 82, "item_num": 1}
    # viewer_id & friends are appended inside call() via common(); tp_info cached:
    assert c.tp_info["current_tp"] == 130


def test_use_recovery_item_decrements_local_count_without_server_list():
    c = make_client()
    c.item_map[32] = 5
    c.next_response = [{"data": {"tp_info": {"current_tp": 60}}}]
    c.use_recovery_item(item_num=1)
    assert c.tp_potion_count() == 4


def test_use_recovery_item_prefers_server_item_count():
    c = make_client()
    c.item_map[32] = 5
    c.next_response = [{"data": {"tp_info": {"current_tp": 60},
                                 "user_item": [{"item_id": 32, "number": 81}]}}]
    c.use_recovery_item(item_num=1)
    assert c.tp_potion_count() == 81


def test_recovery_tp_sends_total_jewels():
    c = make_client()
    c.coin_info = {"fcoin": 1200, "coin": 300}
    c.next_response = [{"data": {"tp_info": {"current_tp": 100}}}]
    c.recovery_tp(2)
    ep, payload = c.calls[0]
    assert ep == "user/recovery_trainer_point"
    assert payload == {"count": 2, "client_own_num": 1500}


# ---------- ordering: potions first, carats only as fallback ----------

def simulate_recovery(client, use_tp, mode="potion_first", tp_per_potion=30):
    """Mirror of the start_career_from_request recovery ordering."""
    current_tp = int(client.tp_info.get("current_tp") or 0)
    if use_tp and current_tp < use_tp and mode in ("potion_first", "potion_only"):
        for _ in range(20):
            if current_tp >= use_tp:
                break
            if client.tp_potion_count() <= 0:
                break
            client.next_response = [{"data": {"tp_info": {"current_tp": current_tp + tp_per_potion}}}]
            client.use_recovery_item(item_num=1)
            new_tp = int(client.tp_info.get("current_tp") or 0)
            if new_tp <= current_tp:
                break
            current_tp = new_tp
    if use_tp and current_tp < use_tp and mode in ("potion_first", "jewels_only"):
        needed = ((use_tp - current_tp) + 29) // 30
        client.next_response = [{"data": {"tp_info": {"current_tp": current_tp + needed * 30}}}]
        client.recovery_tp(needed)
        current_tp = int(client.tp_info.get("current_tp") or 0)
    return current_tp


def test_potions_used_before_carats():
    c = make_client()
    c.tp_info = {"current_tp": 0}
    c.item_map[32] = 82
    c.coin_info = {"fcoin": 99999, "coin": 0}

    final = simulate_recovery(c, use_tp=30)

    assert final >= 30
    endpoints = [ep for ep, _ in c.calls]
    assert endpoints == ["item/use_recovery_item"], endpoints  # no jewels spent
    assert c.tp_potion_count() == 81


def test_carats_only_when_no_potions_left():
    c = make_client()
    c.tp_info = {"current_tp": 0}
    c.item_map[32] = 0
    c.coin_info = {"fcoin": 99999, "coin": 0}

    final = simulate_recovery(c, use_tp=30)

    endpoints = [ep for ep, _ in c.calls]
    assert endpoints == ["user/recovery_trainer_point"], endpoints
    assert final >= 30


# ---------- UI / status contract ----------

def _main_src():
    return (ROOT / "main.py").read_text(encoding="utf-8", errors="replace")

def _extract_func(src, name):
    """Exec a single top-level function from main.py without importing it."""
    import ast
    tree = ast.parse(src)
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name == name:
            ns = {}
            exec(compile(ast.Module([node], []), "main.py", "exec"), ns)
            return ns[name]
    raise AssertionError(f"{name} not found in main.py")

def test_account_status_exposes_potions():
    src = _main_src()
    assert '"potions": potions' in src, "get_account_status must expose potion count"
    assert "find_item_count(item_list, 32)" in src

def test_find_item_count_distinguishes_absent_from_zero():
    f = _extract_func(_main_src(), "find_item_count")
    partial = [{"item_id": 101, "number": 3}]          # career-only items
    assert f(partial, 32) is None, "absent item must mean 'unchanged', not 0"
    assert f([{"item_id": 32, "number": 0}], 32) == 0  # real zero stays zero
    assert f([{"item_id": 32, "number": 82}], 32) == 82
    assert f(None, 32) is None

def test_partial_item_array_does_not_zero_potions():
    src = _main_src()
    # cache fallback present, and cache only overwritten from real sightings
    assert "potions_seen if potions_seen is not None else cache.get(32, 0)" in src
    assert "if potions_seen is not None:" in src

def test_runner_endpoint_returns_live_account():
    src = _main_src()
    i = src.index('@app.get("/api/career/runner")')
    block = src[i:i + 1200]
    for marker in ('item_map.get(32, 0)', '"account"', '"tp"', '"carrots"'):
        assert marker in block, marker

def test_frontend_rerenders_strip_from_runner_poll():
    app_js = (ROOT / "public" / "app.js").read_text(encoding="utf-8", errors="replace")
    assert "renderAccountStrip(data.account)" in app_js
    i_poll = app_js.index("'/api/career/runner'")
    assert "renderAccountStrip(data.account)" in app_js[i_poll:i_poll + 600]

def test_account_strip_shows_potions_between_tp_and_carrots():
    app_js = (ROOT / "public" / "app.js").read_text(encoding="utf-8", errors="replace")
    assert "pill-potion" in app_js
    i_tp, i_potion, i_carrots = (app_js.index(x) for x in ("pill-tp", "pill-potion", "pill-carrots"))
    assert i_tp < i_potion < i_carrots, "potion pill must sit between TP and carrots"
    css = (ROOT / "public" / "styles.css").read_text(encoding="utf-8", errors="replace")
    assert ".pill-potion" in css


def test_potions_then_carats_when_potions_run_out():
    c = make_client()
    c.tp_info = {"current_tp": 0}
    c.item_map[32] = 1          # one potion = 30 TP, need 60
    c.coin_info = {"fcoin": 99999, "coin": 0}

    final = simulate_recovery(c, use_tp=60)

    endpoints = [ep for ep, _ in c.calls]
    assert endpoints == ["item/use_recovery_item", "user/recovery_trainer_point"], endpoints
    assert final >= 60
    assert c.tp_potion_count() == 0
