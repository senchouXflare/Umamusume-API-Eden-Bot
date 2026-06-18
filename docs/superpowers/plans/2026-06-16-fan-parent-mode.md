# Fan/Parent Mode Integration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Thêm switch per-run **Fan Farm / Parent Farm** vào Eden bot — Fan giữ nguyên não Eden hiện tại, Parent dùng não thông minh port từ repo Mcqueen + nhắm factor cụ thể — mà không đụng UI/UX của Eden.

**Architecture:** Hai MANT strategy song song chọn theo `mode`. `MantStrategy` (Eden, bất biến) = Fan; `MantParentStrategy` (copy từ Mcqueen) = Parent. Runner chọn brain qua `MANT_STRATEGIES[mode]`. Parent profile bơm bộ knob thông minh qua `apply_mode_profile()`. Item nâng cao (energy rescue, deck-aware) thêm vào `items.py` sau cổng knob (default off → Fan không đổi). UI thêm toggle qua module riêng + sửa tối thiểu `app.js`.

**Tech Stack:** Python 3.10, FastAPI (`main.py`), pytest, vanilla JS (`public/`), jsdom cho UI test.

---

## File Structure

**Tạo mới:**
- `career_bot/scenarios/mant_parent.py` — não Parent (copy Mcqueen mant.py, đổi tên class).
- `public/js/mode-switch.js` — module toggle Fan/Parent + Parent targets, ghi vào payload run.
- `tests/test_mode_switch.py` — test registry, profile merge, API contract.
- `tests/test_parent_brain.py` — test scoring Parent (rainbow, stat-balance, race-skip, factor target).
- `tests/test_fan_unchanged.py` — golden test: Fan = MantStrategy hiện tại.
- `vendor/mcqueen-ref/` — bản clone donor để port (gitignored).

**Sửa:**
- `career_bot/runner.py` — `MANT_STRATEGIES` map; `start(..., mode="fan")`; chọn strategy theo mode.
- `career_bot/presets.py` — `apply_mode_profile(preset, mode, target_factors)` + `PARENT_PROFILE`.
- `career_bot/items.py` — port method rescue/deck-aware, gọi sau cổng knob.
- `main.py` — `RunCareerRequest.mode`/`target_factors`; truyền `mode` xuống runner (cả dev path).
- `public/app.js` — nhét `mode`/`target_factors` vào 2 nhánh payload (~dòng 1899-1922).
- `public/index.html` — `<script src="/js/mode-switch.js">` + markup toggle.
- `public/css/shell.css` — style toggle + khối Parent targets.
- `tests/test_ui_contract.py` — assert `mode-switch.js` được tham chiếu.
- `.gitignore` — thêm `vendor/mcqueen-ref/`.

---

## Task 0: Lấy mã nguồn donor (Mcqueen) để port

**Files:**
- Create: `vendor/mcqueen-ref/` (clone, gitignored)
- Modify: `.gitignore`

- [ ] **Step 1: Clone donor repo**

Run:
```bash
mkdir -p vendor
git clone --depth 1 https://github.com/Mcqueenkel/Mcqueen-uma-auto vendor/mcqueen-ref
```
Expected: clone thành công, có `vendor/mcqueen-ref/career_bot/scenarios/mant.py`.

- [ ] **Step 2: Gitignore donor**

Thêm dòng vào cuối `.gitignore`:
```
vendor/mcqueen-ref/
```

- [ ] **Step 3: Verify donor brain self-contained**

Run:
```bash
grep -n "^from \|^import " vendor/mcqueen-ref/career_bot/scenarios/mant.py
```
Expected: chỉ có `from career_bot.events import EventManager` và `from career_bot.scenarios.base import Decision, ScenarioStrategy` — không phụ thuộc module diverged. Nếu có import khác, dừng và báo lại.

- [ ] **Step 4: Commit**

```bash
git add .gitignore
git commit -m "chore: vendor Mcqueen reference for porting (gitignored)"
```

---

## Task 1: Khung mode trong runner (Parent tạm = Fan)

Mục tiêu: thêm trục `mode` vào runner, `mode="parent"` tạm chạy `MantStrategy` cho tới khi có brain Parent thật ở Task 3. Fan path không đổi.

**Files:**
- Modify: `career_bot/runner.py:23-25` (STRATEGIES), `:102` (start signature), `:106-148`
- Test: `tests/test_mode_switch.py`

- [ ] **Step 1: Write the failing test**

