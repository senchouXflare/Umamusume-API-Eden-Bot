# Spec: Tích hợp não Mcqueen vào Eden — Switch Fan Farm / Parent Farm

Ngày: 2026-06-16 · Trạng thái: đã duyệt thiết kế

## Mục tiêu

Ghép "bộ não training thông minh" của repo `Mcqueenkel/Mcqueen-uma-auto` vào Eden bot,
giữ nguyên UI/UX của Eden, và thêm một **switch per-run** cho phép chọn giữa hai mode:

- **Fan Farm** — giữ NGUYÊN logic Eden hiện tại (cày fan tốc độ/volume, 5 phút/run, đã tối ưu).
- **Parent Farm** — dùng não Mcqueen (build chất lượng) + nhắm factor/spark cụ thể để săn parent tốt.

## Bối cảnh & cơ sở khả thi

Cả Eden và Mcqueen đều là fork của engine **Sweepy**, cấu trúc thư mục y hệt:
`career_bot/{runner,items,skills,races,presets,events,master_data,report}.py`,
`career_bot/scenarios/{base,mant}.py`, `uma_api/client.py`, `main.py`, `public/`.

Điểm mấu chốt: cả hai chia sẻ cùng interface quyết định
`ScenarioStrategy.next_decision(state, preset) -> Decision(action, payload, reason)`
(định nghĩa trong `career_bot/scenarios/base.py`). Vì vậy não Mcqueen ghép vào dưới dạng
một strategy mới mà không phải đụng runtime loop hay UI.

Khác biệt chính (đã xác minh):

| Khía cạnh | Eden | Mcqueen |
|---|---|---|
| Scenario | MANT (`mant.py` ~481 dòng) | MANT (~683) + URA |
| Training brain | scoring cơ bản | rainbow/friendship scoring, stat-balance, hint scaling, wit-as-rest, SP awareness, junior bond-rush, energy rescue |
| Items | energy target tĩnh (~1288 dòng) | deck-aware, rescue charm+energy, glow-stick theo race (~1427 dòng) |
| Race skip | không | `_train_outvalues_race()` |
| Preset knob | ít | ~25 knob tinh chỉnh |
| UI | bản revamp dark của Eden | UI mặc định (loại bỏ) |
| Discord notify | không | `notify.py` (NGOÀI phạm vi) |

## Phạm vi (đã chốt)

**Trong phạm vi:** toàn bộ training brain Mcqueen, energy rescue + deck-aware items,
race-skip logic, factor targeting cho Parent Farm, switch per-run trong UI Eden.

**Ngoài phạm vi:** scenario URA, Discord notify (`notify.py`). Chỉ làm MANT.

## Kiến trúc

Runner hiện chọn strategy bằng `scenario_id` (4 = MANT). Thêm trục thứ hai là **mode**:

```
RunCareerRequest { preset_name, max_steps, burn_clocks, dev_mode, mode }   ← thêm "mode": "fan"|"parent"
        │
   resolve_preset(preset_name) + apply_mode_profile(preset, mode)
        │
   runner.start(client, preset, mode=...)
        │
   MANT_STRATEGIES = { "fan": MantStrategy,           # Eden gốc — KHÔNG đụng
                       "parent": MantParentStrategy }  # port từ Mcqueen
        │
   strategy.next_decision(state, preset)   ← interface giữ nguyên
```

`scenario_id` vẫn = 4 cho cả hai (đều MANT). `mode` chỉ chọn brain + profile knob.
Mặc định `mode="fan"` để mọi đường gọi cũ giữ hành vi cũ.

## Thành phần

### 1. Mode registry & resolution (runner + main.py)

- `career_bot/runner.py`: thêm `MANT_STRATEGIES` map; `start()` nhận tham số `mode`
  (default `"fan"`), chọn strategy theo `mode` thay vì hardcode `MantStrategy`.
- `main.py`: `RunCareerRequest` thêm field `mode: str = "fan"` và (Parent) `target_factors`;
  `/api/career/run` truyền `mode` xuống `runner.start(...)`.

### 2. Profile knob mặc định theo mode (presets.py)

- `apply_mode_profile(preset, mode)`: nếu `mode=="parent"`, merge bộ default Parent
  (rainbow_bonus, rainbow_stack_bonus, stat_balance(+threshold/boost), hint_count_scale,
  wit_energy_boost, score_skill_points(+weight), junior_bond_rush, rescue_*(good_training,
  score_threshold, min_vital, vital_margin), failure_hard_cap, race_skip_train_stat,
  target_factors) **trước** khi merge preset người dùng (preset override được).
