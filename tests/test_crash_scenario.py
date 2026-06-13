"""End-to-end simulation of the exact crash from 2026-06-12 09:04 log:
race_entry 208 at turn 60 -> entry actually succeeded -> race_progress ->
race_out returns state WITHOUT chara_info -> loop must not crash (KeyError 'turn')."""
import sys, types
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import career_bot.delay as delay
delay.dna_sleep = lambda *a, **k: None

from career_bot.runner import CareerRunner

class Decision:
    def __init__(self, action, payload=None, reason=""):
        self.action, self.payload, self.reason = action, payload or {}, reason

HOME = {"command_info_array": []}

def st(turn, playing_state=1, extra=None):
    d = {"chara_info": {"turn": turn, "playing_state": playing_state, "vital": 50, "max_vital": 100},
         "home_info": HOME}
    if extra:
        d.update(extra)
    return {"data": d}

class FakeClient:
    api_jitter = 0.0
    def __init__(self):
        self.loads = 0
        self.entry_calls = 0
    def race_entry(self, **kw):
        self.entry_calls += 1
        raise Exception("API error 208 on single_mode_free/race_entry")
    def load_career(self):
        self.loads += 1
        if self.loads == 1:
            # after failed entry: server says we're mid-race
            return st(60, 2, {"race_start_info": {"program_id": 7}})
        return st(61, 1)
    def race_start(self, is_short, current_turn):
        return {"data": {}}
    def race_end(self, current_turn):
        return {"data": {}}
    def race_out(self, current_turn):
        # the poison state: no chara_info at all
        return {"data": {"race_reward": []}}
    def wait_turn_delay(self):
        pass

class FakeStrategy:
    def __init__(self):
        self.steps = 0
    def next_decision(self, state, preset):
        self.steps += 1
        data = state.get("data") or {}
        chara = data.get("chara_info") or {}
        ps = chara.get("playing_state") or 0
        if ps in (2, 3, 4):
            return Decision("race_progress", {"current_turn": chara["turn"], "phase": "start", "chara_info": chara}, "resume race")
        if self.steps == 1:
            return Decision("race", {"program_id": 7, "current_turn": chara["turn"], "_strategy": self}, "scheduled race")
        return Decision("idle", {}, "test done")
    def _choice(self, e):
        return 1

def test_full_crash_sequence_survives():
    r = CareerRunner(str(ROOT))
    r.status["running"] = True
    client = FakeClient()
    # patch out skill/item phases to isolate the loop
    r._buy_skills = lambda c, s, p, f: s
    r._handle_items = lambda c, s, p, b: s
    r.item_manager.handle_pre_race = lambda c, s, p, pl, st_, rp: (s, 0)
    r.item_manager.use_attempt_events = []
    r._run(client, {"name": "t", "scenario_id": 4}, st(60), FakeStrategy(), max_steps=10)
    assert r.status["last_error"] == "", f"crashed: {r.status['last_error']}"
    assert client.entry_calls == 1
    assert client.loads >= 2, "must reload after entry failure and after chara-less race_out"

def test_resume_loop_guard_stops_infinite_102():
    """Server stuck: every load says in-race, every race op returns 102.
    Runner must abort with a clear error instead of spinning forever."""
    r = CareerRunner(str(ROOT))
    r.status["running"] = True
    r._buy_skills = lambda c, s, p, f: s
    r._handle_items = lambda c, s, p, b: s

    class StuckClient:
        api_jitter = 0.0
        def __init__(self):
            self.resets = 0
        def load_career(self):
            return st(60, 3, {"race_start_info": {"program_id": 7}})
        def hard_reset(self):
            self.resets += 1
            return st(60, 3, {"race_start_info": {"program_id": 7}})
        def race_start(self, is_short, current_turn):
            raise Exception("API error 102 on race_start")
        def race_end(self, current_turn):
            raise Exception("API error 102 on race_end")
        def race_out(self, current_turn):
            raise Exception("API error 102 on race_out")
        def wait_turn_delay(self):
            pass

    class StuckStrategy:
        def next_decision(self, state, preset):
            chara = (state.get("data") or {}).get("chara_info") or {}
            return Decision("race_progress", {"current_turn": chara["turn"], "phase": "start", "chara_info": chara}, "resume race")
        def _choice(self, e):
            return 1

    client = StuckClient()
    r._run(client, {"name": "t", "scenario_id": 4}, st(60, 3, {"race_start_info": {"program_id": 7}}), StuckStrategy(), max_steps=100)
    assert "race resume loop" in r.status["last_error"], f"got: {r.status['last_error']}"
    assert client.resets >= 1, "hard recovery should have been attempted"