Tạo `tests/test_mode_switch.py`:
```python
from career_bot.runner import resolve_mant_strategy
from career_bot.scenarios.mant import MantStrategy


def test_fan_mode_uses_eden_strategy():
    assert resolve_mant_strategy("fan") is MantStrategy


def test_unknown_mode_defaults_to_fan():
    assert resolve_mant_strategy("") is MantStrategy
    assert resolve_mant_strategy("bogus") is MantStrategy


def test_parent_mode_resolves_to_a_strategy():
    cls = resolve_mant_strategy("parent")
    assert cls is not None and hasattr(cls, "next_decision")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_mode_switch.py -v`
Expected: FAIL — `ImportError: cannot import name 'resolve_mant_strategy'`.

- [ ] **Step 3: Add MANT_STRATEGIES + resolver in runner.py**

Trong `career_bot/runner.py`, ngay sau khối `STRATEGIES = { 4: MantStrategy, }` (dòng ~23-25) thêm:
```python
# Mode-specific MANT brains. Fan = Eden's proven engine (untouched).
# Parent is wired in Task 3; temporarily falls back to MantStrategy.
MANT_STRATEGIES = {
    "fan": MantStrategy,
    "parent": MantStrategy,  # replaced by MantParentStrategy in Task 3
}


def resolve_mant_strategy(mode):
    return MANT_STRATEGIES.get((mode or "fan").strip().lower(), MantStrategy)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_mode_switch.py -v`
Expected: PASS (3 test).

- [ ] **Step 5: Thread `mode` qua start()**

Sửa `career_bot/runner.py` `start()` (dòng 102):
```python
    def start(self, client, preset, initial_result, max_steps=2500, burn_clocks=False, dev_mode=False, mode="fan"):
```
Trong thân `start()`, thay khối chọn strategy (dòng 106-109):
```python
            scenario_id = int(preset.get("scenario_id") or 4)
            if scenario_id == 4:
                strategy_cls = resolve_mant_strategy(mode)
            else:
                strategy_cls = STRATEGIES.get(scenario_id)
            if not strategy_cls:
                raise RuntimeError(f"No runner for scenario {scenario_id}")
            self.mode = (mode or "fan").strip().lower()
```
Thêm `"mode": self.mode,` vào dict `self.status` (sau dòng `"scenario_id": scenario_id,` ~119).

- [ ] **Step 6: Run full suite + syntax**

Run: `python -c "import career_bot.runner" && pytest tests/test_mode_switch.py -v`
Expected: import OK, test PASS.

- [ ] **Step 7: Commit**

```bash
git add career_bot/runner.py tests/test_mode_switch.py
git commit -m "feat(runner): mode-aware MANT strategy selection (parent temp=fan)"
```

---

## Task 2: Parent profile knob (apply_mode_profile)

Mục tiêu: định nghĩa bộ knob mặc định cho Parent; Fan không thêm knob. Preset người dùng override được.

**Files:**
- Modify: `career_bot/presets.py` (thêm `PARENT_PROFILE` + `apply_mode_profile`)
- Test: `tests/test_mode_switch.py` (mở rộng)

- [ ] **Step 1: Write the failing test**

Thêm vào `tests/test_mode_switch.py`:
```python
from career_bot.presets import apply_mode_profile, hydrate_preset


def test_fan_profile_unchanged():
    base = hydrate_preset({"name": "p"})
    out = apply_mode_profile(dict(base), "fan", [])
    assert out == base  # Fan adds nothing


def test_parent_profile_injects_knobs():
    base = hydrate_preset({"name": "p"})
    out = apply_mode_profile(dict(base), "parent", [])
    assert out["rainbow_bonus"] > 0
    assert out["stat_balance"] is True
    assert out["race_skip_train_stat"] == 30
    assert out["rescue_good_training"] is True


def test_user_preset_overrides_parent_profile():
    base = hydrate_preset({"name": "p"})
    base["rainbow_bonus"] = 0.99  # user-set value present before profile
    out = apply_mode_profile(dict(base), "parent", [])
    assert out["rainbow_bonus"] == 0.99


def test_target_factors_attached_for_parent_only():
    base = hydrate_preset({"name": "p"})
    tf = [{"factor": "speed", "min_star": 3}]
    assert apply_mode_profile(dict(base), "parent", tf)["target_factors"] == tf
    assert apply_mode_profile(dict(base), "fan", tf)["target_factors"] == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_mode_switch.py -v`
Expected: FAIL — `ImportError: cannot import name 'apply_mode_profile'`.

- [ ] **Step 3: Implement PARENT_PROFILE + apply_mode_profile**