- `mode=="fan"`: không thêm knob mới → Fan profile byte-for-byte như hiện tại.

### 3. MantParentStrategy (scenarios/mant_parent.py)

- Class mới kế thừa `MantStrategy`, override `_score_command()` và thêm helper port từ
  Mcqueen `career_bot/scenarios/mant.py`: `_rainbow_count`, `_bondable_count`,
  `_command_stat_gain`, `_can_rescue_training`, `_train_outvalues_race`, cùng stat-balance,
  hint scaling, wit-as-rest, junior bond-rush, SP awareness.
- `MantStrategy` của Eden **không sửa**.

### 4. Items — bổ sung additive, mặc định tắt cho Fan (items.py)

- Thêm method Mcqueen (`_rescue_energy_target`, `_anklet_target` deck-aware, glow-stick
  theo race) vào `items.py`, **đứng sau cổng knob** (`rescue_good_training`, deck-match...).
- Fan profile không bật các knob này → đường đi Fan Farm không đổi hành vi.

### 5. Parent factor targeting

- Parent preset có `target_factors`, vd `[{"factor":"speed","min_star":3},
  {"factor":"apt_mile"},{"unique":"<skill>"}]`.
- `MantParentStrategy` dùng nó để: thiên training về stat của factor (blue spark), ưu tiên
  race G1 hợp aptitude (race factor + win), nâng trọng số skill/unique (pink/white spark).
- UI chọn factor **tái dùng danh mục factor của `public/js/parent-filter.js`** — không cần
  data/endpoint mới.

### 6. UI — giữ trọn design Eden

- Toggle **Fan / Parent** trong panel Run, theo design dark hiện đại (token `css/shell.css`).
- Khi chọn Parent → lộ khối "Parent targets" (chip chọn factor, style như parent-filter).
- Module mới `public/js/mode-switch.js`; sửa **tối thiểu** `public/app.js` để nhét `mode`
  (+ `target_factors`) vào payload `/api/career/run`. Trạng thái mode lưu `localStorage`.

## Ranh giới & cô lập

- `MantStrategy` (Fan) bất biến — Fan Farm không thể regression.
- `MantParentStrategy` là unit độc lập, test riêng được.
- Items mở rộng đứng sau knob (default off cho Fan).
- UI là module thêm; đụng `app.js`/`main.py`/`runner.py` tối thiểu, rollback qua git.

## Kiểm thử

1. **Fan không đổi**: với cùng state mock, quyết định của `mode=fan` giống `MantStrategy`
   hiện tại (golden test trước/sau).
2. **Parent brain**: test `_score_command` Parent cho rainbow bonus, stat-balance,
   wit-as-rest, energy rescue, race-skip, factor-target bằng state giả.
3. **Profile merge**: `apply_mode_profile` nạp đúng knob; preset override đúng.
4. **API contract**: `RunCareerRequest.mode` mặc định "fan"; payload có `mode`/`target_factors`.
5. **UI contract**: `tests/test_ui_contract.py` — `mode-switch.js` được tham chiếu, toggle
   ghi đúng `mode` vào payload (jsdom).
6. **Smoke**: chạy 1 career dev_mode mỗi mode, không crash.

## Phân pha

| Pha | Nội dung |
|---|---|
| P1 | Khung mode + registry + request field; `mode=parent` tạm chạy như fan (xanh test) |
| P2 | Port training brain → `MantParentStrategy` |
| P3 | Items knob-gated (rescue + deck-aware) |
| P4 | Factor targeting trong Parent brain |
| P5 | UI toggle + Parent targets |
| P6 | Test toàn bộ + smoke 2 mode |

## Rủi ro & xử lý

| Rủi ro | Xử lý |
|---|---|
| Regression Fan Farm | Fan dùng đúng `MantStrategy` cũ; golden test so quyết định |
| Items mở rộng ảnh hưởng Fan | Mọi method mới sau cổng knob, default off |
| Đụng app.js nhiều | Chỉ thêm 1 điểm nhét `mode` vào payload + module riêng |
| Factor target sai dữ liệu | Tái dùng danh mục factor đã có của parent-filter.js |
| Mcqueen knob lệch master_data Eden | Port kèm test scoring trên state giả của Eden |
