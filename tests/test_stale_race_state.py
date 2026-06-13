"""Reproduces the stuck-at-T60 state observed in trace 2026-06-12 09:49:
playing_state=3 + race_start_info present, but race 74 turn 60 is already in
race_history (rank 1) and home commands are enabled. The strategy must NOT
return race_progress / race — it must continue the turn normally."""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import career_bot.delay as delay
delay.dna_sleep = lambda *a, **k: None

from career_bot.scenarios.mant import MantStrategy
from career_bot.races import RacePlanner

def stuck_state():
    return {"data": {
        "chara_info": {
            "turn": 60, "playing_state": 3, "race_program_id": 74,
            "race_running_style": 1, "vital": 47, "max_vital": 108,
            "motivation": 5, "skill_point": 156, "state": 0,
            "speed": 789, "stamina": 504, "power": 840, "guts": 395, "wiz": 451,
        },
        "race_start_info": {"program_id": 74, "continue_num": 0},
        "race_history": [
            {"program_id": 73, "result_rank": 1, "turn": 59},
            {"program_id": 74, "result_rank": 1, "turn": 60},
        ],
        "home_info": {"command_info_array": [
            {"command_type": 1, "command_id": 101, "is_enable": 1, "failure_rate": 8,
             "params_inc_dec_info_array": [{"target_type": 1, "value": 10}]},
            {"command_type": 7, "command_id": 701, "is_enable": 1, "failure_rate": 0},
        ]},
        "unchecked_event_array": [],
    }}

def make_strategy():
    return MantStrategy(RacePlanner(str(ROOT)))

def test_stale_race_state_does_not_race():
    s = make_strategy()
    d = s.next_decision(stuck_state(), {"scenario_id": 4})
    assert d.action not in ("race_progress", "race"), f"still stuck: {d.action} ({d.reason})"

def test_genuine_inrace_state_still_resumes():
    s = make_strategy()
    state = stuck_state()
    # race NOT in history yet -> must still resume the race
    state["data"]["race_history"] = [{"program_id": 73, "result_rank": 1, "turn": 59}]
    d = s.next_decision(state, {"scenario_id": 4})
    assert d.action == "race_progress", f"expected race_progress, got {d.action}"
