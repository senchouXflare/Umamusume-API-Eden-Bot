# Kế hoạch: Sửa lỗi Runner + Hardening API + Revamp Web UI

Ngày: 2026-06-12

---

## Phân tích lỗi (root cause)

### Crash 1 — `KeyError: 'turn'` (runner.py:240)

Chuỗi sự kiện:
1. Turn 60: `race_entry` bị server trả 208 (SERVER BUSY) xen kẽ 205, hết retry → raise.
2. `_race()` bắt lỗi → reject race → `_fresh_career_state()` → `load`. Nhưng race entry **đã thành công server-side**, state load về cho thấy đang giữa race.
3. Strategy trả `race_progress` → chạy `race_start`/`race_end`/`race_out`.
4. `_race_progress()` trả thẳng response của `race_out` — response này **không có `chara_info`** (nhánh graceful-exit còn trả `payload`, không phải state).
5. Vòng lặp sau: `chara = {}` → `chara["turn"]` (dòng 240, và dòng 234) → KeyError → crash.

### Crash 2 — HTTP 500 Akamai trên `race_out` (crash_trace 01:35)

`client.py call()` (dòng 577–581) chỉ retry network exception, **không retry HTTP 5xx** → crash run.

### Bug phụ trong retry logic (client.py:612–625)

- Retry 208 gọi đệ quy nhưng không truyền `retry_205` → bộ đếm 205 reset về 3 mỗi lần (log "3 left" lặp vô hạn).
- Backoff 208 quá ngắn (0.6–1.4s) và lần retry đầu không sleep ("Delay: 0.000s").
- Retry bằng đệ quy → khó kiểm soát, tổng số lần gọi có thể phình to khi 205/208 xen kẽ.

---

## Phase 1 — Hotfix crash (ưu tiên cao nhất)

**File: `career_bot/runner.py`**

1. Dòng 234 + 240: thay `chara["turn"]` bằng `chara.get("turn", turn)` (fallback biến `turn` của vòng lặp / `self.status["turn"]`).
2. `_race_progress()`: không bao giờ trả `payload` làm state. Sau `race_out` (hoặc graceful-exit), nếu response thiếu `data.chara_info` → gọi `_fresh_career_state(client, strategy)` và trả state đó.
3. Thêm guard đầu vòng lặp `_run()`: nếu `state` thiếu `chara_info` → `state = self._fresh_career_state(client, strategy)` rồi `continue` (chặn mọi đường state rỗng trong tương lai).
4. `_race()` khi race_entry fail 205/208: trước khi `race_planner.reject()`, load lại state và kiểm tra `playing_state`/`race_start_info` — nếu entry đã thành công thì tiếp tục race thay vì reject nhầm race hợp lệ.

**Kết quả mong đợi:** không còn RUNNER CRASH 'turn'; race không bị reject oan.

## Phase 2 — Hardening API client

**File: `uma_api/client.py`**

1. Retry HTTP 5xx (500/502/503/504) với backoff lũy tiến (1s → 2s → 4s... cap 15s, tối đa ~5 lần) thay vì raise ngay.
2. Chuyển retry 205/208 từ đệ quy sang vòng lặp `while` trong `call()`:
   - Bộ đếm 205 và 208 độc lập, không reset lẫn nhau.
   - 208: backoff lũy tiến (1s, 2s, 4s, 8s... + jitter), sleep ngay từ lần đầu.
   - 205: giữ delay ngắn hiện tại.
3. Log retry gọn lại: một dòng/lần, kèm thời gian sleep thực tế.

## Phase 3 — Backend cleanup (`main.py`)

1. **Path traversal fix**: validate `file_name` trong `/assets/data/{file}` và `/races/{file}` (chặn `..`, chỉ cho whitelist extension) — hoặc chuyển sang `StaticFiles` mount của FastAPI.
2. Bỏ hardcode preset `"xguri parent"` (dòng ~1137, ~1840) → lấy preset đang chọn từ request/selection.
3. Thêm `threading.Lock` cho global state (`active_client`, `active_account`, `active_dashboard_data`, `active_selection`).
4. API mới phục vụ UI:
   - `GET /api/career/history` — trả `date_history`/`score_history` + stats theo turn (đã có sẵn trong runner) cho chart.
   - `GET /api/logs/stream` hoặc mở rộng `/api/career/runner` — log đầy đủ có phân loại (info/warn/error), kèm crash trace gần nhất.

## Phase 4 — Web UI revamp (vanilla JS, modular)

**Cấu trúc mới `public/`:**
```
public/
  index.html
  styles/          (tách styles.css theo khu vực: base, layout, panels, modals, charts)
  js/
    api.js         (fetch wrapper + polling qua Web Worker — giữ bgSetInterval)
    state.js       (store nhỏ kiểu pub/sub, thay global state object)
    views/
      login.js
      dashboard.js
      runner.js    (status, action history)
      charts.js    (mới)
      logs.js      (mới)
    main.js        (init + wire-up)
```
Dùng `<script type="module">` — không cần build step.

**Tính năng mới:**
1. **Charts/stats trực quan** (Chart.js qua CDN hoặc canvas tự vẽ):
   - Line chart: stat (SPD/STA/PWR/GUT/WIT) + SP theo turn.
   - Bar/line: max training score mỗi turn (`score_history` đã có sẵn).
   - Tổng kết run: skills/items mua, clocks dùng, kết quả race.
2. **Live log viewer**:
   - Panel log riêng, auto-scroll, filter theo loại (race/train/skill/item/error), tô màu theo mức độ.
   - Hiển thị `last_error` + nút xem crash_trace.txt ngay trong UI.
   - Tăng giới hạn log buffer phía runner (hiện cắt ở 120 dòng) hoặc phân trang.
3. **Polish chung**: fix responsive <850px, ARIA cơ bản cho controls, loại dead code (`if (els.x)` thừa), chuẩn hoá theme qua CSS variables.

**Nguyên tắc:** giữ nguyên API contract hiện có (chỉ thêm endpoint mới), refactor từng view một, UI cũ vẫn chạy được giữa chừng.

## Phase 5 — Kiểm thử

1. Unit test cho `runner._race_progress` / `_run` với state thiếu `chara_info` (mock client).
2. Test retry logic `call()` với chuỗi 208/205/500 giả lập.
3. Chạy 1 career đầy đủ (dev_mode) xác nhận không crash, chart + log viewer hoạt động.
4. Kiểm tra path traversal đã chặn (`GET /assets/data/..%2f..%2fsettings.json`).

## Thứ tự thực hiện & ước lượng

| Phase | Nội dung | Độ ưu tiên | Ước lượng |
|-------|----------|-----------|-----------|
| 1 | Hotfix crash runner | Cao nhất | Nhỏ (~4 chỗ sửa) |
| 2 | Hardening retry client | Cao | Vừa (1 hàm `call()`) |
| 3 | Backend cleanup + API mới | Trung | Vừa |
| 4 | UI revamp + charts + logs | Trung | Lớn (làm theo từng view) |
| 5 | Test | Sau mỗi phase | Nhỏ |

Phase 1+2 nên làm và deploy ngay (độc lập với UI). Phase 3 làm trước Phase 4 vì UI mới cần endpoint mới.
