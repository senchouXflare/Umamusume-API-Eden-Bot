"""Steam Guard (2FA) ticket flow tests.

Bug fixed: the node helper passed the guard code only as twoFactorCode,
which Steam ignores for EMAIL-guard accounts -> endless "2FA REQUIRED".
The code must be delivered via the steamGuard event callback, which works
for both email and mobile authenticator accounts.
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


# ---------- node helper script contract ----------

def test_js_does_not_preset_twofactorcode():
    js = client_mod.TICKET_GEN_JS
    assert "loginOpts.twoFactorCode = code" not in js, (
        "code must go through the steamGuard callback, not twoFactorCode "
        "(email-guard accounts reject twoFactorCode)"
    )

def test_js_submits_code_via_steamguard_callback():
    js = client_mod.TICKET_GEN_JS
    assert "callback(code)" in js
    assert "lastCodeWrong" in js
    assert "wrong_code" in js  # signal for the backend

def test_js_exits_2_when_no_code_or_wrong_code():
    js = client_mod.TICKET_GEN_JS
    assert "process.exit(2)" in js
    assert "NEED_GUARD:" in js


# ---------- get_ticket exit-code handling ----------

def run_get_ticket_with(returncode, stdout="", stderr=""):
    client_mod.check_deps = lambda: None
    client_mod.subprocess = types.SimpleNamespace(
        run=lambda *a, **k: types.SimpleNamespace(
            returncode=returncode, stdout=stdout, stderr=stderr
        )
    )
    return client_mod.get_ticket("user", "pass", "T75DX")

def test_exit2_plain_raises_guard_required():
    try:
        run_get_ticket_with(2, stderr="NEED_GUARD:2fa\n")
    except Exception as e:
        assert str(e) == "STEAM_GUARD_REQUIRED"
    else:
        raise AssertionError("expected STEAM_GUARD_REQUIRED")

def test_exit2_wrong_code_raises_wrong_code():
    try:
        run_get_ticket_with(2, stderr="NEED_GUARD:wrong_code:2fa\n")
    except Exception as e:
        assert str(e) == "STEAM_GUARD_WRONG_CODE"
    else:
        raise AssertionError("expected STEAM_GUARD_WRONG_CODE")

def test_success_returns_ids():
    sid, tkt = run_get_ticket_with(
        0, stdout='{"steam_id": "765611", "session_ticket": "AB12"}\n'
    )
    assert sid == "765611" and tkt == "AB12"


# ---------- backend / frontend contract ----------

def test_login_endpoint_maps_wrong_code_to_detail():
    src = (ROOT / "main.py").read_text(encoding="utf-8", errors="replace")
    assert "STEAM_GUARD_WRONG_CODE" in src
    assert "WRONG GUARD CODE" in src

def test_frontend_shows_detail_on_2fa():
    app_js = (ROOT / "public" / "app.js").read_text(encoding="utf-8", errors="replace")
    assert "showTwoFactorPrompt(data.detail)" in app_js
    assert "message || '2FA REQUIRED'" in app_js
