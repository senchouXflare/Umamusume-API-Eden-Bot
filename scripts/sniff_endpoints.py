"""
Endpoint sniffer — discovers which API endpoint + payload the real game sends.

Use it to learn unknown actions (e.g. recovering TP with a stamina/TP potion item
instead of jewels): run this, open the game, perform the action manually, and the
script prints the endpoint name and the fully decrypted request payload.

It reuses the same Frida TLS hook the bot already uses (so it sees every
POST /umamusume/... the game makes) and decrypts the request body with the AES
scheme from uma_api/client.py (the per-request key is appended to the body, and the
IV is derived from your udid, which is read from your auth_config.json).

Usage (Windows, game running):
    python scripts/sniff_endpoints.py
    python scripts/sniff_endpoints.py --filter tp,item,recovery,stamina,present
    python scripts/sniff_endpoints.py --all          # show every endpoint
    python scripts/sniff_endpoints.py --profile default

Then in the game, tap "use TP potion". Watch the console: the matching line shows
    >>> ENDPOINT: user/xxx
    payload: { ... }
Paste that here and the bot can implement potion-based recovery.
"""

import argparse
import base64
import json
import struct
import sys
import time
from pathlib import Path

try:
    import frida
except ImportError:
    sys.exit("frida not installed. Run: pip install frida")

try:
    import msgpack
    from Crypto.Cipher import AES
    from Crypto.Util.Padding import unpad
except ImportError:
    sys.exit("Missing deps. Run: pip install msgpack pycryptodome")

PROCESS_NAME = "UmamusumePrettyDerby.exe"
ROOT = Path(__file__).resolve().parent.parent

# Frida JS: same TLS write hook as main.py, but emits EVERY POST endpoint + body.
SNIFF_JS = r"""
'use strict';
(function() {
    var buffers = {};
    var attached = {};
    function parseHttp(text) {
        if (text.indexOf('/umamusume/') < 0) return;
        var em = text.match(/POST\s+\/umamusume\/([^\s]+)\s+HTTP/i);
        var idx = text.indexOf('\r\n\r\n');
        if (!em || idx < 0) return;
        send({ type: 'req', endpoint: em[1], body: text.substring(idx + 4) });
    }
    function parseChunk(key, chunk) {
        var buf = (buffers[key] || '') + chunk;
        if (buf.length > 2097152) buf = buf.substring(buf.length - 1048576);
        var start = buf.indexOf('POST ');
        if (start < 0) { buffers[key] = buf.slice(-4096); return; }
        if (start > 0) buf = buf.substring(start);
        var headerEnd = buf.indexOf('\r\n\r\n');
        if (headerEnd < 0) { buffers[key] = buf; return; }
        var headers = buf.substring(0, headerEnd);
        var lm = headers.match(/Content-Length:\s*(\d+)/i);
        var length = lm ? parseInt(lm[1], 10) : 0;
        var total = headerEnd + 4 + length;
        if (length > 0 && buf.length < total) { buffers[key] = buf; return; }
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
        var hooked = 0;
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
                hooked++;
            } catch (e) {}
        });
        return hooked > 0;
    }
    var done = false;
    var t = setInterval(function() {
        try { if (!done) done = hookTls(); if (done) { clearInterval(t); send({type:'ready'}); } } catch (e) {}
    }, 1000);
})();
"""


def get_iv(udid):
    return udid.replace("-", "").lower()[:16].encode()


def decrypt_request_body(b64_body, udid):
    """Decrypt a request body produced by uma_api.client.pack()."""
    raw = base64.b64decode(b64_body)
    if len(raw) < 4:
        return None
    header_len = struct.unpack("<I", raw[:4])[0]
    rest = raw[4 + header_len:]
    if len(rest) < 48:
        return None
    key, cipher = rest[-32:], rest[:-32]
    if len(cipher) % 16 != 0 or not cipher:
        return None
    try:
        p = unpad(AES.new(key, AES.MODE_CBC, get_iv(udid)).decrypt(cipher), 16)
        plen = struct.unpack("<I", p[:4])[0]
        return msgpack.unpackb(p[4:4 + plen], raw=False, strict_map_key=False)
    except Exception:
        return None


def load_udid(profile):
    candidates = [
        ROOT / "uma_runtime" / profile / "auth_config.json",
        ROOT / f"{profile}.json",
        ROOT / "config.json",
    ]
    for path in candidates:
        if path.exists():
            try:
                cfg = json.loads(path.read_text(encoding="utf-8"))
                if cfg.get("udid"):
                    return cfg["udid"], path
            except Exception:
                pass
    return None, None


def redact(payload):
    if isinstance(payload, dict):
        out = {}
        for k, v in payload.items():
            if k in {"auth_key", "steam_session_ticket", "steam_id", "device_id"}:
                out[k] = "<redacted>"
            else:
                out[k] = redact(v)
        return out
    if isinstance(payload, list):
        return [redact(x) for x in payload[:30]]
    return payload


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--profile", default="default")
    ap.add_argument("--filter", default="tp,item,recovery,stamina,present,trainer_point",
                    help="comma-separated substrings; only matching endpoints are shown")
    ap.add_argument("--all", action="store_true", help="show every endpoint")
    args = ap.parse_args()

    udid, cfg_path = load_udid(args.profile)
    if not udid:
        print("Could not find udid in auth_config.json — payloads won't be decrypted, "
              "but endpoint names will still be shown.")
    else:
        print(f"Loaded udid from {cfg_path}")

    needles = [s.strip().lower() for s in args.filter.split(",") if s.strip()]
    seen = set()

    def on_message(message, data):
        if message.get("type") != "send":
            if message.get("type") == "error":
                print("Frida error:", message.get("description"))
            return
        p = message["payload"]
        if p.get("type") == "ready":
            print("\n[+] TLS hook installed. Now do the action in-game "
                  "(e.g. use a TP potion). Watching...\n")
            return
        if p.get("type") != "req":
            return
        ep = p.get("endpoint", "")
        match = args.all or any(n in ep.lower() for n in needles)
        payload = decrypt_request_body(p.get("body", ""), udid) if udid else None
        if match:
            print("=" * 70)
            print(f">>> ENDPOINT: {ep}")
            if payload is not None:
                print("payload:", json.dumps(redact(payload), ensure_ascii=False, indent=2, default=str))
            else:
                print("(payload not decrypted)")
            print("=" * 70, flush=True)
        elif ep not in seen:
            seen.add(ep)
            print(f"   ...seen (filtered out): {ep}", flush=True)

    print(f"Attaching to {PROCESS_NAME} ...")
    try:
        session = frida.attach(PROCESS_NAME)
    except Exception as e:
        sys.exit(f"Could not attach (is the game running?): {e}")
    script = session.create_script(SNIFF_JS)
    script.on("message", on_message)
    script.load()
    print("Attached. Filter:", "ALL" if args.all else ",".join(needles))
    print("Press Ctrl+C to stop.\n")
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("\nStopped.")


if __name__ == "__main__":
    main()
