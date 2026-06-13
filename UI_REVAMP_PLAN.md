# Kế hoạch UI Revamp 2.0 — Clean Dark Modern

Ngày: 2026-06-12 · Hướng đã chốt: **clean dark hiện đại**, thực hiện toàn bộ, tự test.

## Mục tiêu

Giao diện kiểu dashboard chuyên nghiệp (Linear/Vercel): nền tối dịu, một màu accent,
typography rõ, spacing thoáng, dễ nhìn khi treo máy lâu — thay cho neon pink hiện tại.

## Nguyên tắc kỹ thuật (quan trọng nhất)

**Không đụng vào `app.js`** (2435 dòng logic nghiệp vụ đã chạy ổn). Toàn bộ revamp qua:

1. `public/index.html` — viết lại layout shell, **giữ nguyên 100% id/class mà app.js
   phụ thuộc** (73 id + 20 query selector đã inventory bằng script).
2. `public/css/shell.css` — layer thiết kế mới load SAU `styles.css`, ghi đè design
   tokens (mọi component cũ dùng `var(--accent-primary)` v.v. nên tự đổi theo) +
   layout mới + restyle component chính.
3. `public/js/nav.js` — rail điều hướng (focus Setup/Library, mở Monitor, theme) —
   chỉ gọi các nút/logic có sẵn của app.js, không thay logic.
4. `main.py` — thêm route `/css/{file}` (an toàn path như `/js/`).

Rollback dễ: mọi thứ nằm trong git, file cũ không bị xóa.

## Design system

| Token | Giá trị mới |
|---|---|
| Nền | `#0b0e14` → `#11151d` (slate đậm, không tím) |
| Surface/card | `#151a23`, border `rgba(255,255,255,.07)`, radius 10px |
| Accent | Teal `#2dd4bf` (hover `#5eead4`); danger `#f87171`; warn `#fbbf24` |
| Text | `#e6e9ef` chính, `#8b93a3` phụ |
| Font | Inter/system-ui; mono cho log: ui-monospace |
| Hiệu ứng | Bỏ glow neon; shadow mềm 1 lớp; transition 0.15s |
| Theme cũ | Click logo vẫn đổi theme (giữ #theme-toggle); theme-blue map sang accent xanh dương |

## Layout mới

```
┌──────────────────────────────────────────────────────────┐
│ TOPBAR  logo · account strip (TP/carrot/gold/clock/career)│
│         · delay + fate/burn/dev · logout                  │
├───┬──────────────────────────────────────────────────────┤
│ R │  SETUP & RUN (trái, 460px)   │  LIBRARY (phải, fluid) │
│ A │  · Team slots (5 card)       │  · Decks               │
│ I │  · Preset + skills           │  · Friend supports     │
│ L │  · Master data               │  · Trainees            │
│   │  · Race schedule             │  · Parents             │
│   │  · RUN + action history      │  · Owned cards         │
├───┴──────────────────────────────────────────────────────┤
│ MONITOR drawer (chart · live log · crash trace)          │
└──────────────────────────────────────────────────────────┘
```

Rail (trái, 48px): nút focus Setup / focus Library (gọi nút collapse có sẵn),
nút Monitor, nút theme. Mobile <900px: 1 cột, rail thành bottom của topbar.

## Component restyle chính (trong shell.css)

- Buttons: nền surface, viền mảnh, accent khi primary; bỏ uppercase tracking quá đà.
- Inputs/selects: nền `#0d1117`, focus ring accent 2px.
- Section: card có header sticky nhỏ, chevron xoay mượt.
- Team slots: card ngang có avatar + tên + nút đổi; trạng thái trống rõ ràng.
- Data grids (deck/friend/trainee/parent/card): card hover nhẹ, selected = viền accent.
- Action history: bảng gọn, pill màu theo loại action (đồng bộ màu monitor).
- Modals (delete career, skill editor): backdrop blur nhẹ, panel radius lớn.
- Monitor drawer: đồng bộ token mới.
- Scrollbar mảnh, focus-visible outline, empty-state có hướng dẫn.

## Phases

| # | Việc | Output |
|---|---|---|
| 1 | Inventory DOM contract (xong) | 73 id + selectors |
| 2 | Shell mới | index.html + nav.js |
| 3 | Design layer | css/shell.css (~600 dòng) |
| 4 | Backend route | /css/{file} trong main.py |
| 5 | Verify tự động | script id-coverage (mọi id app.js cần đều có trong HTML mới), node --check, server smoke (200 + traversal 404), jsdom monitor |

## Test matrix

1. `tests/test_ui_contract.py` — parse app.js lấy id/selector, assert tồn tại trong index.html mới (chạy được bằng pytest, không cần browser).
2. Server smoke: `/`, `/styles.css`, `/css/shell.css`, `/js/nav.js`, `/js/monitor.js` đều 200; path traversal 404.
3. jsdom: monitor mount/mở/log/chart không lỗi.
4. Python/JS syntax toàn bộ.
