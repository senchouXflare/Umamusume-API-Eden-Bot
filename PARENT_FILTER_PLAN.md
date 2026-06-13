# Plan: Parent Spark Filter

Ngày: 2026-06-12 · Trạng thái: chờ duyệt

## Mục tiêu

Tab **Parents** hiện chỉ xem được spark khi hover từng con. Thêm thanh filter ngay trên
grid để lọc/sắp xếp parent theo chính dữ liệu spark đó — chọn parent tốt nhanh hơn nhiều.

## Dữ liệu có sẵn (đã xác minh trong app.js + factor_map.json)

Mỗi parent card đã render kèm tooltip chứa:

| Trường | Nội dung |
|---|---|
| factors | Tên + số sao (1–3★) + nhóm: `stat` (Speed/Stamina/...), `aptitude` (sân/cự ly/chiến thuật), `unique` (skill độc quyền), `skill`, `race`, `scenario` |
| lineage | 3 node: bản thân (self) + parent 1 + parent 2 — tổng tối đa 9★/factor |
| wins | Số trận thắng G1/G2/G3 từng node |
| rank | Hạng tổng (S+, S, A+...) |

## Thiết kế filter bar (chèn trên `#parent-grid`)

```
[ Search factor...        ] [STAT][APT][UNIQUE][SKILL][RACE][SCENARIO]
[ Factor: Speed ▾ ] [ Min ★: 6 ▾ ] [ Phạm vi: Cả 3 đời ▾ ] [ Sort: ★ giảm dần ▾ ] [CLEAR]
                                                  Hiển thị 12/48 parents
```

1. **Search box**: gõ tên factor (vd "speed", "URA", tên skill) → chỉ hiện parent có factor khớp.
2. **Category chips** (bật/tắt): lọc theo nhóm spark.
3. **Factor + Min sao**: dropdown liệt kê mọi factor đang có trong kho + ngưỡng tổng sao
   (tính tổng cộng dồn cả 3 đời, vd "Speed ≥ 6★").
4. **Phạm vi**: tính sao chỉ trên `self` hoặc cộng cả lineage (mặc định cả 3 đời).
5. **Sort**: theo tổng sao của factor đã chọn / theo tổng sao stat / theo rank — dùng CSS
   `order`, KHÔNG đổi thứ tự DOM.
6. **Đếm kết quả** + nút **CLEAR** reset tất cả.
7. Trạng thái filter lưu `localStorage`, khôi phục khi mở lại.

## Kỹ thuật (tiếp tục nguyên tắc không sửa app.js)

- Module mới `public/js/parent-filter.js` (~250 dòng):
  - **Đọc dữ liệu từ DOM** đã render (parse `.sparks-tooltip .factor-badge` + sao + nhóm
    từ class `f-<category>`) → build index mỗi card. Không cần API mới, không sửa backend.
  - **MutationObserver** trên `#parent-grid`: app.js re-render grid bất cứ lúc nào →
    tự re-index + re-apply filter.
  - **Ẩn/hiện bằng `display:none`** và sort bằng CSS `order` — phần tử giữ nguyên vị trí
    DOM nên logic chọn parent theo index của app.js (autoLoadCareerSelection,
    click selection) không bị ảnh hưởng. Đây là ràng buộc quan trọng nhất.
  - Filter bar chèn vào đầu `#parents-body` (trước grid), chỉ hiện ở tab Parents.
- CSS: thêm section 14 vào `css/shell.css` (chips, bar, count).
- `index.html`: thêm `<script src="/js/parent-filter.js?v=1" defer>`.

## Test

1. `tests/test_ui_contract.py`: script được tham chiếu + file tồn tại.
2. jsdom: dựng grid giả 4 parent với spark khác nhau → kiểm: search đúng, chip category
   đúng, min-star tính tổng lineage đúng, scope self-only đúng, sort đổi `order` đúng,
   CLEAR reset, MutationObserver re-apply sau khi grid re-render, **không** element nào
   bị xóa/đổi chỗ trong DOM.
3. pytest toàn bộ suite cũ vẫn pass.

## Rủi ro & xử lý

| Rủi ro | Xử lý |
|---|---|
| app.js re-render mất filter | MutationObserver re-apply tự động |
| Ẩn card làm lệch index chọn parent | Chỉ dùng display/order, không remove/reorder DOM |
| Tên factor skill có ký tự lạ | So khớp lowercase + trim, search theo substring |
| Kho parent lớn (100+) | Index 1 lần/render, filter chạy trên mảng đã index — O(n) |