Thêm vào cuối `career_bot/presets.py` (trước `class PresetStore` hoặc sau nó, miễn module-level):
```python
# Smart-brain knob defaults for Parent Farm. Values mirror Mcqueen's hydrate
# defaults. A knob already present on the preset (user-set) is NOT overwritten.
PARENT_PROFILE = {
    "rainbow_explicit": True,
    "rainbow_bonus": 0.12,
    "rainbow_stack_bonus": 0.06,
    "rainbow_useful_ref": 0.12,
    "junior_bond_rush": True,
    "hint_count_scale": 0.5,
    "wit_energy_boost": 0.25,
    "score_skill_points": True,
    "skill_point_weight": 1.0,
    "stat_balance": True,
    "stat_balance_threshold": 0.55,
    "stat_balance_boost": 0.6,
    "rescue_good_training": True,
    "rescue_score_threshold": 0.55,
    "rescue_min_vital": 25,
    "rescue_vital_margin": 12,
    "failure_hard_cap": 50,
    "race_skip_train_stat": 30,
}


def apply_mode_profile(preset, mode, target_factors=None):
    """Return preset enriched for the given mode. Fan adds nothing (parity).
    Parent injects PARENT_PROFILE defaults without clobbering user-set keys,
    and attaches target_factors."""
    data = dict(preset or {})
    m = (mode or "fan").strip().lower()
    data["mode"] = m
    if m == "parent":
        for key, value in PARENT_PROFILE.items():
            data.setdefault(key, value)
        data["target_factors"] = list(target_factors or [])
    else:
        data["target_factors"] = []
    return data
```

> Ghi chú: `hydrate_preset()` (dòng 89) KHÔNG đổi — vì vậy `test_fan_profile_unchanged` chỉ đúng nếu hydrate không sinh sẵn key `mode`/`target_factors`. Test so sánh `out == base`; vì Fan path set `data["mode"]="fan"` và `data["target_factors"]=[]`, hãy thêm 2 dòng sau vào CUỐI `hydrate_preset` (sau `data["mant_config"] = {}` dòng 115) để base cũng có chúng, giữ test parity đúng:
> ```python
>     data["mode"] = "fan"
>     data["target_factors"] = []
> ```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_mode_switch.py -v`
Expected: PASS (toàn bộ, gồm 4 test mới).

- [ ] **Step 5: Commit**

```bash
git add career_bot/presets.py tests/test_mode_switch.py
git commit -m "feat(presets): Parent profile knobs + apply_mode_profile"
```

---

## Task 3: MantParentStrategy (port não Mcqueen)

Mục tiêu: tạo brain Parent thật từ donor, đăng ký vào `MANT_STRATEGIES["parent"]`.

**Files:**
- Create: `career_bot/scenarios/mant_parent.py`
- Modify: `career_bot/runner.py` (import + map)
- Test: `tests/test_parent_brain.py`

- [ ] **Step 1: Copy donor brain & rename class**

Run:
```bash
cp vendor/mcqueen-ref/career_bot/scenarios/mant.py career_bot/scenarios/mant_parent.py
sed -i 's/^class MantStrategy(ScenarioStrategy):/class MantParentStrategy(ScenarioStrategy):/' career_bot/scenarios/mant_parent.py
```
Expected: `career_bot/scenarios/mant_parent.py` tồn tại, có `class MantParentStrategy(ScenarioStrategy):`.

- [ ] **Step 2: Verify it imports**

Run: `python -c "from career_bot.scenarios.mant_parent import MantParentStrategy; print(MantParentStrategy.scenario_id)"`
Expected: in ra `4`. Nếu lỗi import (vd thiếu hằng số), so sánh với donor và copy hằng số module-level còn thiếu vào đầu file.

- [ ] **Step 3: Write the failing test (brain wiring)**

Tạo `tests/test_parent_brain.py`:
```python
from career_bot.scenarios.mant_parent import MantParentStrategy
from career_bot.runner import resolve_mant_strategy


def test_parent_strategy_registered():
    assert resolve_mant_strategy("parent") is MantParentStrategy


def test_parent_has_smart_helpers():
    s = MantParentStrategy()
    for name in ("_rainbow_count", "_bondable_count", "_command_stat_gain",
                 "_can_rescue_training", "_train_outvalues_race"):
        assert hasattr(s, name), f"missing {name}"
```

- [ ] **Step 4: Run test to verify it fails**

Run: `pytest tests/test_parent_brain.py -v`
Expected: FAIL trên `test_parent_strategy_registered` (vẫn trỏ MantStrategy).

- [ ] **Step 5: Register MantParentStrategy in runner**

Sửa `career_bot/runner.py`:
- Sau dòng 13 (`from career_bot.scenarios.mant import MantStrategy`) thêm:
```python
from career_bot.scenarios.mant_parent import MantParentStrategy
```
- Trong `MANT_STRATEGIES` đổi `"parent"`:
```python
MANT_STRATEGIES = {
    "fan": MantStrategy,
    "parent": MantParentStrategy,
}
```

- [ ] **Step 6: Run tests**

Run: `pytest tests/test_parent_brain.py tests/test_mode_switch.py -v`
Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add career_bot/scenarios/mant_parent.py career_bot/runner.py tests/test_parent_brain.py
git commit -m "feat(scenarios): MantParentStrategy (Mcqueen smart brain) wired as parent mode"
```

