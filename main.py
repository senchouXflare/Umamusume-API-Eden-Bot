import os
import json
import re
import subprocess
import sys

try:
    subprocess.run(
        [sys.executable, "-m", "pip", "install", "-r", "requirements.txt"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        check=True,
    )
except Exception:
    pass

from fastapi import FastAPI, HTTPException
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, HTMLResponse
from pydantic import BaseModel
from pathlib import Path
import random
import time
import threading
import frida
from career_bot import master_data
from career_bot.presets import PresetStore
from career_bot.runner import CareerRunner
from uma_api.client import UmaClient, get_ticket, LAST_TICKET_GEN_RESULT as _ltkr_ref
import uma_api.client as _uma_client_mod

PROCESS_NAME = "UmamusumePrettyDerby.exe"
APP_ID = "3224770"

JS_CODE = r"""
'use strict';
(function() {
    var buffers = {};
    var attached = {};
    function hex2(n) { return ('0' + (n & 255).toString(16)).slice(-2); }
    function uuidFromHex(h) {
        return h.substring(0, 8) + '-' + h.substring(8, 12) + '-' + h.substring(12, 16) + '-' + h.substring(16, 20) + '-' + h.substring(20);
    }
    function b64(s) {
        var chars = 'ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/';
        var out = [];
        var buffer = 0;
        var bits = 0;
        for (var i = 0; i < s.length; i++) {
            var c = s.charAt(i);
            if (c === '=') break;
            var idx = chars.indexOf(c);
            if (idx < 0) continue;
            buffer = (buffer << 6) | idx;
            bits += 6;
            if (bits >= 8) {
                bits -= 8;
                out.push((buffer >> bits) & 255);
            }
        }
        return out;
    }
    function parseWire(endpoint, viewerId, body, appVer, resVer) {
        var decoded = b64(body);
        if (decoded.length < 140) return;
        var headerLen = decoded[0] | (decoded[1] << 8) | (decoded[2] << 16) | (decoded[3] << 24);
        var blob1End = 4 + headerLen;
        if (headerLen < 120 || headerLen > 2048 || decoded.length < blob1End) return;
        
        var udidHex = '';
        for (var i = blob1End - 96; i < blob1End - 80; i++) udidHex += hex2(decoded[i]);
        var authHex = '';
        for (var j = blob1End - 48; j < blob1End; j++) authHex += hex2(decoded[j]);
        
        if (!viewerId || !authHex || authHex.length < 64 || udidHex.length !== 32) return;
        
        send({
            type: 'creds',
            endpoint: endpoint,
            viewer_id: parseInt(viewerId, 10),
            udid: uuidFromHex(udidHex),
            auth_key: authHex,
            auth_key_len: authHex.length / 2,
            app_ver: appVer,
            res_ver: resVer,
            body: body
        });
    }
    function parseHttp(text) {
        if (text.indexOf('/umamusume/') < 0) return;
        var em = text.match(/POST\s+\/umamusume\/([^\s]+)\s+HTTP/i);
        var vm = text.match(/(?:^|\r\n)(?:ViewerID|ViewerId):\s*(\d+)/i);
        var appVer = text.match(/(?:^|\r\n)APP-VER:\s*([^\r\n]+)/i);
        var resVer = text.match(/(?:^|\r\n)RES-VER:\s*([^\r\n]+)/i);
        var idx = text.indexOf('\r\n\r\n');
        if (!em || !vm || idx < 0) return;
        parseWire(em[1], vm[1], text.substring(idx + 4), appVer ? appVer[1].trim() : '', resVer ? resVer[1].trim() : '');
    }
    function parseChunk(key, chunk) {
        var buf = (buffers[key] || '') + chunk;
        if (buf.length > 2097152) buf = buf.substring(buf.length - 1048576);
        var start = buf.indexOf('POST ');
        if (start < 0) {
            buffers[key] = buf.slice(-4096);
            return;
        }
        if (start > 0) buf = buf.substring(start);
        var headerEnd = buf.indexOf('\r\n\r\n');
        if (headerEnd < 0) {
            buffers[key] = buf;
            return;
        }
        var headers = buf.substring(0, headerEnd);
        var lm = headers.match(/Content-Length:\s*(\d+)/i);
        var length = lm ? parseInt(lm[1], 10) : 0;
        var total = headerEnd + 4 + length;
        if (length > 0 && buf.length < total) {
            buffers[key] = buf;
            return;
        }
        parseHttp(length > 0 ? buf.substring(0, total) : buf);
        buffers[key] = buf.length > total ? buf.substring(total) : '';
    }
    function hookTls() {
        var ga = Process.findModuleByName('GameAssembly.dll');
        if (!ga) return false;
        var installFn = ga.findExportByName('il2cpp_unity_install_unitytls_interface');
        if (!installFn) return false;
        var rb = new Uint8Array(installFn.readByteArray(16));
        var realFn = installFn;
        if (rb[0] === 0xe9) {
            var off = rb[1] | (rb[2] << 8) | (rb[3] << 16) | (rb[4] << 24);
            if (off > 0x7fffffff) off -= 0x100000000;
            realFn = installFn.add(5 + off);
            rb = new Uint8Array(realFn.readByteArray(16));
        }
        var globalPtr = null;
        if (rb[0] === 0x48 && rb[1] === 0x89 && rb[2] === 0x0d) {
            var disp = rb[3] | (rb[4] << 8) | (rb[5] << 16) | (rb[6] << 24);
            if (disp > 0x7fffffff) disp -= 0x100000000;
            globalPtr = realFn.add(7 + disp);
        }
        if (!globalPtr) return false;
        var iface = globalPtr.readPointer();
        if (!iface || iface.isNull()) return false;
        var hookedTls = 0;
        [0xd0, 0xd8, 0xe0, 0xe8].forEach(function(off) {
            var addr = iface.add(off).readPointer();
            if (!addr || addr.isNull()) return;
            var key = 'tls_' + addr.toString();
            if (attached[key]) return;
            try {
                Interceptor.attach(addr, {
                    onEnter: function(args) {
                        var len = args[2].toInt32();
                        if (len <= 0 || len > 1048576 || args[1].isNull()) return;
                        try {
                            var bytes = args[1].readByteArray(len);
                            var u8 = new Uint8Array(bytes);
                            var s = '';
                            for (var i = 0; i < u8.length; i++) s += String.fromCharCode(u8[i]);
                            parseChunk(args[0].toString(), s);
                        } catch (e) {}
                    }
                });
                attached[key] = true;
                hookedTls++;
            } catch (e) {}
        });
        return hookedTls > 0;
    }
    var tlsDone = false;
    var timer = setInterval(function() {
        try {
            if (!tlsDone) tlsDone = hookTls();
            if (tlsDone) clearInterval(timer);
        } catch (e) {}
    }, 1000);
})();
"""


DIR = os.path.dirname(os.path.abspath(__file__))

PROFILE_NAME = "default"
INSTANCE_CONFIG = {}
PORT = 1616

import base64


def _obfuscate_creds(s):
    if not s or not isinstance(s, str) or s.startswith("enc:"):
        return s
    return "enc:" + base64.b64encode(s[::-1].encode("utf-8")).decode("utf-8")


def _deobfuscate_creds(s):
    if not s or not isinstance(s, str) or not s.startswith("enc:"):
        return s
    try:
        return base64.b64decode(s[4:]).decode("utf-8")[::-1]
    except Exception:
        return s


def generate_spoofed_hardware(profile_name):
    import hashlib
    import uuid
    import random

    h = hashlib.sha256(profile_name.encode("utf-8")).hexdigest()
    rng = random.Random(h)
    gpus = [
        "NVIDIA GeForce RTX 3060",
        "NVIDIA GeForce RTX 3070",
        "NVIDIA GeForce RTX 3080",
        "NVIDIA GeForce RTX 4090",
        "AMD Radeon RX 6700 XT",
        "AMD Radeon RX 6800 XT",
    ]
    ip_addr = f"192.168.{rng.randint(1, 254)}.{rng.randint(1, 254)}"
    dev_name = (
        f"DESKTOP-{''.join(rng.choices('ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789', k=7))}"
    )
    return {
        "device_name": dev_name,
        "graphics_device_name": rng.choice(gpus),
        "platform_os_version": "Windows 10  (10.0.19045) 64bit",
        "ip_address": ip_addr,
    }


if len(sys.argv) > 1 and sys.argv[1].endswith(".json"):
    config_path = sys.argv[1]
    PROFILE_NAME = os.path.splitext(os.path.basename(config_path))[0]

    needs_save = False
    if os.path.exists(config_path):
        with open(config_path, "r", encoding="utf-8") as f:
            try:
                INSTANCE_CONFIG = json.load(f)
            except Exception:
                INSTANCE_CONFIG = {}
    else:
        needs_save = True

    if "port" not in INSTANCE_CONFIG:
        used_ports = set()
        for fname in os.listdir(DIR):
            if fname.endswith(".json"):
                try:
                    with open(os.path.join(DIR, fname), "r", encoding="utf-8") as f:
                        cfg = json.load(f)
                        if (
                            isinstance(cfg, dict)
                            and "port" in cfg
                            and isinstance(cfg["port"], int)
                        ):
                            used_ports.add(cfg["port"])
                except Exception:
                    pass

        assign_port = PORT
        while assign_port in used_ports:
            assign_port += 1

        INSTANCE_CONFIG["port"] = assign_port
        needs_save = True

    PORT = INSTANCE_CONFIG["port"]

    # Auto-fill missing hardware details for consistency per instance
    spoofed = generate_spoofed_hardware(PROFILE_NAME)
    for key in [
        "device_name",
        "graphics_device_name",
        "platform_os_version",
        "ip_address",
    ]:
        if key not in INSTANCE_CONFIG:
            INSTANCE_CONFIG[key] = spoofed[key]
            needs_save = True

    if needs_save:
        with open(config_path, "w", encoding="utf-8") as f:
            json.dump(INSTANCE_CONFIG, f, indent=4)

RUNTIME_DIR = os.path.join(DIR, "uma_runtime", PROFILE_NAME)
os.makedirs(RUNTIME_DIR, exist_ok=True)
os.environ["UMA_RUNTIME_DIR"] = RUNTIME_DIR

app = FastAPI()

chara_map = {}
support_map = {}
active_client = None
active_account = None
active_dashboard_data = None
active_start_state = {}
active_parent_cards = {}
active_parent_rank_points = {}
pending_game_auth_config = {}
raw_load_index_response = None
active_selection = {"deck": None, "friend": None, "trainee": None, "veterans": []}
state_lock = threading.Lock()  # guards cross-thread mutation of active_* globals
turn_delay_min_sec = 2.5
turn_delay_max_sec = 5.0
turn_delay_restore_min_sec = 2.5
turn_delay_restore_max_sec = 5.0
turn_delay_disabled = False
preset_store = PresetStore(DIR)
career_runner = CareerRunner(DIR)

base_dir = Path(__file__).parent.absolute()
master_data_startup_status = master_data.status(base_dir)
if master_data_startup_status.get("exists"):
    master_data_startup_result = master_data.generate(base_dir)
    if master_data_startup_result.get("success"):
        print(
            f"master.mdb data generated: {master_data_startup_status.get('master_mdb_path')}"
        )
    else:
        print(
            f"master.mdb data generation failed: {master_data_startup_result.get('detail')}"
        )
elif master_data_startup_status.get("requires_user_action"):
    print(
        f"master.mdb requires user action: {master_data_startup_status.get('master_mdb_path')}"
    )
chara_path = base_dir / "data" / "chara_list.json"
support_path = base_dir / "data" / "support_list.json"
images_dir = base_dir / "data" / "images"

if chara_path.exists():
    with open(chara_path, "r", encoding="utf-8") as f:
        chara_map = json.load(f)
if support_path.exists():
    with open(support_path, "r", encoding="utf-8") as f:
        support_map = json.load(f)


def display_support_type(value):
    return {"Friends": "Pal", "Wisdom": "Wit"}.get(value, value)


def normalize_turn_delay(min_value, max_value, disabled=False):
    left = max(0.0, float(min_value or 0.0))
    right = max(0.0, float(max_value or 0.0))
    if left > right:
        right = left
    if disabled:
        left = 0.0
        right = 0.0
    return left, right, bool(disabled)


def set_turn_delay(min_value, max_value, disabled=False):
    global turn_delay_min_sec, turn_delay_max_sec, turn_delay_restore_min_sec, turn_delay_restore_max_sec, turn_delay_disabled
    next_min, next_max, next_disabled = normalize_turn_delay(
        min_value, max_value, disabled
    )
    if not next_disabled:
        turn_delay_restore_min_sec = next_min
        turn_delay_restore_max_sec = next_max
    turn_delay_min_sec = next_min
    turn_delay_max_sec = next_max
    turn_delay_disabled = next_disabled
    return get_turn_delay()


def get_turn_delay():
    return {
        "success": True,
        "min": turn_delay_min_sec,
        "max": turn_delay_max_sec,
        "restore_min": turn_delay_restore_min_sec,
        "restore_max": turn_delay_restore_max_sec,
        "disabled": turn_delay_disabled,
    }


SETTINGS_PATH = os.path.join(DIR, "settings.json")
TP_RECOVERY_MODES = ("potion_first", "potion_only", "jewels_only")


def _read_settings():
    try:
        with open(SETTINGS_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
            return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _write_settings(data):
    try:
        with open(SETTINGS_PATH, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=4)
        return True
    except Exception as e:
        print(f"Failed to write settings.json: {e}")
        return False


def load_tp_recovery_mode():
    mode = _read_settings().get("tp_recovery", "potion_first")
    return mode if mode in TP_RECOVERY_MODES else "potion_first"


def set_tp_recovery_mode(mode):
    if mode not in TP_RECOVERY_MODES:
        mode = "potion_first"
    data = _read_settings()
    data["tp_recovery"] = mode
    _write_settings(data)
    return mode


import hashlib
import uuid

_mac_seed = str(uuid.getnode()).encode("utf-8")
_m_hash = int(hashlib.md5(_mac_seed).hexdigest()[:8], 16)
_m_rng = random.Random(_m_hash)
_T_M = [_m_rng.uniform(0.85, 1.15) for _ in range(7)]
_S_M = [_m_rng.uniform(0.9, 1.1) for _ in range(7)]
_C_P = random.uniform(2160, 2520)

GLOBAL_SESSION_JITTER = random.uniform(-0.08, 0.08)


def wait_for_game_turn_delay(delay_type="turn", endpoint=None):
    if turn_delay_disabled:
        return 0.0

    import math
    import random
    import time

    cycle_time = time.time() % _C_P
    fatigue = 1.0 + (math.sin((cycle_time / _C_P) * math.pi * 2) * 0.15)

    if delay_type == "api":
        target_mean = 0.6
        sigma = 0.5
        max_cap = 8.0
        min_cap = 0.1

        if endpoint:
            if any(
                endpoint.endswith(ep)
                for ep in ["tool/pre_signup", "tool/start_session"]
            ):
                seconds = random.uniform(0.011, 0.021)
                return seconds
            elif any(endpoint.endswith(ep) for ep in ["race_entry", "read_info/index"]):
                target_mean = 0.05 * _T_M[1]
                sigma = 0.3 * _S_M[1]
                min_cap = 0.025
                max_cap = 0.1
            elif any(
                endpoint.endswith(ep)
                for ep in [
                    "check_event",
                    "continue",
                    "race_end",
                    "race_out",
                    "minigame_end",
                    "mission/receive",
                    "start_career",
                ]
            ):
                target_mean = 1.5 * _T_M[2]
                sigma = 0.55 * _S_M[2]
                min_cap = 0.2
                max_cap = 4.6
            elif any(
                endpoint.endswith(ep)
                for ep in [
                    "load/index",
                    "home/index",
                    "single_mode_free/load",
                    "single_mode_free/start",
                    "tool/signup",
                    "user/recovery_trainer_point",
                ]
            ):
                target_mean = 3.6 * _T_M[3]
                sigma = 0.6 * _S_M[3]
                min_cap = 0.7
                max_cap = 18.0
            elif any(
                endpoint.endswith(ep)
                for ep in [
                    "exec_command",
                    "race_start",
                    "reserve_race",
                    "finish_career",
                    "finish",
                    "single_mode_free/pre",
                    "pre_single_mode/index",
                ]
            ):
                target_mean = 4.0 * _T_M[4]
                sigma = 0.65 * _S_M[4]
                min_cap = 1.0
                max_cap = 19.3
            elif any(
                endpoint.endswith(ep)
                for ep in [
                    "multi_item_use",
                    "multi_item_exchange",
                    "exchange/item",
                    "support_card/enhance",
                    "friend/add",
                ]
            ):
                target_mean = 7.0 * _T_M[5]
                sigma = 0.7 * _S_M[5]
                min_cap = 3.1
                max_cap = 17.0
            elif any(
                endpoint.endswith(ep)
                for ep in [
                    "gain_skills",
                    "chara/nickname",
                    "chara/talent",
                    "item/use",
                    "team/evaluation",
                ]
            ):
                target_mean = 30.0 * _T_M[6]
                sigma = 0.8 * _S_M[6]
                min_cap = 6.0
                max_cap = 75.0

        target_mean *= fatigue
        target_mean += GLOBAL_SESSION_JITTER * (target_mean * 0.5)
        target_mean = max(0.01, target_mean)

        mu = math.log(target_mean) - (sigma**2) / 2.0
        roll = random.lognormvariate(mu, sigma)
        seconds = min(max_cap, max(min_cap, roll))
        return seconds

    elif delay_type == "complex":
        range_span = turn_delay_max_sec - turn_delay_min_sec
        target_mean = (
            ((turn_delay_min_sec + turn_delay_max_sec) / 2.0)
            + (GLOBAL_SESSION_JITTER * range_span)
        ) * _T_M[0]
        target_mean = max(0.1, target_mean) * 2.0
        sigma = 1.1 * _S_M[0]
        mu = math.log(target_mean) - (sigma**2) / 2.0
        roll = random.lognormvariate(mu, sigma)
        seconds = min(45.0, max(turn_delay_min_sec * 0.2, roll))
        return seconds
    else:
        range_span = turn_delay_max_sec - turn_delay_min_sec
        target_mean = (
            ((turn_delay_min_sec + turn_delay_max_sec) / 2.0)
            + (GLOBAL_SESSION_JITTER * range_span)
        ) * _T_M[0]
        target_mean = max(0.1, target_mean)
        sigma = 0.75 * _S_M[0]
        mu = math.log(target_mean) - (sigma**2) / 2.0
        roll = random.lognormvariate(mu, sigma)
        seconds = min(turn_delay_max_sec * 5.0, max(turn_delay_min_sec * 0.5, roll))
        return seconds


def attach_turn_delay(client):
    if getattr(client, "_turn_delay_wrapped", False):
        return client

    client._last_api_call_ts = time.time()

    original_call = client.call

    def wrapped_call(ep, args=None, **kwargs):
        target_delay = wait_for_game_turn_delay(delay_type="api", endpoint=ep)
        elapsed = time.time() - client._last_api_call_ts
        if elapsed < target_delay:
            time.sleep(target_delay - elapsed)

        print(
            f"Last Endpoint: {ep.split('/')[-1]} | Delay: {target_delay:.3f}s",
            flush=True,
        )

        res = original_call(ep, args, **kwargs)
        client._last_api_call_ts = time.time()
        return res

    client.call = wrapped_call
    client.wait_turn_delay = lambda: time.sleep(
        wait_for_game_turn_delay(delay_type="turn")
    )
    client.wait_complex_delay = lambda: time.sleep(
        wait_for_game_turn_delay(delay_type="complex")
    )
    client._turn_delay_wrapped = True
    return client


def update_start_state(data):
    global active_start_state
    if not data:
        return
    if data.get("tp_info"):
        tp_info = dict(data.get("tp_info"))
        active_start_state["tp_info"] = tp_info
    item_list = data.get("item_list") or data.get("user_item_array")
    if isinstance(item_list, list) and item_list:
        active_start_state["current_money"] = get_item_count(item_list, 59)
        active_start_state["succession_rank_point"] = get_item_count(item_list, 75)


def normalize_friend_cards(data):
    source = "refresh"
    friend_data = data.get("friend_support_card_data")
    if friend_data:
        source = "initial"
        summaries = friend_data.get("summary_user_info_array", [])
        support_cards = friend_data.get("support_card_data_array", [])
    else:
        summaries = data.get("summary_user_info_array", [])
        support_cards = data.get("support_card_data_array", [])

    support_by_key = {}
    for sc in support_cards or []:
        key = (sc.get("viewer_id"), sc.get("support_card_id"))
        support_by_key[key] = sc

    friends = []
    exclude_viewer_ids = []
    seen = set()
    for info in summaries or []:
        viewer_id = info.get("viewer_id")
        support_card_id = info.get("support_card_id")
        if not viewer_id or not support_card_id:
            continue
        key = (viewer_id, support_card_id)
        if key in seen:
            continue
        seen.add(key)
        exclude_viewer_ids.append(viewer_id)
        card_data = support_by_key.get(key) or info.get("user_support_card") or {}
        support_info = support_map.get(str(support_card_id), {})
        friends.append(
            {
                "viewer_id": viewer_id,
                "name": info.get("name", ""),
                "support_card_id": support_card_id,
                "support_name": support_info.get(
                    "name", f"Unknown ({support_card_id})"
                ),
                "rarity": support_info.get("rarity", "?"),
                "type": display_support_type(support_info.get("type", "Unknown")),
                "exp": card_data.get(
                    "exp", info.get("user_support_card", {}).get("exp")
                ),
                "limit_break_count": card_data.get(
                    "limit_break_count",
                    info.get("user_support_card", {}).get("limit_break_count"),
                ),
                "favorite_flag": card_data.get("favorite_flag", 0),
                "friend_state": info.get("friend_state", 0),
            }
        )
    return friends, exclude_viewer_ids, source


def normalize_card_name(name):
    return re.sub(r"[^a-z0-9]+", "", re.sub(r"\([^)]*\)", "", str(name or "").lower()))


def validate_start_selection(req):
    support_ids = [int(card_id) for card_id in req.support_card_ids]
    friend_card_id = int(req.friend_card_id)
    if friend_card_id in support_ids:
        return "Friend support card is already in selected deck"

    friend_info = support_map.get(str(friend_card_id), {})
    friend_name = normalize_card_name(friend_info.get("name"))
    if not friend_name:
        return None

    for support_id in support_ids:
        support_name = normalize_card_name(
            support_map.get(str(support_id), {}).get("name")
        )
        if support_name and support_name == friend_name:
            return "Friend support card has same character as selected deck"

    trainee_name = normalize_card_name(chara_map.get(str(req.card_id), ""))
    if trainee_name and trainee_name == friend_name:
        return "Friend support card has same character as trainee"

    if trainee_name:
        for support_id in support_ids:
            support_name = normalize_card_name(
                support_map.get(str(support_id), {}).get("name")
            )
            if support_name and support_name == trainee_name:
                return "Selected deck contains a support card with the same character as the trainee"

    parent1_cards = active_parent_cards.get(int(req.parent_id_1), [])
    parent2_cards = active_parent_cards.get(int(req.parent_id_2), [])
    if (
        parent1_cards
        and parent2_cards
        and int(req.card_id) in (parent1_cards[0], parent2_cards[0])
    ):
        return "Selected direct parent is same character as trainee"

    return None


def deck_type_counts_from_ids(support_ids, friend_card_id=0):
    counts = [0] * 5
    for sid_int in list(support_ids or []) + (
        [friend_card_id] if friend_card_id else []
    ):
        info = support_map.get(str(sid_int))
        if not info:
            continue
        ctype = info.get("type")
        if ctype == "Speed":
            counts[0] += 1
        elif ctype == "Stamina":
            counts[1] += 1
        elif ctype == "Power":
            counts[2] += 1
        elif ctype == "Guts":
            counts[3] += 1
        elif ctype == "Wisdom":
            counts[4] += 1
    return counts


def deck_type_counts_from_chara(chara_info):
    ids = []
    for card in (chara_info or {}).get("support_card_array") or []:
        sid = int(card.get("support_card_id") or 0)
        if sid:
            ids.append(sid)
    return deck_type_counts_from_ids(ids)


def apply_deck_type_counts(preset, req=None, chara_info=None):
    counts = None
    if req and (req.support_card_ids or req.friend_card_id):
        counts = deck_type_counts_from_ids(req.support_card_ids, req.friend_card_id)
    elif chara_info:
        counts = deck_type_counts_from_chara(chara_info)
    if counts is not None:
        preset["_deck_type_counts"] = counts
        scale_table = [0.0, 0.02, 0.05, 0.09, 0.14, 0.20]
        preset["_deck_multipliers"] = [1.0 + scale_table[min(5, c)] for c in counts]


def parent_rank_point(parent_id):
    parent = active_parent_rank_points.get(int(parent_id))
    if not parent:
        return 0

    rank = int(parent.get("rank") or 0)
    if rank == 13:
        return 62
    return int(parent.get("rank_point") or 0)


def selected_succession_rank_point(req):
    p1_pt = parent_rank_point(req.parent_id_1)
    p2_pt = parent_rank_point(req.parent_id_2)
    selected_total = p1_pt + p2_pt
    if selected_total in (0, 124):
        return selected_total
    return 0


skill_data = {}
skill_data_path = base_dir / "data" / "skill_data.json"
if skill_data_path.exists():
    with open(skill_data_path, "r", encoding="utf-8") as f:
        skill_data = json.load(f)

factor_map = {}
factor_map_path = base_dir / "data" / "factor_map.json"
if factor_map_path.exists():
    with open(factor_map_path, "r", encoding="utf-8") as f:
        factor_map = json.load(f)

race_map = {}
race_map_path = base_dir / "data" / "race_map.json"
if race_map_path.exists():
    with open(race_map_path, "r", encoding="utf-8") as f:
        race_map = json.load(f)


def skill_entry_name(entry):
    if isinstance(entry, dict):
        return entry.get("name") or ""
    return entry


def get_win_summary(win_saddle_ids):
    summary = {"g1": 0, "g2": 0, "g3": 0}

    for saddle_id in win_saddle_ids or []:
        race = race_map.get(str(saddle_id))
        grade = race.get("grade") if race else None
        if grade == "G1":
            summary["g1"] += 1
        elif grade == "G2":
            summary["g2"] += 1
        elif grade == "G3":
            summary["g3"] += 1

    summary["total"] = summary["g1"] + summary["g2"] + summary["g3"]
    return summary


def clean_factor_name(name, base_id=None, category=None):
    if not isinstance(name, str):
        return name

    if category == "skill" and "?" in name and base_id is not None:
        skill_name = skill_entry_name(skill_data.get(f"{base_id}2"))
        if skill_name:
            return skill_name
    return name.replace(" ?", " ○")


def get_factors(fid_array, owner_card_id=None):
    results = []
    category_order = {
        "stat": 0,
        "aptitude": 1,
        "unique": 2,
        "race": 3,
        "skill": 4,
        "scenario": 5,
        "other": 6,
    }
    stat_map = {
        1: "Speed",
        2: "Stamina",
        3: "Power",
        4: "Guts",
        5: "Wit",
        11: "Turf",
        12: "Dirt",
        21: "Short",
        22: "Mile",
        23: "Medium",
        24: "Long",
        31: "Front Runner",
        32: "Pace Chaser",
        33: "Late Surger",
        34: "End Closer",
    }

    owner_cid_str = str(owner_card_id) if owner_card_id else ""
    if len(owner_cid_str) > 4:
        owner_cid_str = owner_cid_str[:4]

    for fid in fid_array:
        if not fid or fid <= 0:
            continue

        fid_str = str(fid)
        factor_info = factor_map.get(fid_str)
        if factor_info:
            base_id = fid // 100
            category = factor_info.get("category", "other")
            name = clean_factor_name(
                factor_info.get("name", f"Unknown({fid})"), base_id, category
            )
            stars = factor_info.get("stars", fid % 100)
            results.append(
                {"name": name, "stars": stars, "id": fid, "category": category}
            )
            continue

        base_id = fid // 100
        stars = fid % 100
        bid_str = str(base_id)
        name = f"Unknown({base_id})"
        category = "other"

        if base_id <= 34:
            category = "stat" if base_id <= 5 else "aptitude"
            name = stat_map.get(base_id, name)

        elif bid_str in skill_data:
            category = "skill"
            name = skill_entry_name(skill_data[bid_str])

        results.append(
            {"name": name, "stars": stars, "id": base_id, "category": category}
        )

    return [
        factor
        for _, factor in sorted(
            enumerate(results),
            key=lambda item: (category_order.get(item[1]["category"], 99), item[0]),
        )
    ]


def get_chara_factor_ids(chara):
    factor_ids = chara.get("factor_id_array")
    if isinstance(factor_ids, list) and factor_ids:
        return factor_ids
    return [f.get("factor_id", 0) for f in chara.get("factor_info_array", [])]


def get_item_count(item_list, item_id):
    for item in item_list or []:
        if item.get("item_id") == item_id:
            return item.get("number", 0)
    return 0


def find_item_count(item_list, item_id):
    """Like get_item_count but returns None when the item is absent.

    Career responses often carry a PARTIAL user_item_array (career-scoped
    items only); an absent item means "unchanged", NOT zero.
    """
    for item in item_list or []:
        if item.get("item_id") == item_id:
            return int(item.get("number") or 0)
    return None


def get_account_status(data, career_data=None):
    tp_info = data.get("tp_info") or (active_client.tp_info if active_client else {})
    coin_info = data.get("coin_info") or (
        active_client.coin_info if active_client else {}
    )
    item_list = data.get("item_list") or data.get("user_item_array")
    # Only trust the list for items it actually contains; otherwise fall back
    # to the client cache (call() keeps it fresh from every response).
    cache = active_client.item_map if active_client else {}
    gold_seen = find_item_count(item_list, 59)
    potions_seen = find_item_count(item_list, 32)
    gold = gold_seen if gold_seen is not None else cache.get(59, 0)
    potions = potions_seen if potions_seen is not None else cache.get(32, 0)
    if active_client:
        if gold_seen is not None:
            active_client.item_map[59] = gold_seen
        if potions_seen is not None:
            active_client.item_map[32] = potions_seen
    career = data.get("single_mode_chara_light") or None

    if career_data:
        career_payload = (
            career_data.get("data") if career_data.get("data") else career_data
        )
        if career_payload.get("chara_info"):
            career = career_payload.get("chara_info")

    status = {
        "tp": {
            "current": tp_info.get("current_tp", 0),
            "max": tp_info.get("max_tp", 0),
        },
        "carrots": {
            "free": coin_info.get("fcoin", 0) or 0,
            "paid": coin_info.get("coin", 0) or 0,
            "total": (coin_info.get("fcoin", 0) or 0) + (coin_info.get("coin", 0) or 0),
        },
        "gold": gold,
        "potions": potions,
        "clocks": active_client.item_map.get(95, 0) if active_client else 0,
        "career": None,
    }
    if career:
        card_id = str(career.get("card_id", ""))

        p1 = career.get("succession_trained_chara_id_1")
        p2 = career.get("succession_trained_chara_id_2")

        friend_viewer_id = None
        friend_card_id = None
        friend_support = None
        current_deck_cards = []
        current_deck_supports = []

        support_array = career.get("support_card_array") or []
        for sc in support_array:
            pos = sc.get("position")
            if pos == 6:
                friend_viewer_id = sc.get("owner_viewer_id")
                friend_card_id = sc.get("support_card_id")
                friend_info = support_map.get(str(friend_card_id))
                friend_support = {
                    "viewer_id": friend_viewer_id,
                    "support_card_id": friend_card_id,
                    "support_name": (
                        friend_info["name"]
                        if friend_info
                        else f"Unknown ({friend_card_id})"
                    ),
                    "rarity": friend_info["rarity"] if friend_info else "?",
                    "type": (
                        display_support_type(friend_info["type"])
                        if friend_info
                        else "?"
                    ),
                    "limit_break_count": sc.get("limit_break_count"),
                }
            elif 1 <= pos <= 5:
                support_card_id = sc.get("support_card_id")
                current_deck_cards.append(support_card_id)
                support_info = support_map.get(str(support_card_id))
                current_deck_supports.append(
                    {
                        "id": str(support_card_id),
                        "name": (
                            support_info["name"]
                            if support_info
                            else f"Unknown ({support_card_id})"
                        ),
                        "rarity": support_info["rarity"] if support_info else "?",
                        "type": (
                            display_support_type(support_info["type"])
                            if support_info
                            else "?"
                        ),
                    }
                )

        matched_deck_id = None
        user_decks = data.get("support_card_deck_array") or []
        if current_deck_cards:
            current_deck_set = set(current_deck_cards)
            for deck in user_decks:
                deck_cards = deck.get("support_card_id_array") or []
                if set(deck_cards) == current_deck_set:
                    matched_deck_id = deck.get("deck_id")
                    break

        status["career"] = {
            "active": True,
            "card_id": card_id,
            "name": chara_map.get(card_id, f"Unknown ({card_id})"),
            "turn": career.get("turn", 0),
            "scenario_id": career.get("scenario_id", 0),
            "fans": career.get("fans", 0),
            "vital": career.get("vital", 0),
            "max_vital": career.get("max_vital", 0),
            "deck_id": matched_deck_id,
            "support_card_ids": current_deck_cards,
            "support_cards": current_deck_supports,
            "friend_viewer_id": friend_viewer_id,
            "friend_card_id": friend_card_id,
            "friend": friend_support,
            "parent_id_1": p1,
            "parent_id_2": p2,
        }

    return status


class LoginRequest(BaseModel):
    username: str = ""
    password: str = ""
    code: str = ""
    steam_id: str = ""
    steam_session_ticket: str = ""


class DeleteCareerRequest(BaseModel):
    current_turn: int = 0


class StartCareerRequest(BaseModel):
    card_id: int
    support_card_ids: list[int]
    friend_viewer_id: int
    friend_card_id: int
    parent_id_1: int
    parent_id_2: int
    scenario_id: int = 4
    deck_id: int = 1
    use_tp: int = 30
    difficulty_id: int = 0
    difficulty: int = 0
    is_boost: int = 0
    boost_story_event_id: int = 0
    burn_clocks: bool = False


class RunCareerRequest(BaseModel):
    card_id: int = 0
    support_card_ids: list[int] = []
    friend_viewer_id: int = 0
    friend_card_id: int = 0
    parent_id_1: int = 0
    parent_id_2: int = 0
    scenario_id: int = 4
    deck_id: int = 1
    use_tp: int = 30
    difficulty_id: int = 0
    difficulty: int = 0
    is_boost: int = 0
    boost_story_event_id: int = 0
    preset_name: str = ""
    max_steps: int = 2500
    burn_clocks: bool = False
    dev_mode: bool = False


class SaveRacesRequest(BaseModel):
    races: list[int]
    preset_name: str = ""


def resolve_preset(preset_name=""):
    """Resolve a preset by name with sane fallbacks (no hardcoded preset)."""
    name = (preset_name or "").strip()
    if name:
        preset = preset_store.read_one(name)
        if preset:
            return preset
    preset = preset_store.read_one("xguri parent")
    if preset:
        return preset
    all_presets = preset_store.read_all() or []
    return all_presets[0] if all_presets else None


class SavePresetRequest(BaseModel):
    preset: dict


class DeletePresetByNameRequest(BaseModel):
    name: str


class CareerActionRequest(BaseModel):
    command_type: int
    command_id: int
    current_turn: int
    current_vital: int
    command_group_id: int = 0
    select_id: int = 0


class FriendListRequest(BaseModel):
    exclude_viewer_ids: list[int] = []


class ApiDelayRequest(BaseModel):
    min: float = 1.6
    max: float = 4.0
    disabled: bool = False


class MasterDataPathRequest(BaseModel):
    master_mdb_path: str


@app.get("/api/settings/turn-delay")
async def get_turn_delay_settings():
    return get_turn_delay()


@app.post("/api/settings/turn-delay")
async def set_turn_delay_settings(req: ApiDelayRequest):
    return set_turn_delay(req.min, req.max, req.disabled)


class TpRecoveryRequest(BaseModel):
    mode: str = "potion_first"


@app.get("/api/settings/tp-recovery")
async def get_tp_recovery_settings():
    mode = load_tp_recovery_mode()
    potions = None
    if active_client is not None:
        try:
            potions = active_client.tp_potion_count()
        except Exception:
            potions = None
    return {"success": True, "mode": mode, "modes": list(TP_RECOVERY_MODES), "potions": potions}


@app.post("/api/settings/tp-recovery")
async def set_tp_recovery_settings(req: TpRecoveryRequest):
    return {"success": True, "mode": set_tp_recovery_mode(req.mode)}


@app.get("/api/master-data/status")
async def master_data_status():
    return master_data.status(base_dir)


@app.post("/api/master-data/path")
async def set_master_data_path(req: MasterDataPathRequest):
    status = master_data.set_master_mdb_path(base_dir, req.master_mdb_path)
    if status.get("exists"):
        result = master_data.generate(base_dir)
        if result.get("success"):
            status["generated"] = result.get("generated", [])
        else:
            status["generation_error"] = (
                result.get("detail") or "master_data generation failed"
            )
    return status


@app.post("/api/master-data/generate")
async def generate_master_data():
    result = master_data.generate(base_dir)
    if not result.get("success"):
        raise HTTPException(
            status_code=400,
            detail=result.get("detail") or "master_data generation failed",
        )
    return result


@app.post("/api/presets/save_races")
async def save_races(req: SaveRacesRequest):
    preset = resolve_preset(req.preset_name)
    if not preset:
        return {"success": False, "detail": "no preset available"}
    preset["extra_race_list"] = req.races
    preset_store.write(preset)
    return {"success": True, "preset": preset.get("name")}


@app.get("/api/presets")
async def get_presets():
    return {"success": True, "presets": preset_store.read_all()}


@app.post("/api/presets")
async def save_preset(req: SavePresetRequest):
    return {"success": True, "preset": preset_store.write(req.preset)}


@app.post("/api/presets/delete")
async def delete_preset(req: DeletePresetByNameRequest):
    return {"success": preset_store.delete(req.name)}


def start_career_from_request(req):
    global active_account, active_dashboard_data
    if not active_client:
        return {"success": False, "detail": "Not logged in"}
    if not req.friend_viewer_id or not req.friend_card_id:
        return {"success": False, "detail": "Friend support card is required"}
    selection_error = validate_start_selection(req)
    if selection_error:
        return {"success": False, "detail": selection_error}

    try:
        res = active_client.read_info()
        data = res.get("data", {})
        active_client.refresh_cached_account_state(data)
        update_start_state(data)
        if active_account:
            active_account = get_account_status(data)
            if active_dashboard_data:
                active_dashboard_data["account"] = active_account
    except Exception:
        pass

    if not active_start_state.get("tp_info"):
        return {
            "success": False,
            "detail": "Missing live TP state; login again before starting career",
        }
    if "current_money" not in active_start_state:
        return {
            "success": False,
            "detail": "Missing live item state; login again before starting career",
        }

    tp_info = active_start_state["tp_info"]
    current_tp = int(tp_info.get("current_tp") or 0)

    # TP recovery. Modes (settings.json -> "tp_recovery"):
    #   "potion_first" (default): drink TP potions first, fall back to jewels
    #   "potion_only": only use potions
    #   "jewels_only": only spend jewels (legacy behavior)
    tp_mode = load_tp_recovery_mode()

    if req.use_tp and current_tp < req.use_tp and tp_mode in ("potion_first", "potion_only"):
        for _ in range(20):  # cap potions per start
            if current_tp >= req.use_tp:
                break
            if active_client.tp_potion_count() <= 0:
                break
            try:
                active_client.use_recovery_item(item_num=1)
                tp_info = active_client.tp_info
                active_start_state["tp_info"] = tp_info
                new_tp = int(tp_info.get("current_tp") or 0)
                if new_tp <= current_tp:
                    break  # potion gave nothing (full or server refused) -> stop looping
                current_tp = new_tp
            except Exception as e:
                if "213" in str(e):
                    try:
                        res = active_client.call("load/index", {"adid": ""})
                        active_client.refresh_cached_account_state(res.get("data", {}))
                    except Exception:
                        pass
                else:
                    break
                time.sleep(1)

    if req.use_tp and current_tp < req.use_tp and tp_mode in ("potion_first", "jewels_only"):
        for attempt in range(3):
            try:
                needed = ((req.use_tp - current_tp) + 29) // 30
                active_client.recovery_tp(needed)
                tp_info = active_client.tp_info
                active_start_state["tp_info"] = tp_info
                current_tp = int(tp_info.get("current_tp") or 0)
                if current_tp >= req.use_tp:
                    break
            except Exception as e:
                if "213" in str(e):
                    try:
                        res = active_client.call("load/index", {"adid": ""})
                        active_client.refresh_cached_account_state(res.get("data", {}))
                    except Exception:
                        pass
                time.sleep(1)

    if req.use_tp and current_tp < req.use_tp:
        return {"success": False, "detail": f"Not enough TP: {current_tp}/{req.use_tp}"}

    current_money = active_start_state["current_money"]
    succession_rank_point = selected_succession_rank_point(req)

    try:
        active_client.pre_single_mode(
            [req.friend_viewer_id] if req.friend_viewer_id else []
        )
        time.sleep(random.uniform(0.5, 1.5))
    except Exception:
        pass

    result = active_client.start_career(
        card_id=req.card_id,
        support_card_ids=req.support_card_ids,
        friend_viewer_id=req.friend_viewer_id,
        friend_card_id=req.friend_card_id,
        parent_id_1=req.parent_id_1,
        parent_id_2=req.parent_id_2,
        scenario_id=req.scenario_id,
        deck_id=req.deck_id,
        use_tp=req.use_tp,
        tp_info=tp_info,
        current_money=current_money,
        succession_rank_point=succession_rank_point,
        difficulty_id=req.difficulty_id,
        difficulty=req.difficulty,
        is_boost=req.is_boost,
        boost_story_event_id=req.boost_story_event_id,
    )
    return {"success": True, "result": result}


def apply_career_result(result):
    global active_account, active_dashboard_data
    result_data = result.get("data", {})
    update_start_state(result_data)
    account = get_account_status(result_data, result)
    chara_info = result_data.get("chara_info") or {}
    if chara_info:
        account["career"] = account.get("career") or {}
        card_id = str(chara_info.get("card_id", account["career"].get("card_id", "")))
        account["career"].update(
            {
                "active": True,
                "card_id": card_id,
                "name": chara_map.get(card_id, f"Unknown ({card_id})"),
                "turn": chara_info.get("turn", 0),
                "scenario_id": chara_info.get("scenario_id", 0),
                "fans": chara_info.get("fans", 0),
                "vital": chara_info.get("vital", 0),
                "max_vital": chara_info.get("max_vital", 0),
            }
        )
    active_account = account
    if active_dashboard_data:
        active_dashboard_data["account"] = account
    return account, chara_info


@app.post("/api/login")
async def login(req: LoginRequest):
    global active_client, active_account, active_dashboard_data, active_start_state, active_parent_cards, active_parent_rank_points, pending_game_auth_config, raw_load_index_response, active_selection
    try:
        chara = None
        cfg = dict(pending_game_auth_config)
        pending_game_auth_config = {}

        # Fallback: if startup auto-login already consumed pending_game_auth_config,
        # reload game-auth fields from the saved auth_config.json so that
        # manual web-UI logins still work without re-running Frida capture.
        if not has_fresh_auth_config(cfg):
            _saved_path = os.path.join(RUNTIME_DIR, "auth_config.json")
            if os.path.exists(_saved_path):
                try:
                    with open(_saved_path, "r") as _f:
                        _saved = json.load(_f)
                    # Deobfuscate creds stored by previous login
                    if "steam_username" in _saved:
                        _saved["steam_username"] = _deobfuscate_creds(_saved["steam_username"])
                    if "steam_password_seed" in _saved:
                        _saved["steam_password_seed"] = _deobfuscate_creds(_saved["steam_password_seed"])
                    # Merge game-auth fields only (never override steam ticket from form)
                    for _k in ("app_ver", "res_ver", "auth_key", "auth_key_len",
                               "viewer_id", "udid", "device_id"):
                        if _k in _saved and _k not in cfg:
                            cfg[_k] = _saved[_k]
                    print("[login] Restored game-auth fields from saved auth_config.json", flush=True)
                except Exception as _e:
                    print(f"[login] Could not restore auth_config.json: {_e}", flush=True)

        active_client = None
        active_account = None
        active_dashboard_data = None
        active_start_state = {}
        active_parent_cards = {}
        active_parent_rank_points = {}
        raw_load_index_response = None
        active_selection = {
            "deck": None,
            "friend": None,
            "trainee": None,
            "veterans": [],
        }

        has_form_creds = bool(req.username and req.password)
        if req.steam_id and req.steam_session_ticket:
            sid = str(req.steam_id)
            tkt = str(req.steam_session_ticket)
            print("Using provided Steam ticket")
        elif has_form_creds:
            sid, tkt = get_ticket(req.username, req.password, req.code)
        elif "steam_id" in cfg and "steam_session_ticket" in cfg:
            sid = cfg["steam_id"]
            tkt = cfg["steam_session_ticket"]
            print("Using saved Steam ticket from headless bypass")
        else:
            raise Exception("Steam credentials required")

        cfg.update(
            {
                "steam_id": sid,
                "steam_session_ticket": tkt,
                "steam_username": req.username or cfg.get("steam_username", ""),
                "steam_password_seed": req.password
                or cfg.get("steam_password_seed", ""),
            }
        )

        # Inject spoofed hardware info if present (DO NOT override 'udid' or 'device_id' as it breaks auth crypto/binding)
        for key in [
            "device_name",
            "graphics_device_name",
            "platform_os_version",
            "ip_address",
        ]:
            if key in INSTANCE_CONFIG:
                cfg[key] = INSTANCE_CONFIG[key]

        if not has_fresh_auth_config(cfg):
            raise Exception(
                "Fresh in-game auth capture required; switch to the target in-game account, restart capture, then login again"
            )

        # --- UMATRACKER INJECTION: SAVE CONFIGS FOR HEADLESS MODE ---
        try:
            save_cfg = dict(cfg)
            if "steam_username" in save_cfg:
                save_cfg["steam_username"] = _obfuscate_creds(
                    save_cfg["steam_username"]
                )
            if "steam_password_seed" in save_cfg:
                save_cfg["steam_password_seed"] = _obfuscate_creds(
                    save_cfg["steam_password_seed"]
                )

            with open(os.path.join(RUNTIME_DIR, "auth_config.json"), "w") as f:
                json.dump(save_cfg, f, indent=4)
            with open(os.path.join(RUNTIME_DIR, "steam_token.txt"), "w") as f:
                f.write(tkt)
            print(f"\n[+] UMATRACKER: Saved keys to {RUNTIME_DIR}!", flush=True)
        except Exception as e:
            print(f"[-] Failed to save keys: {e}")
        # ------------------------------------------------------------

        c = attach_turn_delay(UmaClient(cfg, trace_enabled=False))
        res = c.login()
        if not res:
            raise HTTPException(status_code=401, detail="Game login failed")
        active_client = c

        d = res.get("data", {})
        career_data = None
        if d.get("single_mode_chara_light") or d.get("single_mode_chara"):
            try:
                career_res = c.load_career()
                career_data = career_res.get("data")
            except Exception:
                pass

        account = get_account_status(d, career_data)
        active_account = account
        active_start_state = {}
        active_parent_cards = {}
        active_parent_rank_points = {}
        update_start_state(d)

        umas = []
        card_list = d.get("card_list", [])
        for card in card_list:
            cid = str(card.get("card_id", card.get("id", "")))
            umas.append({"id": cid, "name": chara_map.get(cid, f"Unknown ({cid})")})

        supports = []
        support_card_list = d.get("support_card_list", [])
        for s in support_card_list:
            sid = str(s.get("support_card_id", s.get("id", "")))
            info = support_map.get(sid)
            if info:
                supports.append(
                    {
                        "id": sid,
                        "name": info["name"],
                        "type": display_support_type(info["type"]),
                        "rarity": info["rarity"],
                    }
                )
            else:
                supports.append(
                    {
                        "id": sid,
                        "name": f"Unknown ({sid})",
                        "type": "Unknown",
                        "rarity": "?",
                    }
                )

        decks = []
        deck_array = d.get("support_card_deck_array", [])
        for deck in deck_array:
            cards = []
            for cid in deck.get("support_card_id_array", []):
                sid = str(cid)
                info = support_map.get(sid)
                if info:
                    cards.append(
                        {
                            "id": sid,
                            "name": info["name"],
                            "rarity": info["rarity"],
                            "type": display_support_type(info["type"]),
                        }
                    )
                else:
                    cards.append(
                        {
                            "id": sid,
                            "name": f"Unknown ({sid})",
                            "rarity": "?",
                            "type": "?",
                        }
                    )

            decks.append(
                {
                    "id": deck.get("deck_id"),
                    "name": deck.get("name", f'Deck {deck.get("deck_id")}'),
                    "cards": cards,
                }
            )

        parents = []
        trained_chara_list = d.get("trained_chara", [])
        for chara in trained_chara_list:

            raw_id = str(chara.get("card_id", ""))

            if "{" in raw_id or "-" in raw_id or not raw_id.isdigit():
                found = False
                for key, val in chara.items():
                    val_str = str(val)
                    if val_str.isdigit() and len(val_str) >= 4:
                        raw_id = val_str
                        found = True
                        break
                if not found:
                    continue

            cid = raw_id

            tree = {
                "self": {
                    "card_id": cid,
                    "name": chara_map.get(cid, f"Unknown ({cid})"),
                    "factors": [],
                    "wins": get_win_summary(chara.get("win_saddle_id_array", [])),
                },
                "p1": {
                    "card_id": 0,
                    "name": "",
                    "factors": [],
                    "wins": get_win_summary([]),
                },
                "p2": {
                    "card_id": 0,
                    "name": "",
                    "factors": [],
                    "wins": get_win_summary([]),
                },
                "gp1": {
                    "card_id": 0,
                    "name": "",
                    "factors": [],
                    "wins": get_win_summary([]),
                },
                "gp2": {
                    "card_id": 0,
                    "name": "",
                    "factors": [],
                    "wins": get_win_summary([]),
                },
                "gp3": {
                    "card_id": 0,
                    "name": "",
                    "factors": [],
                    "wins": get_win_summary([]),
                },
                "gp4": {
                    "card_id": 0,
                    "name": "",
                    "factors": [],
                    "wins": get_win_summary([]),
                },
            }

            tree["self"]["factors"] = get_factors(get_chara_factor_ids(chara), cid)

            for sc in chara.get("succession_chara_array", []):
                pos = sc.get("position_id")
                sc_cid = sc.get("card_id", 0)
                key = ""
                if pos == 10:
                    key = "p1"
                elif pos == 20:
                    key = "p2"
                elif pos == 11:
                    key = "gp1"
                elif pos == 12:
                    key = "gp2"
                elif pos == 21:
                    key = "gp3"
                elif pos == 22:
                    key = "gp4"

                if key:
                    tree[key]["card_id"] = sc_cid
                    tree[key]["name"] = chara_map.get(
                        str(sc_cid), f"Unknown ({sc_cid})"
                    )
                    tree[key]["factors"] = get_factors(
                        sc.get("factor_id_array", []), sc_cid
                    )
                    tree[key]["wins"] = get_win_summary(
                        sc.get("win_saddle_id_array", [])
                    )

            parents.append(
                {
                    "instance_id": chara.get("trained_chara_id"),
                    "card_id": cid,
                    "name": chara_map.get(cid, f"Unknown ({cid})"),
                    "rank": chara.get("rank", 0),
                    "create_date": chara.get("create_date") or chara.get("created_at") or 0,
                    "tree": tree,
                }
            )
            lineage_cards = [int(cid)]
            for sc in chara.get("succession_chara_array", []) or []:
                sc_cid = sc.get("card_id", 0)
                if sc_cid:
                    lineage_cards.append(int(sc_cid))
            active_parent_cards[int(chara.get("trained_chara_id"))] = lineage_cards
            active_parent_rank_points[int(chara.get("trained_chara_id"))] = {
                "rank": chara.get("rank", 0),
                "rank_point": chara.get("rank_score", 0),
            }

        active_dashboard_data = {
            "success": True,
            "account": account,
            "umas": umas,
            "supports": supports,
            "decks": decks,
            "parents": parents,
        }
        return active_dashboard_data
    except Exception as e:
        msg = str(e)
        if "STEAM_GUARD_WRONG_CODE" in msg:
            pending_game_auth_config = cfg
            return {
                "success": False,
                "needs_2fa": True,
                "detail": "WRONG GUARD CODE - GET A FRESH CODE AND RETRY",
            }
        if "STEAM_GUARD_REQUIRED" in msg:
            pending_game_auth_config = cfg
            return {"success": False, "needs_2fa": True}
        return {"success": False, "detail": str(e)}


# --- DIRECT CIRCLE LOOKUP ---
@app.get("/api/circle/{circle_id}")
async def get_specific_circle_data(circle_id: int):
    global active_client
    if not active_client:
        return {"success": False, "detail": "Bot is not logged in."}

    try:
        result = active_client.call(
            "circle/detail", {"circle_id": circle_id, "no_join_user": True}
        )
        data = result.get("data", {})

        info = data.get("circle_info", {})
        if not info:
            return {
                "success": False,
                "detail": f"No data returned for Circle ID {circle_id}.",
            }

        # Grab the Club's Monthly Data
        monthly_ranking = data.get("circle_ranking_this_month", {})
        club_monthly_fans = monthly_ranking.get("point", 0)
        club_monthly_rank = monthly_ranking.get("rank", 0)

        # Parse the members
        members_raw = data.get("summary_user_info_array", [])
        formatted_members = []
        all_time_fans_sum = 0

        for m in members_raw:
            user_fans = m.get("fan", 0)
            all_time_fans_sum += user_fans  # Add this user's fans to the club total

            formatted_members.append(
                {
                    "viewer_id": m.get("viewer_id"),
                    "name": m.get("name", "Unknown Trainer"),
                    "fans": user_fans,
                }
            )

        return {
            "success": True,
            "club_name": info.get("name", "Unknown"),
            "club_monthly_fans": club_monthly_fans,
            "club_rank": club_monthly_rank,
            "total_all_time_fans": all_time_fans_sum,
            "member_count": len(formatted_members),
            "members": formatted_members,
        }
    except Exception as e:
        return {"success": False, "detail": str(e)}


# --- PROFILE PROXY LOOKUP ---
@app.get("/api/club_by_member/{trainer_id}")
async def get_club_by_member(trainer_id: int):
    global active_client
    if not active_client:
        return {"success": False, "detail": "API bridge is not logged in."}

    try:
        print(f"[*] Look up Trainer ID: {trainer_id}...", flush=True)

        # We now use the EXACT payload your sniffer discovered for friend search!
        friend_res = active_client.call(
            "friend/search",
            {"friend_viewer_id": trainer_id, "deleted_response_type": 0},
        )
        friend_data = friend_res.get("data", {})

        user_info = friend_data.get("summary_user_info")
        if (
            not user_info
            and "summary_user_info_array" in friend_data
            and len(friend_data["summary_user_info_array"]) > 0
        ):
            user_info = friend_data["summary_user_info_array"][0]

        if not user_info:
            return {
                "success": False,
                "detail": f"Trainer ID {trainer_id} returned no profile data.",
            }

        target_circle_id = user_info.get("circle_id")
        if not target_circle_id:
            return {
                "success": False,
                "detail": f"Trainer {user_info.get('name', trainer_id)} is not currently in a club.",
            }

        print(f"[+] Found Club ID {target_circle_id}! Fetching roster...", flush=True)
        time.sleep(1.0)

        # Again, using the exact payload for the external club fetch
        details = active_client.call(
            "circle/detail", {"circle_id": target_circle_id, "no_join_user": True}
        )
        details_data = details.get("data", {})

        info = details_data.get("circle_info", {})
        members_raw = (
            details_data.get("circle_user_array")
            or details_data.get("circle_member_array")
            or []
        )

        formatted_members = []
        for m in members_raw:
            formatted_members.append(
                {
                    "viewer_id": m.get("viewer_id"),
                    "name": m.get("name", "Unknown Trainer"),
                    "fans": m.get("fans") or m.get("circle_fans") or 0,
                }
            )

        return {
            "success": True,
            "club_name": info.get("name", "Unknown"),
            "club_id": target_circle_id,
            "total_fans": info.get("total_fans") or info.get("fans", 0),
            "member_count": len(formatted_members),
            "members": formatted_members,
        }

    except Exception as e:
        return {"success": False, "detail": str(e)}


@app.get("/api/skills")
async def get_skills():
    return {"success": True, "skills": skill_data}


@app.get("/api/session")
async def session_status():
    global active_client, active_dashboard_data, active_account, active_selection
    if not active_client or not active_dashboard_data:
        return {"success": False}

    data = dict(active_dashboard_data)
    if active_account:
        data["account"] = active_account
    data["selection"] = active_selection
    data["success"] = True
    return data


class UISelectionRequest(BaseModel):
    selection: dict


@app.post("/api/selection")
async def update_selection(req: UISelectionRequest):
    global active_selection
    active_selection = req.selection
    return {"success": True}


@app.post("/api/logout")
async def logout():
    global active_client, active_account, active_dashboard_data, active_start_state, active_parent_cards, active_parent_rank_points, raw_load_index_response, pending_game_auth_config, active_selection
    active_client = None
    active_account = None
    active_dashboard_data = None
    active_start_state = {}
    active_parent_cards = {}
    active_parent_rank_points = {}
    raw_load_index_response = None
    pending_game_auth_config = {}
    active_selection = {"deck": None, "friend": None, "trainee": None, "veterans": []}
    return {"success": True}


@app.post("/api/career/start")
async def start_career(req: StartCareerRequest):
    try:
        started = start_career_from_request(req)
        if not started.get("success"):
            return started
        account, chara_info = apply_career_result(started["result"])
        return {"success": True, "account": account, "chara_info": chara_info}
    except Exception as e:
        return {"success": False, "detail": str(e)}


backend_loop_thread = None
backend_loop_stop = False


def manage_career_loop(req, preset, initial_result):
    global backend_loop_stop, active_account, active_client
    max_steps = max(1, min(int(req.max_steps or 2500), 3000))
    consecutive_fails = 0
    current_result = initial_result

    while not backend_loop_stop:
        career_runner.start(
            active_client,
            preset,
            current_result,
            max_steps,
            burn_clocks=req.burn_clocks,
            dev_mode=req.dev_mode,
        )

        while career_runner.snapshot().get("running"):
            if backend_loop_stop:
                career_runner.stop()
                return
            time.sleep(1)

        status = career_runner.snapshot()
        if status.get("last_error"):
            consecutive_fails += 1
            if consecutive_fails >= 3:
                break
        else:
            consecutive_fails = 0

        if not req.dev_mode:
            break

        for _ in range(6):
            if backend_loop_stop:
                return
            time.sleep(1)

        started_ok = False
        while not started_ok and not backend_loop_stop:
            try:
                started = start_career_from_request(req)
                if not started.get("success"):
                    consecutive_fails += 1
                    if consecutive_fails >= 5:
                        break
                    for _ in range(15):
                        if backend_loop_stop:
                            return
                        time.sleep(1)
                    continue
                current_result = started["result"]
                with state_lock:
                    account, chara_info = apply_career_result(current_result)
                    active_account = account
                started_ok = True
                consecutive_fails = 0
            except Exception as e:
                consecutive_fails += 1
                if consecutive_fails >= 5:
                    break
                for _ in range(15):
                    if backend_loop_stop:
                        return
                    time.sleep(1)

        if not started_ok:
            break


@app.post("/api/career/run")
async def run_career(req: RunCareerRequest):
    global active_account, backend_loop_thread, backend_loop_stop
    if career_runner.snapshot().get("running") or (
        backend_loop_thread and backend_loop_thread.is_alive()
    ):
        return {"success": False, "detail": "Career runner loop already active"}
    preset = resolve_preset(req.preset_name)
    if not preset:
        return {"success": False, "detail": "no preset available"}
    req.scenario_id = int(preset.get("scenario_id") or 4)
    try:
        account = active_account or {}
        career = account.get("career") or {}
        load_data = {}
        if career.get("active"):
            index_result = active_client.call("load/index")
            load_data = index_result.get("data", {})
            update_start_state(load_data)

            account = get_account_status(load_data)
            active_account = account
            career = account.get("career") or {}

        if career.get("active"):
            career_result = active_client.load_career()
            career_data = career_result.get("data", {})

            account = get_account_status(load_data, career_result)
            active_account = account

            career_status = account.get("career")
            req.card_id = int(career_status.get("card_id"))
            req.support_card_ids = career_status.get("support_card_ids")
            req.friend_viewer_id = int(career_status.get("friend_viewer_id"))
            req.friend_card_id = int(career_status.get("friend_card_id"))
            req.parent_id_1 = int(career_status.get("parent_id_1"))
            req.parent_id_2 = int(career_status.get("parent_id_2"))
            req.deck_id = int(career_status.get("deck_id"))

            chara_info = career_data.get("chara_info") or {}
            if active_dashboard_data:
                active_dashboard_data["account"] = account
            result = career_result
        else:
            started = start_career_from_request(req)
            if not started.get("success"):
                return started
            result = started["result"]
            account, chara_info = apply_career_result(result)

        apply_deck_type_counts(preset, req=req, chara_info=chara_info)

        if req.dev_mode:
            backend_loop_stop = False
            backend_loop_thread = threading.Thread(
                target=manage_career_loop, args=(req, preset, result), daemon=True
            )
            backend_loop_thread.start()
            time.sleep(0.5)
        else:
            career_runner.start(
                active_client,
                preset,
                result,
                max(1, min(int(req.max_steps or 2500), 3000)),
                burn_clocks=req.burn_clocks,
                dev_mode=req.dev_mode,
            )

        return {
            "success": True,
            "account": account,
            "chara_info": chara_info,
            "runner": career_runner.snapshot(),
        }
    except Exception as e:
        return {"success": False, "detail": str(e)}


@app.get("/api/career/runner")
async def career_runner_status():
    payload = {"success": True, "runner": career_runner.snapshot()}
    # Overlay live wallet/TP/item values from the client cache so the UI
    # account strip stays fresh while the runner loop is active.
    if active_account and active_client:
        acct = dict(active_account)
        tp = active_client.tp_info or {}
        coin = active_client.coin_info or {}
        fcoin = coin.get("fcoin", 0) or 0
        pcoin = coin.get("coin", 0) or 0
        acct["tp"] = {
            "current": tp.get("current_tp", 0),
            "max": tp.get("max_tp", 0),
        }
        acct["carrots"] = {"free": fcoin, "paid": pcoin, "total": fcoin + pcoin}
        acct["gold"] = active_client.item_map.get(59, 0)
        acct["potions"] = active_client.item_map.get(32, 0)
        acct["clocks"] = active_client.item_map.get(95, 0)
        payload["account"] = acct
    return payload


@app.post("/api/career/runner/stop")
async def stop_career_runner():
    global backend_loop_stop
    backend_loop_stop = True
    career_runner.stop()
    return {"success": True, "runner": career_runner.snapshot()}


class BurnClocksRequest(BaseModel):
    burn_clocks: bool


@app.post("/api/career/runner/burn_clocks")
async def set_burn_clocks(req: BurnClocksRequest):
    career_runner.set_burn_clocks(req.burn_clocks)
    return {"success": True, "runner": career_runner.snapshot()}


@app.post("/api/career/friends")
async def get_friend_list(req: FriendListRequest):
    global active_client, active_dashboard_data
    if not active_client:
        return {"success": False, "detail": "Not logged in"}

    if (
        not req.exclude_viewer_ids
        and active_dashboard_data is not None
        and "friends" in active_dashboard_data
    ):
        return {
            "success": True,
            "friends": active_dashboard_data["friends"],
            "exclude_viewer_ids": active_dashboard_data.get("friendExcludeIds", []),
            "source": "cache",
        }

    try:
        result = active_client.pre_single_mode(req.exclude_viewer_ids)
        data = result.get("data", {})
        update_start_state(data)
        friends, exclude_viewer_ids, source = normalize_friend_cards(data)

        if active_dashboard_data is not None:
            active_dashboard_data["friends"] = friends
            active_dashboard_data["friendExcludeIds"] = exclude_viewer_ids
            active_dashboard_data["friendsLoaded"] = True

        return {
            "success": True,
            "friends": friends,
            "exclude_viewer_ids": exclude_viewer_ids,
            "source": source,
        }
    except Exception as e:
        return {"success": False, "detail": str(e)}


@app.post("/api/career/action")
async def career_action(req: CareerActionRequest):
    global active_client, active_account
    if not active_client:
        return {"success": False, "detail": "Not logged in"}

    try:
        result = active_client.exec_command(
            command_type=req.command_type,
            command_id=req.command_id,
            current_turn=req.current_turn,
            current_vital=req.current_vital,
            command_group_id=req.command_group_id,
            select_id=req.select_id,
        )

        data = result.get("data", {})
        return {
            "success": True,
            "chara_info": data.get("chara_info", {}),
            "command_result": data.get("command_result", {}),
        }
    except Exception as e:
        return {"success": False, "detail": str(e)}


@app.post("/api/career/delete")
async def delete_career(req: DeleteCareerRequest):
    global active_client, active_account, active_dashboard_data, backend_loop_thread
    if not active_client:
        return {"success": False, "detail": "Not logged in"}
    if career_runner.snapshot().get("running") or (
        backend_loop_thread and backend_loop_thread.is_alive()
    ):
        return {
            "success": False,
            "detail": "Cannot delete career while runner is active",
        }

    try:
        account = active_account or {}
        career = account.get("career") or {}
        if not career.get("active"):
            load_result = active_client.call("load/index")
            load_data = load_result.get("data", {})
            update_start_state(load_data)
            account = get_account_status(load_data)
            active_account = account
            career = account.get("career") or {}
        current_turn = req.current_turn or career.get("turn", 0) or 1
        if not career.get("active") and not req.current_turn:
            return {"success": False, "detail": "No active career"}
        active_client.finish_career(current_turn=current_turn, is_force_delete=True)
        account["career"] = None
        active_account = account
        if active_dashboard_data:
            active_dashboard_data["account"] = account
        return {"success": True, "account": account}
    except Exception as e:
        return {"success": False, "detail": str(e)}


class RemoveParentsRequest(BaseModel):
    trained_chara_ids: list  # list of int instance IDs to delete


def _evict_parents(ids: list):
    """Remove ids from all in-memory caches. Call while holding no lock."""
    global active_dashboard_data, active_parent_cards, active_parent_rank_points
    for cid in ids:
        active_parent_cards.pop(cid, None)
        active_parent_rank_points.pop(cid, None)
    if active_dashboard_data:
        parents = active_dashboard_data.get("parents") or []
        active_dashboard_data["parents"] = [
            p for p in parents if int(p.get("instance_id") or -1) not in ids
        ]


@app.post("/api/parents/remove")
async def remove_parents(req: RemoveParentsRequest):
    """Delete one or more trained characters (parents) by instance ID."""
    global active_client
    if not active_client:
        return {"success": False, "detail": "Not logged in"}
    if not req.trained_chara_ids:
        return {"success": False, "detail": "No IDs provided"}
    ids = [int(i) for i in req.trained_chara_ids]
    try:
        result = active_client.remove_trained_chara(ids)
        _evict_parents(ids)
        return {"success": True, "removed": len(ids), "result": result}
    except Exception as e:
        return {"success": False, "detail": str(e)}


class RemoveRecentParentsRequest(BaseModel):
    max_age_hours: float = 24.0   # delete parents created within this many hours


@app.post("/api/parents/remove-recent")
async def remove_recent_parents(req: RemoveRecentParentsRequest):
    """Auto-delete all parents whose create_date is within max_age_hours of now.
    Uses the in-memory dashboard cache so no extra API call needed.
    """
    global active_client, active_dashboard_data
    if not active_client:
        return {"success": False, "detail": "Not logged in"}
    if not active_dashboard_data:
        return {"success": False, "detail": "Dashboard not loaded — please refresh"}

    import time
    cutoff = time.time() - req.max_age_hours * 3600
    parents = active_dashboard_data.get("parents") or []

    candidates = [
        int(p["instance_id"])
        for p in parents
        if int(p.get("instance_id") or 0) > 0
        and int(p.get("create_date") or 0) >= cutoff
    ]

    if not candidates:
        return {"success": True, "removed": 0, "detail": "No parents found within the time window"}

    try:
        result = active_client.remove_trained_chara(candidates)
        _evict_parents(candidates)
        return {"success": True, "removed": len(candidates), "ids": candidates, "result": result}
    except Exception as e:
        return {"success": False, "detail": str(e)}


@app.get("/api/debug/last_ticket")
async def get_last_ticket_result():
    """Returns the raw stdout/stderr/returncode from the last Steam ticket gen attempt."""
    result = _uma_client_mod.LAST_TICKET_GEN_RESULT
    if result is None:
        return {"detail": "No ticket gen attempt recorded yet"}
    safe = dict(result)
    # redact the actual ticket value from stdout
    if safe.get("stdout"):
        safe["stdout"] = safe["stdout"][:80] + "...<redacted>"
    return safe


@app.get("/api/debug/start_state")
async def get_start_state():
    return active_start_state


@app.get("/api/debug/raw_load")
async def get_raw_load():
    return {"error": "raw load/index response storage disabled"}


def safe_public_path(subdir: str, file_name: str):
    """Resolve a file inside public/<subdir>, refusing path traversal."""
    base = (base_dir / "public" / subdir).resolve()
    try:
        path = (base / file_name).resolve()
    except (OSError, ValueError):
        return None
    if base != path and base not in path.parents:
        return None
    return path if path.is_file() else None


@app.post("/api/career/rescue")
async def rescue_career():
    """Probe ladder to clear a stuck single-mode state (e.g. playing_state=3
    with the race already recorded, where race_end/race_out/exec_command all
    return 102). Run while logged in and with the runner STOPPED."""
    if not active_client:
        return {"success": False, "detail": "Not logged in"}
    if career_runner.snapshot().get("running"):
        return {"success": False, "detail": "Stop the career runner first"}

    report = []

    def snap():
        res = active_client.load_career()
        d = res.get("data") or {}
        ch = d.get("chara_info") or {}
        return {
            "turn": ch.get("turn"),
            "playing_state": ch.get("playing_state"),
            "vital": ch.get("vital"),
            "race_program_id": ch.get("race_program_id"),
            "has_race_start_info": bool(d.get("race_start_info")),
            "events": len(d.get("unchecked_event_array") or []),
        }

    try:
        st0 = snap()
    except Exception as e:
        return {"success": False, "detail": f"load failed: {e}", "report": report}
    report.append({"step": "initial", "state": st0})
    start_turn = int(st0.get("turn") or 0)
    vital = int(st0.get("vital") or 0)
    if st0.get("playing_state") == 1:
        return {"success": True, "detail": "career is not stuck", "report": report}

    t = start_turn

    def probe(label, fn):
        row = {"step": label}
        try:
            fn()
            row["call"] = "ok"
        except Exception as e:
            row["call"] = str(e)[:200]
        try:
            row["state"] = snap()
        except Exception as e:
            row["state"] = {"error": str(e)[:120]}
        report.append(row)
        st = row.get("state") or {}
        ps = st.get("playing_state")
        turn_now = int(st.get("turn") or 0)
        return ps == 1 or turn_now > start_turn

    probes = [
        ("race_out turn", lambda: active_client.race_out(current_turn=t)),
        ("race_out turn+1", lambda: active_client.race_out(current_turn=t + 1)),
        ("race_end turn+1", lambda: active_client.race_end(current_turn=t + 1)),
        ("race_end+out turn", lambda: (active_client.race_end(current_turn=t), active_client.race_out(current_turn=t))),
        ("race_start+end+out turn", lambda: (
            active_client.race_start(is_short=1, current_turn=t),
            active_client.race_end(current_turn=t),
            active_client.race_out(current_turn=t),
        )),
        ("race_start+end+out turn+1", lambda: (
            active_client.race_start(is_short=1, current_turn=t + 1),
            active_client.race_end(current_turn=t + 1),
            active_client.race_out(current_turn=t + 1),
        )),
        ("rest turn+1", lambda: active_client.exec_command(command_type=7, command_id=701, current_turn=t + 1, current_vital=vital)),
    ]
    try:
        for label, fn in probes:
            if probe(label, fn):
                return {"success": True, "detail": f"unstuck via: {label}", "report": report}
    except Exception as e:
        return {"success": False, "detail": str(e), "report": report}
    return {"success": False, "detail": "still stuck after all probes", "report": report}


@app.get("/api/career/history")
async def career_history():
    snap = career_runner.snapshot()
    history = snap.get("action_history") or []
    return {
        "success": True,
        "turns": snap.get("date_history") or [],
        "scores": snap.get("score_history") or [],
        "stats": [
            {"turn": row.get("turn"), "action": row.get("action"), **(row.get("stats") or {})}
            for row in history
        ],
        "running": snap.get("running"),
        "finished": snap.get("finished"),
    }


@app.get("/api/career/crash_trace")
async def career_crash_trace():
    trace_path = Path(RUNTIME_DIR) / "crash_trace.txt"
    if not trace_path.exists():
        return {"success": True, "trace": ""}
    try:
        text = trace_path.read_text(encoding="utf-8", errors="replace")
        return {"success": True, "trace": text[-8000:]}
    except Exception as e:
        return {"success": False, "detail": str(e)}


@app.get("/api/images/{image_name}")
async def get_image(image_name: str):
    name_no_ext = Path(image_name.split("?")[0].replace(".png", "")).name

    exact_path = images_dir / f"{name_no_ext}.png"
    if exact_path.exists():
        return FileResponse(
            exact_path, media_type="image/png", headers={"Cache-Control": "no-cache"}
        )

    for fallback_id in ["100101", "10010", "10000", "10001"]:
        fb_path = images_dir / f"{fallback_id}.png"
        if fb_path.exists():
            return FileResponse(
                fb_path, media_type="image/png", headers={"Cache-Control": "no-cache"}
            )

    raise HTTPException(status_code=404, detail="Image not found")


@app.get("/styles.css")
async def styles_css():
    path = base_dir / "public" / "styles.css"
    if path.exists():
        return FileResponse(
            path, media_type="text/css", headers={"Cache-Control": "no-cache"}
        )
    raise HTTPException(status_code=404, detail="styles.css not found")


@app.get("/app.js")
async def app_js():
    path = base_dir / "public" / "app.js"
    if path.exists():
        return FileResponse(
            path,
            media_type="application/javascript",
            headers={"Cache-Control": "no-cache"},
        )
    raise HTTPException(status_code=404, detail="app.js not found")


@app.get("/sweep.png")
async def sweep_png():
    path = base_dir / "public" / "sweep.png"
    if path.exists():
        return FileResponse(
            path, media_type="image/png", headers={"Cache-Control": "no-cache"}
        )
    raise HTTPException(status_code=404, detail="sweep.png not found")


@app.get("/broom.png")
async def broom_png():
    path = base_dir / "public" / "broom.png"
    if path.exists():
        return FileResponse(
            path, media_type="image/png", headers={"Cache-Control": "no-cache"}
        )
    raise HTTPException(status_code=404, detail="broom.png not found")


@app.get("/assets/data/{file_name}")
async def get_asset_data(file_name: str):
    path = safe_public_path("assets/data", file_name)
    if path:
        return FileResponse(path, headers={"Cache-Control": "no-cache"})
    raise HTTPException(status_code=404, detail="File not found")


@app.get("/races/{file_name}")
async def get_race_image(file_name: str):
    path = safe_public_path("races", file_name)
    if path:
        return FileResponse(path, headers={"Cache-Control": "max-age=31536000"})
    raise HTTPException(status_code=404, detail="Race image not found")


@app.get("/css/{file_name}")
async def get_css_module(file_name: str):
    path = safe_public_path("css", file_name)
    if path and path.suffix == ".css":
        return FileResponse(
            path, media_type="text/css", headers={"Cache-Control": "no-cache"}
        )
    raise HTTPException(status_code=404, detail="CSS module not found")


@app.get("/js/{file_name}")
async def get_js_module(file_name: str):
    path = safe_public_path("js", file_name)
    if path and path.suffix == ".js":
        return FileResponse(
            path,
            media_type="application/javascript",
            headers={"Cache-Control": "no-cache"},
        )
    raise HTTPException(status_code=404, detail="JS module not found")


@app.get("/", response_class=HTMLResponse)
async def root():
    index_path = base_dir / "public" / "index.html"
    if index_path.exists():
        return FileResponse(
            index_path, media_type="text/html", headers={"Cache-Control": "no-cache"}
        )
    return "index.html not found"


def set_console_topmost():
    if os.name != "nt":
        return
    try:
        import ctypes

        hwnd = ctypes.windll.kernel32.GetConsoleWindow()
        if not hwnd:
            return
        ctypes.windll.user32.SetWindowPos(hwnd, -1, 0, 0, 0, 0, 0x0001 | 0x0002)
    except Exception:
        pass


def kill_process_by_name(name):
    if os.name != "nt":
        return
    try:
        subprocess.run(
            ["taskkill", "/IM", name, "/F"], capture_output=True, text=True, timeout=10
        )
    except Exception:
        pass


def kill_listeners_on_port(port):
    if os.name != "nt":
        return
    try:
        proc = subprocess.run(
            ["netstat", "-ano"], capture_output=True, text=True, timeout=5
        )
    except Exception:
        return

    current_pid = os.getpid()
    pids = set()
    marker = f":{port}"
    for line in proc.stdout.splitlines():
        parts = line.split()
        if len(parts) < 5:
            continue
        local_addr = parts[1]
        state = parts[3].upper() if len(parts) >= 5 else ""
        pid_text = parts[-1]
        if marker not in local_addr or state != "LISTENING":
            continue
        try:
            pid = int(pid_text)
        except ValueError:
            continue
        if pid and pid != current_pid:
            pids.add(pid)

    if not pids:
        return
    print(
        f"Port {port} already in use; killing listener PID(s): {', '.join(map(str, sorted(pids)))}",
        flush=True,
    )
    for pid in sorted(pids):
        try:
            subprocess.run(
                ["taskkill", "/PID", str(pid), "/F"],
                capture_output=True,
                text=True,
                timeout=5,
            )
        except Exception:
            pass
    time.sleep(0.5)


def has_fresh_auth_config(cfg):
    app_ver = str(cfg.get("app_ver") or "").strip()
    res_ver = str(cfg.get("res_ver") or "").strip()
    if not app_ver or not res_ver:
        return False
    if int(cfg.get("auth_key_len") or 0) != 48:
        return False
    viewer_id = cfg.get("viewer_id")
    udid = str(cfg.get("udid") or "").strip()
    auth_key = str(cfg.get("auth_key") or "").strip().lower()
    if not viewer_id or not udid or not auth_key:
        return False
    if not re.fullmatch(r"[0-9a-f]+", auth_key):
        return False
    if len(auth_key) < 32 or len(auth_key) % 2:
        return False
    if len(udid) != 36 or udid.count("-") != 4:
        return False
    return True


def check_saved_auth():
    auth_config_path = os.path.join(RUNTIME_DIR, "auth_config.json")

    if os.path.exists(auth_config_path):
        try:
            with open(auth_config_path, "r") as f:
                saved_cfg = json.load(f)

            if "steam_username" in saved_cfg:
                saved_cfg["steam_username"] = _deobfuscate_creds(
                    saved_cfg["steam_username"]
                )
            if "steam_password_seed" in saved_cfg:
                saved_cfg["steam_password_seed"] = _deobfuscate_creds(
                    saved_cfg["steam_password_seed"]
                )

            if (
                has_fresh_auth_config(saved_cfg)
                and "steam_id" in saved_cfg
                and "steam_session_ticket" in saved_cfg
            ):
                for key in [
                    "device_name",
                    "graphics_device_name",
                    "platform_os_version",
                    "ip_address",
                ]:
                    if key in INSTANCE_CONFIG:
                        saved_cfg[key] = INSTANCE_CONFIG[key]

                print(
                    f"[+] Found saved auth config for {PROFILE_NAME}. Testing headless bypass...",
                    flush=True,
                )
                c = UmaClient(saved_cfg, trace_enabled=False)
                res = c.login()
                if res and res.get("data"):
                    print("[+] Headless bypass successful!", flush=True)
                    return saved_cfg
                else:
                    print("[-] Headless bypass failed (Invalid session).", flush=True)

            if saved_cfg.get("steam_username") and saved_cfg.get("steam_password_seed"):
                print("[+] Attempting to refresh Steam session ticket...", flush=True)
                try:
                    sid, tkt = get_ticket(
                        saved_cfg["steam_username"],
                        saved_cfg["steam_password_seed"],
                        "",
                    )
                    saved_cfg["steam_id"] = sid
                    saved_cfg["steam_session_ticket"] = tkt

                    print("[+] Testing with new Steam ticket...", flush=True)
                    c = UmaClient(saved_cfg, trace_enabled=False)
                    res = c.login()
                    if res and res.get("data"):
                        print(
                            "[+] Headless bypass with new ticket successful!",
                            flush=True,
                        )
                        save_cfg = dict(saved_cfg)
                        if "steam_username" in save_cfg:
                            save_cfg["steam_username"] = _obfuscate_creds(
                                save_cfg["steam_username"]
                            )
                        if "steam_password_seed" in save_cfg:
                            save_cfg["steam_password_seed"] = _obfuscate_creds(
                                save_cfg["steam_password_seed"]
                            )

                        with open(auth_config_path, "w") as f:
                            json.dump(save_cfg, f, indent=4)
                        return saved_cfg
                    else:
                        print("[-] Headless bypass with new ticket failed.", flush=True)
                except Exception as e:
                    if "STEAM_GUARD_REQUIRED" in str(e):
                        print(
                            "[-] Steam ticket refresh failed: Steam Guard code required. Falling back to manual launch.",
                            flush=True,
                        )
                    else:
                        print(f"[-] Steam ticket refresh failed: {e}", flush=True)
        except Exception as e:
            print(f"[-] Headless bypass failed: {e}", flush=True)
    return None


def launch_game():
    if os.name != "nt":
        print("Auth refresh needs Windows Steam launch.")
        return False
    try:
        os.startfile(f"steam://rungameid/{APP_ID}")
        return True
    except Exception as e:
        print(f"Failed to launch Umamusume through Steam: {e}")
        return False


def refresh_auth_before_serving(timeout_sec=None):
    global pending_game_auth_config

    saved_cfg = check_saved_auth()
    if saved_cfg:
        pending_game_auth_config = saved_cfg
        return True

    timeout_sec = timeout_sec or int(
        os.environ.get("SWEEPY_AUTH_CAPTURE_TIMEOUT_SEC", "180")
    )
    started_at = time.time()
    deadline = started_at + timeout_sec

    print("[NEED TO CAPTURE AUTH]", flush=True)
    if not launch_game():
        return False

    print(f"Waiting up to {timeout_sec}s for user to enter game menu", flush=True)

    session = None
    captured_data = {}
    done = {"ok": False}

    def on_message(message, data):
        if message.get("type") == "error":
            print(f"Frida Error: {message.get('description')}", flush=True)
            return
        payload = message.get("payload") or {}
        if payload.get("type") == "creds":
            if payload.get("app_ver") and payload.get("res_ver"):
                captured_data.update(payload)
                done["ok"] = True

    while time.time() < deadline:
        try:
            session = frida.attach(PROCESS_NAME)
            break
        except Exception:
            time.sleep(1)

    if not session:
        print(f"Error: {PROCESS_NAME} not found within timeout.", flush=True)
        return False

    try:
        script = session.create_script(JS_CODE)
        script.on("message", on_message)
        script.load()

        while time.time() < deadline:
            if done["ok"]:
                if has_fresh_auth_config(captured_data):
                    pending_game_auth_config = dict(captured_data)
                    time.sleep(random.uniform(2, 4))
                    kill_process_by_name(PROCESS_NAME)
                    return True
            time.sleep(0.5)
    except Exception as e:
        print(f"Frida injection failed: {e}", flush=True)
    finally:
        if session:
            try:
                session.detach()
            except Exception:
                pass

    print(
        "Auth refresh failed: no fresh credentials captured before timeout.", flush=True
    )
    return False


if __name__ == "__main__":
    import uvicorn

    set_console_topmost()
    kill_listeners_on_port(PORT)
    if not refresh_auth_before_serving():
        raise SystemExit(1)

    if pending_game_auth_config.get("steam_id") and pending_game_auth_config.get(
        "steam_session_ticket"
    ):
        print("[*] Pre-loading backend session to bypass Web UI login...", flush=True)
        backup_cfg = dict(pending_game_auth_config)
        try:
            import asyncio
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            res = loop.run_until_complete(login(LoginRequest()))
            if res and res.get("success"):
                print(
                    "[+] Backend pre-load successful. You will bypass the Web UI login!",
                    flush=True,
                )
            else:
                print(
                    "[-] Backend pre-load failed. You will need to login on the Web UI.",
                    flush=True,
                )
                pending_game_auth_config = backup_cfg
        except Exception as e:
            print(f"[-] Backend pre-load error: {e}", flush=True)
            pending_game_auth_config = backup_cfg

    print(f"Access the Web UI at: http://127.0.0.1:{PORT}", flush=True)
    uvicorn.run(app, host="127.0.0.1", port=PORT, log_level="error")