---

## Task 4: Test scoring Parent (rainbow / stat-balance / race-skip)

Mục tiêu: khoá hành vi não Parket bằng test trên state giả, để Task 7 (factor target) và refactor sau không phá ngầm.

**Files:**
- Test: `tests/test_parent_brain.py` (mở rộng)

- [ ] **Step 1: Inspect donor scoring inputs**

Run:
```bash
sed -n '274,435p' vendor/mcqueen-ref/career_bot/scenarios/mant.py
```
Đọc để biết `_score_command(self, command, data, chara, preset)` đọc field nào: `command["training_partner_array"]`, `command["tips_event_partner_array"]`, `command["params_inc_dec_info_array"]`, `chara["evaluation_info_array"]`, `chara["vital"]`, `chara["turn"]`.

- [ ] **Step 2: Write scoring tests**

Thêm vào `tests/test_parent_brain.py` (điều chỉnh khoá field cho khớp Step 1 nếu cần):
```python
import copy
from career_bot.presets import apply_mode_profile, hydrate_preset

PRESET = apply_mode_profile(hydrate_preset({"name": "t"}), "parent", [])


def _cmd(command_id=101, partners=(), hints=(), gains=None):
    return {
        "command_id": command_id,
        "training_partner_array": list(partners),
        "tips_event_partner_array": list(hints),
        "params_inc_dec_info_array": gains or [
            {"target_type": 1, "value": 10}, {"target_type": 30, "value": 5},
        ],
        "failure_rate": 0,
    }


def _chara(turn=12, vital=80, bonds=None):
    bonds = bonds or {}
    return {
        "turn": turn, "vital": vital,
        "evaluation_info_array": [
            {"training_partner_id": pid, "evaluation": val} for pid, val in bonds.items()
        ],
    }


def test_rainbow_training_scores_higher_than_plain():
    s = MantParentStrategy()
    data = {}
    plain = s._score_command(_cmd(partners=[1]), data, _chara(bonds={1: 30}), PRESET)
    rainbow = s._score_command(_cmd(partners=[1, 2]), data,
                               _chara(bonds={1: 85, 2: 85}), PRESET)
    assert rainbow > plain


def test_command_stat_gain_sums_param_values():
    s = MantParentStrategy()
    assert s._command_stat_gain(_cmd(gains=[{"target_type": 1, "value": 12},
                                            {"target_type": 2, "value": 8}])) == 20


def test_rainbow_count_counts_maxed_partners():
    s = MantParentStrategy()
    assert s._rainbow_count(_cmd(partners=[1, 2, 3]), _chara(bonds={1: 85, 2: 80, 3: 40})) == 2
```

> Lưu ý: tên field/đường đọc bond trong donor có thể khác (vd `evaluation` vs `bond`). Sau Step 1, chỉnh helper `_chara`/`_cmd` cho khớp donor TRƯỚC khi chạy. Mục tiêu là test PASS phản ánh đúng logic donor, không phải ép donor theo test.

- [ ] **Step 3: Run tests, adjust fixtures to match donor**

Run: `pytest tests/test_parent_brain.py -v`
Nếu FAIL vì sai tên field: đọc lại donor (Step 1), sửa fixture `_cmd`/`_chara`, chạy lại tới khi PASS.
Expected: PASS.

- [ ] **Step 4: Commit**

```bash
git add tests/test_parent_brain.py
git commit -m "test(parent): lock rainbow/stat-gain scoring behavior"
```

---

## Task 5: Golden test — Fan Farm không đổi hành vi

Mục tiêu: bằng chứng Fan path cho quyết định y hệt `MantStrategy` hiện tại.

**Files:**
- Test: `tests/test_fan_unchanged.py`

- [ ] **Step 1: Write the test**

Tạo `tests/test_fan_unchanged.py`:
```python
from career_bot.runner import resolve_mant_strategy
from career_bot.scenarios.mant import MantStrategy
from career_bot.presets import apply_mode_profile, hydrate_preset


def test_fan_resolves_to_untouched_eden_strategy():
    assert resolve_mant_strategy("fan") is MantStrategy


def test_fan_preset_has_no_smart_knobs():
    out = apply_mode_profile(hydrate_preset({"name": "p"}), "fan", [])
    for knob in ("rainbow_bonus", "stat_balance", "rescue_good_training",
                 "race_skip_train_stat"):
        assert knob not in out, f"Fan profile must not contain {knob}"
```

- [ ] **Step 2: Run test**

Run: `pytest tests/test_fan_unchanged.py -v`
Expected: PASS.

- [ ] **Step 3: Commit**

```bash
git add tests/test_fan_unchanged.py
git commit -m "test(fan): golden guard that Fan mode keeps Eden brain + clean profile"
```

---

## Task 6: API — thêm `mode` & `target_factors`, truyền xuống runner

**Files:**
- Modify: `main.py:1159-1176` (RunCareerRequest), `:2128-2143` (run_career), `manage_career_loop`
- Test: `tests/test_mode_switch.py` (mở rộng)

- [ ] **Step 1: Write the failing test**

Thêm vào `tests/test_mode_switch.py`:
```python
def test_run_request_defaults_to_fan():
    from main import RunCareerRequest
    req = RunCareerRequest()
    assert req.mode == "fan"
    assert req.target_factors == []


def test_run_request_accepts_parent():
    from main import RunCareerRequest
    req = RunCareerRequest(mode="parent", target_factors=[{"factor": "speed", "min_star": 3}])
    assert req.mode == "parent"
    assert req.target_factors[0]["factor"] == "speed"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_mode_switch.py -k run_request -v`
Expected: FAIL — `RunCareerRequest` chưa có `mode`.

- [ ] **Step 3: Add fields to RunCareerRequest**

Sửa `main.py` `class RunCareerRequest` (sau dòng 1176 `dev_mode: bool = False`):
```python
    mode: str = "fan"
    target_factors: list = []
```

- [ ] **Step 4: Apply profile + pass mode in run_career**

Trong `main.py` `run_career` (dòng 2075+), ngay sau khi có `preset` (sau `resolve_preset(...)` được gọi, trước khi dùng), thêm:
```python
        from career_bot.presets import apply_mode_profile
        preset = apply_mode_profile(preset, req.mode, req.target_factors)
```
Sửa lời gọi `career_runner.start(...)` (dòng 2136-2143) thêm `mode=req.mode`:
```python
            career_runner.start(
                active_client,
                preset,
                result,
                max(1, min(int(req.max_steps or 2500), 3000)),
                burn_clocks=req.burn_clocks,
                dev_mode=req.dev_mode,
                mode=req.mode,
            )
```

- [ ] **Step 5: Dev-loop path also honors mode**

Tìm `def manage_career_loop` trong `main.py`:
```bash
grep -n "def manage_career_loop\|career_runner.start" main.py
```
Trong `manage_career_loop`, tại mọi lời gọi `career_runner.start(...)` thêm `mode=req.mode`. Nếu hàm dùng `preset` cục bộ, đảm bảo nó cũng đi qua `apply_mode_profile(preset, req.mode, req.target_factors)` một lần (đặt ngay đầu hàm sau khi nhận `preset`).

- [ ] **Step 6: Run tests + import check**

Run: `python -c "import main" && pytest tests/test_mode_switch.py -k run_request -v`
Expected: import OK (nếu thiếu dependency hệ thống, ít nhất chạy `python -c "import ast; ast.parse(open('main.py').read())"` để check cú pháp), test PASS.

- [ ] **Step 7: Commit**

```bash
git add main.py tests/test_mode_switch.py
git commit -m "feat(api): RunCareerRequest.mode/target_factors threaded to runner (+dev loop)"
```

---

## Task 7: Factor targeting trong Parent brain

Mục tiêu: Parent brain thiên training/skill theo `target_factors`. Đây là logic MỚI (donor không có).

**Files:**
- Modify: `career_bot/scenarios/mant_parent.py`
- Test: `tests/test_parent_brain.py` (mở rộng)

- [ ] **Step 1: Write the failing test**

Thêm vào `tests/test_parent_brain.py`:
```python
def test_factor_target_boosts_matching_stat_training():
    s = MantParentStrategy()
    preset_speed = apply_mode_profile(hydrate_preset({"name": "t"}), "parent",
                                      [{"factor": "speed", "min_star": 3}])
    preset_none = apply_mode_profile(hydrate_preset({"name": "t"}), "parent", [])
    chara = _chara(bonds={1: 85})
    speed_cmd = _cmd(command_id=101, partners=[1])   # 101 = Speed training
    boosted = s._score_command(speed_cmd, {}, chara, preset_speed)
    base = s._score_command(speed_cmd, {}, chara, preset_none)
    assert boosted > base


def test_factor_bias_zero_when_no_targets():
    s = MantParentStrategy()
    preset = apply_mode_profile(hydrate_preset({"name": "t"}), "parent", [])
    assert s._factor_bias(_cmd(command_id=101), preset) == 0.0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_parent_brain.py -k factor -v`
Expected: FAIL — `_factor_bias` chưa tồn tại / không có boost.

- [ ] **Step 3: Implement `_factor_bias` + hook into `_score_command`**

Trong `career_bot/scenarios/mant_parent.py` thêm helper (đặt cạnh các helper stat, dùng `TRAINING_COMMANDS`/`STAT_TARGETS` đã có ở đầu file):
```python
    # Map target-factor names -> training command stat index (0..4)
    FACTOR_STAT_INDEX = {
        "speed": 0, "stamina": 1, "power": 2, "guts": 3, "wit": 4, "wisdom": 4,
    }

    def _factor_bias(self, command, preset):
        """Extra score for trainings/skills matching Parent target_factors.
        0.0 when no targets. Stat factors boost matching stat training;
        weight scales with requested min_star (default 1)."""
        targets = (preset or {}).get("target_factors") or []
        if not targets:
            return 0.0
        cmd_id = int(command.get("command_id") or 0)
        stat_idx = TRAINING_COMMANDS.get(cmd_id)
        if stat_idx is None:
            return 0.0
        weight = float((preset or {}).get("factor_target_weight", 0.08))
        bias = 0.0
        for t in targets:
            name = str(t.get("factor") or "").strip().lower()
            idx = self.FACTOR_STAT_INDEX.get(name)
            if idx is not None and idx == stat_idx:
                stars = float(t.get("min_star") or 1)
                bias += weight * max(1.0, stars)
        return bias
```
Trong `_score_command`, ngay TRƯỚC câu `return` cuối, cộng bias:
```python
        score += self._factor_bias(command, preset)
        return score
```
(Đọc đoạn cuối `_score_command` để biết biến tổng tên là `score` hay khác; chỉnh tên biến cho khớp.)

Thêm default knob vào `PARENT_PROFILE` trong `career_bot/presets.py`:
```python
    "factor_target_weight": 0.08,
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_parent_brain.py -k factor -v`
Expected: PASS.

- [ ] **Step 5: Run full parent suite**

Run: `pytest tests/test_parent_brain.py tests/test_mode_switch.py tests/test_fan_unchanged.py -v`
Expected: PASS toàn bộ.

- [ ] **Step 6: Commit**

```bash
git add career_bot/scenarios/mant_parent.py career_bot/presets.py tests/test_parent_brain.py
git commit -m "feat(parent): factor targeting bias in scoring"
```

---

## Task 8: Items — energy rescue + deck-aware (gated, Fan an toàn)

Mục tiêu: port method item nâng cao từ donor vào `items.py`, chỉ kích hoạt khi knob bật (Parent). Fan không đổi vì knob off.

**Files:**
- Modify: `career_bot/items.py`
- Test: `tests/test_items_gated.py`

- [ ] **Step 1: Locate donor item methods + Eden call sites**

Run:
```bash
grep -n "_rescue_energy_target\|_anklet_target\|_is_glow_stick_race\|def use_items\|def buy_shop_items\|def _energy_targets\|def _charm_target" vendor/mcqueen-ref/career_bot/items.py
grep -n "def use_items\|def buy_shop_items\|def _energy_targets\|def _charm_target\|def handle" career_bot/items.py
```
Ghi lại số dòng hai bên để port đúng method và xác định nơi gọi.

- [ ] **Step 2: Write the failing test**

Tạo `tests/test_items_gated.py`:
```python
from career_bot.items import MantItemManager


def test_rescue_disabled_without_knob():
    m = MantItemManager()
    preset = {}  # Fan: no rescue knob
    # _rescue_energy_target must no-op (return None) when knob absent/false
    assert m._rescue_energy_target({"item_list": []}, vital=10, rest_threshold=48, preset=preset) is None


def test_rescue_enabled_with_knob_and_inventory():
    m = MantItemManager()
    preset = {"rescue_good_training": True, "rescue_vital_margin": 12}
    data = {"item_list": [{"item_id": 2002, "num": 1}]}  # Vita 40
    out = m._rescue_energy_target(data, vital=20, rest_threshold=48, preset=preset)
    assert out is not None  # picks an energy item to clear threshold+margin
```

- [ ] **Step 3: Run test to verify it fails**

Run: `pytest tests/test_items_gated.py -v`
Expected: FAIL — `_rescue_energy_target` chưa tồn tại trong Eden items.py.

- [ ] **Step 4: Port methods from donor, add knob gate**

Copy thân các method `_rescue_energy_target`, `_anklet_target`, `_is_glow_stick_race` từ `vendor/mcqueen-ref/career_bot/items.py` (số dòng từ Step 1) vào `career_bot/items.py` trong `class MantItemManager`. Thêm/giữ signature `_rescue_energy_target(self, data, vital, rest_threshold, preset, ...)` và mở đầu bằng cổng knob:
```python
    def _rescue_energy_target(self, data, vital, rest_threshold, preset, margin=None):
        if not (preset or {}).get("rescue_good_training"):
            return None
        margin = (preset or {}).get("rescue_vital_margin", 12) if margin is None else margin
        # ... donor body: find smallest energy item lifting vital > rest_threshold + margin ...
```
Tại nơi `use_items()` / `_energy_targets()` của Eden quyết định mua vita (call sites từ Step 1), thêm nhánh: nếu `preset.get("rescue_good_training")` thì gọi `_rescue_energy_target(...)` trước; ngược lại giữ logic Eden cũ nguyên vẹn. Tương tự `_anklet_target` chỉ gọi khi `preset.get("deck_aware_items")` (thêm knob này vào `PARENT_PROFILE` = True).

- [ ] **Step 5: Run test to verify it passes**

Run: `pytest tests/test_items_gated.py -v`
Expected: PASS (cả 2). Nếu donor body dùng hằng `ENERGY_ITEM_VALUES`/`GOOD_LUCK_CHARM_ID`, copy chúng lên đầu `items.py` nếu chưa có.

- [ ] **Step 6: Guard Fan parity**

Thêm test vào `tests/test_items_gated.py`:
```python
def test_anklet_gated_off_for_fan():
    m = MantItemManager()
    assert m._rescue_energy_target({"item_list": [{"item_id": 2002, "num": 1}]},
                                   vital=20, rest_threshold=48, preset={}) is None
```
Run: `pytest tests/test_items_gated.py -v` → PASS.

- [ ] **Step 7: Add deck_aware_items knob + commit**

Thêm `"deck_aware_items": True,` vào `PARENT_PROFILE` (`career_bot/presets.py`).
```bash
git add career_bot/items.py career_bot/presets.py tests/test_items_gated.py
git commit -m "feat(items): gated energy-rescue + deck-aware item port (off for Fan)"
```

---

## Task 9: UI — toggle Fan/Parent + Parent targets (giữ design Eden)

**Files:**
- Create: `public/js/mode-switch.js`
- Modify: `public/index.html`, `public/css/shell.css`, `public/app.js:1899-1922`
- Test: `tests/test_ui_contract.py`

- [ ] **Step 1: Write the failing UI-contract test**

Thêm vào `tests/test_ui_contract.py` (theo mẫu test có sẵn trong file — đọc cách nó đọc `index.html`):
```python
def test_mode_switch_script_referenced():
    html = (BASE_DIR / "public" / "index.html").read_text(encoding="utf-8")
    assert "/js/mode-switch.js" in html


def test_mode_switch_module_exists():
    assert (BASE_DIR / "public" / "js" / "mode-switch.js").exists()
```
(Dùng đúng biến `BASE_DIR`/helper mà file test hiện có; nếu khác tên, theo file.)

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_ui_contract.py -k mode_switch -v`
Expected: FAIL.

- [ ] **Step 3: Create mode-switch.js**

Tạo `public/js/mode-switch.js`:
```javascript
// Fan/Parent run-mode toggle. Reads/writes a single source of truth on
// window.__umaRunMode so app.js can fold it into the /api/career/run payload.
(function () {
  const KEY = 'uma_run_mode';
  const FKEY = 'uma_target_factors';
  const state = {
    mode: localStorage.getItem(KEY) || 'fan',
    targetFactors: JSON.parse(localStorage.getItem(FKEY) || '[]'),
  };
  window.__umaRunMode = state;

  function persist() {
    localStorage.setItem(KEY, state.mode);
    localStorage.setItem(FKEY, JSON.stringify(state.targetFactors));
    render();
  }
  function setMode(m) { state.mode = (m === 'parent') ? 'parent' : 'fan'; persist(); }

  function render() {
    const root = document.getElementById('run-mode-switch');
    if (!root) return;
    root.querySelectorAll('[data-mode]').forEach(btn => {
      btn.classList.toggle('active', btn.dataset.mode === state.mode);
    });
    const targets = document.getElementById('parent-targets');
    if (targets) targets.hidden = state.mode !== 'parent';
  }

  function init() {
    const root = document.getElementById('run-mode-switch');
    if (!root) return;
    root.addEventListener('click', e => {
      const btn = e.target.closest('[data-mode]');
      if (btn) setMode(btn.dataset.mode);
    });
    render();
  }
  if (document.readyState !== 'loading') init();
  else document.addEventListener('DOMContentLoaded', init);
})();
```

- [ ] **Step 4: Add markup to index.html**

Trong `public/index.html`, trong panel Run (gần nút RUN — tìm `id="..."` của nút run để đặt kề), thêm:
```html
<div id="run-mode-switch" class="mode-switch" role="group" aria-label="Run mode">
  <button type="button" data-mode="fan" class="mode-btn active">Fan Farm</button>
  <button type="button" data-mode="parent" class="mode-btn">Parent Farm</button>
</div>
<div id="parent-targets" class="parent-targets" hidden>
  <!-- factor chips reuse parent-filter styling; populated later -->
</div>
```
Thêm trước `</body>` (sau các script hiện có): `<script src="/js/mode-switch.js?v=1" defer></script>`

- [ ] **Step 5: Style in shell.css**

Thêm vào cuối `public/css/shell.css` (dùng token có sẵn `--accent-primary`, surface...):
```css
/* Run mode switch */
.mode-switch { display:inline-flex; gap:2px; background:var(--surface,#151a23);
  border:1px solid rgba(255,255,255,.07); border-radius:10px; padding:2px; }
.mode-switch .mode-btn { border:0; background:transparent; color:var(--text-dim,#8b93a3);
  padding:6px 14px; border-radius:8px; cursor:pointer; font:inherit; transition:.15s; }
.mode-switch .mode-btn.active { background:var(--accent-primary,#2dd4bf); color:#06231f; }
.parent-targets { margin-top:10px; }
```

- [ ] **Step 6: Fold mode into payload (app.js)**

Trong `public/app.js` `startCareer()` (dòng ~1899-1922), thêm vào CẢ HAI nhánh object `body` (sau `dev_mode: state.devEnabled`):
```javascript
                mode: (window.__umaRunMode && window.__umaRunMode.mode) || 'fan',
                target_factors: (window.__umaRunMode && window.__umaRunMode.targetFactors) || []
```
(Nhánh `activeCareer` ở 1899-1903 và nhánh đầy đủ 1904-1921 — thêm vào cả hai.)

- [ ] **Step 7: Run UI tests + JS syntax**

Run:
```bash
node --check public/js/mode-switch.js && node --check public/app.js && pytest tests/test_ui_contract.py -v
```
Expected: node OK, pytest PASS.

- [ ] **Step 8: Commit**

```bash
git add public/js/mode-switch.js public/index.html public/css/shell.css public/app.js tests/test_ui_contract.py
git commit -m "feat(ui): Fan/Parent run-mode toggle + parent targets (Eden design)"
```

---

## Task 10: Verify toàn bộ + smoke 2 mode

**Files:** không sửa code (chỉ chạy + sửa lỗi phát sinh).

- [ ] **Step 1: Full test suite**

Run: `pytest -q`
Expected: tất cả PASS (gồm suite cũ: crash, stale race, tp recovery, ui contract).

- [ ] **Step 2: Backend syntax/import**

Run: `python -c "import ast; [ast.parse(open(f).read()) for f in ['main.py','career_bot/runner.py','career_bot/presets.py','career_bot/items.py','career_bot/scenarios/mant_parent.py']]" && echo OK`
Expected: `OK`.

- [ ] **Step 3: Smoke dev_mode mỗi mode (thủ công, nếu có game/account)**

Chạy server, ở UI chọn Fan → RUN một career dev_mode → xác nhận log chạy như cũ. Đổi Parent → RUN → xác nhận log thể hiện rainbow/rescue (não Parent hoạt động). Không crash.
Nếu không có môi trường game: ghi chú lại để người dùng tự smoke; coi như test tự động ở Step 1-2 là cổng tối thiểu.

- [ ] **Step 4: Final commit / tidy**

```bash
git add -A && git commit -m "test: full-suite verification for Fan/Parent integration"
```

---

## Self-Review notes

- **Spec coverage:** Mode registry (T1), Parent profile knobs (T2), MantParentStrategy port (T3), brain scoring lock (T4), Fan parity guard (T5), API mode/target_factors (T6), factor targeting (T7), gated items rescue/deck-aware (T8), UI toggle giữ design Eden (T9), full verify + smoke 2 mode (T10). URA & Discord notify đã loại theo spec.
- **Donor dependency:** mọi task port trỏ `vendor/mcqueen-ref/` (Task 0). Nếu execution không có mạng, cung cấp donor thủ công vào `vendor/mcqueen-ref/`.
- **Field-name risk:** Task 4/7 ghi rõ phải đọc donor `_score_command` (T4 Step 1) để chỉnh fixture/biến tổng cho khớp trước khi chốt PASS — tránh ép donor theo test.
- **Fan safety:** T5 + T8 Step 6 là cổng chống regression; mọi knob Parket dùng `setdefault`, item mới sau cổng knob.
