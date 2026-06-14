/* Parent Spark Filter — filters the Parents grid by spark data parsed from the
   already-rendered tooltips. Never removes or reorders DOM nodes (app.js selects
   parents by element index), only toggles display and CSS order.

   Spark colors (Umamusume): Blue = stat, Pink = aptitude, Green = unique skill,
   White = regular skills / races / scenario. A parent has at most one Blue, one
   Pink and one Green spark, but can carry several White sparks — so Blue/Pink/
   Green are single-select dropdowns and White is a multi-select (AND match).
   The ★ threshold is the lineage total (all 3 generations, max 9★; Green max 3★). */
(() => {
    'use strict';

    const STORE_KEY = 'parentFilter';
    const CATEGORIES = ['stat', 'aptitude', 'unique', 'skill', 'race', 'scenario'];

    // category -> spark-color group
    const CAT_GROUP = {
        stat: 'blue',
        aptitude: 'pink',
        unique: 'green',
        skill: 'white',
        race: 'white',
        scenario: 'white',
        other: 'white',
    };

    const state = {
        search: '',
        cats: [],
        blue: '',         // single factor key (stat)
        pink: '',         // single factor key (aptitude)
        green: '',        // single factor key (unique)
        white: [],        // multiple factor keys (skill / race / scenario)
        minStars: 0,
        sort: 'none',     // 'none' | 'selected' | 'stars' | 'rank'
        maxAgeH: 0,       // age filter window in hours (0 = off)
    };
    try {
        const saved = JSON.parse(localStorage.getItem(STORE_KEY) || '{}');
        Object.assign(state, saved);
        if (!Array.isArray(state.white)) state.white = [];
        delete state.factor; delete state.scope; // migrate legacy single-factor state
    } catch (e) {}

    let cards = []; // [{el, name, rank, factors: Map(key -> {label, cat, total, self}), totalStars}]
    let bar = null;

    const RANK_ORDER = { 'SS+': 13, 'SS': 12, 'S+': 11, 'S': 10, 'A+': 9, 'A': 8, 'B+': 7, 'B': 6, 'C+': 5, 'C': 4, 'D+': 3, 'D': 2, 'E': 1 };

    function save() {
        try { localStorage.setItem(STORE_KEY, JSON.stringify(state)); } catch (e) {}
    }

    function parseCard(el) {
        const factors = new Map();
        let totalStars = 0;
        el.querySelectorAll('.spark-node').forEach((node, nodeIdx) => {
            const isSelf = node.classList.contains('spark-node-self') || nodeIdx === 0;
            node.querySelectorAll('.factor-badge').forEach(badge => {
                const starsEl = badge.querySelector('.stars');
                const stars = starsEl ? (starsEl.textContent.match(/★/g) || []).length : 0;
                const label = badge.textContent.replace(/★/g, '').trim();
                const key = label.toLowerCase();
                let cat = 'other';
                badge.classList.forEach(c => {
                    if (c.startsWith('f-')) cat = c.slice(2);
                });
                if (!factors.has(key)) factors.set(key, { label, cat, total: 0, self: 0 });
                const row = factors.get(key);
                row.total += stars;
                if (isSelf) row.self += stars;
                totalStars += stars;
            });
        });
        const nameEl = el.querySelector('.grid-card-name');
        const rankEl = el.querySelector('.rank-badge');
        return {
            el,
            name: nameEl ? nameEl.textContent.trim() : '',
            rank: rankEl ? rankEl.textContent.trim() : '',
            factors,
            totalStars,
        };
    }

    function reindex() {
        const grid = document.getElementById('parent-grid');
        if (!grid) return;
        cards = Array.from(grid.querySelectorAll(':scope > .grid-card')).map(parseCard);
        rebuildFactorOptions();
    }

    function factorTotal(card, key) {
        if (!key) return 0;
        const row = card.factors.get(key);
        return row ? row.total : 0;
    }

    function selectedKeys() {
        return [state.blue, state.pink, state.green, ...state.white].filter(Boolean);
    }

    function selectedScore(card) {
        return selectedKeys().reduce((sum, key) => sum + factorTotal(card, key), 0);
    }

    function passes(card) {
        if (state.search) {
            const q = state.search.toLowerCase();
            let hit = card.name.toLowerCase().includes(q);
            if (!hit) {
                for (const row of card.factors.values()) {
                    if (row.label.toLowerCase().includes(q)) { hit = true; break; }
                }
            }
            if (!hit) return false;
        }
        if (state.cats.length) {
            let hit = false;
            for (const row of card.factors.values()) {
                if (state.cats.includes(row.cat)) { hit = true; break; }
            }
            if (!hit) return false;
        }
        const min = state.minStars || 1;
        // Blue / Pink / Green — single each
        for (const key of [state.blue, state.pink, state.green]) {
            if (key && factorTotal(card, key) < min) return false;
        }
        // White — must have ALL selected (AND)
        for (const key of state.white) {
            if (factorTotal(card, key) < min) return false;
        }
        return true;
    }

    function apply() {
        if (!cards.length) reindex();
        let shown = 0;
        cards.forEach(card => {
            const ageHidden = card.el.dataset.ageHidden === '1';
            const ok = !ageHidden && passes(card);
            card.el.style.display = ok ? '' : 'none';
            if (ok) shown++;
            let order = 0;
            if (state.sort === 'selected') order = -selectedScore(card);
            else if (state.sort === 'stars') order = -card.totalStars;
            else if (state.sort === 'rank') order = -(RANK_ORDER[card.rank] || 0);
            card.el.style.order = String(order);
        });
        const count = bar && bar.querySelector('#parent-filter-count');
        if (count) count.textContent = `${shown}/${cards.length} parents`;
        save();
    }

    // ---- option building -------------------------------------------------

    function groupedFactors() {
        const groups = { blue: new Map(), pink: new Map(), green: new Map(), white: new Map() };
        cards.forEach(card => card.factors.forEach((row, key) => {
            const g = CAT_GROUP[row.cat] || 'white';
            if (!groups[g].has(key)) groups[g].set(key, row);
        }));
        return groups;
    }

    function sortedEntries(map) {
        return Array.from(map.entries()).sort((a, b) => a[1].label.localeCompare(b[1].label));
    }

    function fillSingleSelect(id, placeholder, map, current) {
        const select = bar && bar.querySelector(id);
        if (!select) return;
        const entries = sortedEntries(map);
        select.innerHTML = `<option value="">${placeholder}</option>` + entries.map(([key, row]) =>
            `<option value="${key.replace(/"/g, '&quot;')}">${row.label}</option>`
        ).join('');
        select.value = (current && map.has(current)) ? current : '';
    }

    function rebuildFactorOptions() {
        if (!bar) return;
        const groups = groupedFactors();
        fillSingleSelect('#pf-blue', '— Blue spark —', groups.blue, state.blue);
        fillSingleSelect('#pf-pink', '— Pink spark —', groups.pink, state.pink);
        fillSingleSelect('#pf-green', '— Green spark —', groups.green, state.green);
        // keep state in sync if a previously-selected option vanished
        if (state.blue && !groups.blue.has(state.blue)) state.blue = '';
        if (state.pink && !groups.pink.has(state.pink)) state.pink = '';
        if (state.green && !groups.green.has(state.green)) state.green = '';

        const panel = bar.querySelector('#pf-white-panel');
        if (panel) {
            const entries = sortedEntries(groups.white);
            const valid = new Set(entries.map(([k]) => k));
            state.white = state.white.filter(k => valid.has(k));
            panel.innerHTML = entries.length
                ? entries.map(([key, row]) => {
                    const checked = state.white.includes(key) ? 'checked' : '';
                    const safe = key.replace(/"/g, '&quot;');
                    return `<label class="pf-white-item"><input type="checkbox" value="${safe}" ${checked}><span>${row.label}</span></label>`;
                }).join('')
                : '<div class="pf-white-empty">No white sparks</div>';
            panel.querySelectorAll('input[type="checkbox"]').forEach(cb => {
                cb.addEventListener('change', () => {
                    const v = cb.value;
                    const idx = state.white.indexOf(v);
                    if (cb.checked && idx < 0) state.white.push(v);
                    else if (!cb.checked && idx >= 0) state.white.splice(idx, 1);
                    updateWhiteToggle();
                    apply();
                });
            });
        }
        updateWhiteToggle();
    }

    function updateWhiteToggle() {
        const toggle = bar && bar.querySelector('#pf-white-toggle');
        if (!toggle) return;
        const n = state.white.length;
        toggle.textContent = n ? `White spark (${n}) ▾` : 'White spark ▾';
        toggle.classList.toggle('has-selection', n > 0);
    }

    // ---- bar -------------------------------------------------------------

    function buildBar() {
        bar = document.createElement('div');
        bar.id = 'parent-filter-bar';
        bar.className = 'parent-filter-bar';
        bar.innerHTML = `
            <div class="pf-row">
                <input type="text" id="parent-filter-search" class="form-input pf-search" placeholder="Search name / factor...">
                <div class="pf-chips">${CATEGORIES.map(c =>
                    `<button type="button" class="pf-chip" data-cat="${c}">${c.toUpperCase()}</button>`).join('')}
                </div>
            </div>
            <div class="pf-row pf-row-sparks">
                <select id="pf-blue" class="form-input pf-select pf-spark pf-spark-blue"></select>
                <select id="pf-pink" class="form-input pf-select pf-spark pf-spark-pink"></select>
                <select id="pf-green" class="form-input pf-select pf-spark pf-spark-green"></select>
                <div class="pf-white" id="pf-white">
                    <button type="button" id="pf-white-toggle" class="form-input pf-select pf-spark pf-spark-white pf-white-toggle">White spark ▾</button>
                    <div class="pf-white-panel" id="pf-white-panel" hidden></div>
                </div>
                <select id="parent-filter-stars" class="form-input pf-select pf-select-sm">
                    ${[1,2,3,4,5,6,7,8,9].map(n => `<option value="${n}">≥ ${n}★</option>`).join('')}
                </select>
                <select id="parent-filter-sort" class="form-input pf-select pf-select-sm">
                    <option value="none">Sort: mặc định</option>
                    <option value="selected">Sort: ★ spark đã chọn</option>
                    <option value="stars">Sort: tổng ★</option>
                    <option value="rank">Sort: rank</option>
                </select>
                <button type="button" id="parent-filter-clear" class="btn btn-sm pf-clear">CLEAR</button>
                <span class="pf-count" id="parent-filter-count"></span>
            </div>
            <div class="pf-row pf-row-autodel">
                <select id="parent-filter-age" class="form-input pf-select pf-select-sm">
                    <option value="0">— Age filter —</option>
                    <option value="1">Created &lt; 1h ago</option>
                    <option value="6">Created &lt; 6h ago</option>
                    <option value="12">Created &lt; 12h ago</option>
                    <option value="24">Created &lt; 24h ago</option>
                    <option value="48">Created &lt; 48h ago</option>
                    <option value="72">Created &lt; 3d ago</option>
                    <option value="168">Created &lt; 7d ago</option>
                </select>
                <button type="button" id="parent-autodel-btn" class="btn btn-sm btn-danger pf-autodel" title="Delete all parents within selected age window">
                    &#128465; Auto-delete
                </button>
                <span class="pf-autodel-hint" id="parent-autodel-hint"></span>
            </div>
        `;

        const search = bar.querySelector('#parent-filter-search');
        search.value = state.search;
        search.addEventListener('input', () => { state.search = search.value.trim(); apply(); });

        bar.querySelectorAll('.pf-chip').forEach(chip => {
            const cat = chip.dataset.cat;
            chip.classList.toggle('active', state.cats.includes(cat));
            chip.addEventListener('click', () => {
                const idx = state.cats.indexOf(cat);
                if (idx >= 0) state.cats.splice(idx, 1); else state.cats.push(cat);
                chip.classList.toggle('active', state.cats.includes(cat));
                apply();
            });
        });

        const blueSel = bar.querySelector('#pf-blue');
        blueSel.addEventListener('change', () => { state.blue = blueSel.value; apply(); });
        const pinkSel = bar.querySelector('#pf-pink');
        pinkSel.addEventListener('change', () => { state.pink = pinkSel.value; apply(); });
        const greenSel = bar.querySelector('#pf-green');
        greenSel.addEventListener('change', () => { state.green = greenSel.value; apply(); });

        // White multi-select open/close
        const whiteWrap = bar.querySelector('#pf-white');
        const whiteToggle = bar.querySelector('#pf-white-toggle');
        const whitePanel = bar.querySelector('#pf-white-panel');
        whiteToggle.addEventListener('click', (e) => {
            e.stopPropagation();
            whitePanel.hidden = !whitePanel.hidden;
        });
        document.addEventListener('click', (e) => {
            if (!whiteWrap.contains(e.target)) whitePanel.hidden = true;
        });

        const starsSel = bar.querySelector('#parent-filter-stars');
        starsSel.value = String(state.minStars || 1);
        starsSel.addEventListener('change', () => { state.minStars = parseInt(starsSel.value, 10) || 1; apply(); });

        const sortSel = bar.querySelector('#parent-filter-sort');
        sortSel.value = state.sort;
        sortSel.addEventListener('change', () => { state.sort = sortSel.value; apply(); });

        // Age filter
        const ageSel = bar.querySelector('#parent-filter-age');
        ageSel.value = String(state.maxAgeH || 0);

        function countRecent(maxH) {
            if (!maxH) return 0;
            const cutoff = Date.now() / 1000 - maxH * 3600;
            const grid = document.getElementById('parent-grid');
            if (!grid) return 0;
            return [...grid.querySelectorAll('.grid-card[data-create-date]')]
                .filter(c => {
                    const cd = parseFloat(c.dataset.createDate);
                    return cd > 0 && cd >= cutoff;
                }).length;
        }

        function updateAutodelHint() {
            const hint = bar.querySelector('#parent-autodel-hint');
            const btn  = bar.querySelector('#parent-autodel-btn');
            if (!hint) return;
            const maxH = parseInt(ageSel.value, 10) || 0;
            if (!maxH) {
                hint.textContent = 'Select age window first';
                if (btn) btn.disabled = true;
            } else {
                const n = countRecent(maxH);
                hint.textContent = `${n} parent(s) in window`;
                if (btn) btn.disabled = (n === 0);
            }
        }

        function applyAgeFilter() {
            const maxH = state.maxAgeH || 0;
            const grid = document.getElementById('parent-grid');
            if (!grid) return;
            if (!maxH) {
                grid.querySelectorAll('.grid-card[data-create-date]').forEach(c => {
                    c.dataset.ageHidden = '0';
                });
            } else {
                const cutoff = Date.now() / 1000 - maxH * 3600;
                grid.querySelectorAll('.grid-card[data-create-date]').forEach(c => {
                    const cd = parseFloat(c.dataset.createDate);
                    const tooOld = !(cd > 0 && cd >= cutoff);
                    c.dataset.ageHidden = tooOld ? '1' : '0';
                    if (tooOld) c.style.display = 'none';
                });
            }
            apply();
        }

        ageSel.addEventListener('change', () => {
            state.maxAgeH = parseInt(ageSel.value, 10) || 0;
            applyAgeFilter();
            updateAutodelHint();
            save();
        });

        bar.querySelector('#parent-filter-clear').addEventListener('click', () => {
            state.search = '';
            state.cats = [];
            state.blue = '';
            state.pink = '';
            state.green = '';
            state.white = [];
            state.minStars = 0;
            state.sort = 'none';
            search.value = '';
            blueSel.value = '';
            pinkSel.value = '';
            greenSel.value = '';
            starsSel.value = '1';
            sortSel.value = 'none';
            bar.querySelectorAll('.pf-chip').forEach(c => c.classList.remove('active'));
            whitePanel.querySelectorAll('input[type="checkbox"]').forEach(cb => { cb.checked = false; });
            updateWhiteToggle();
            ageSel.value = '0';
            state.maxAgeH = 0;
            applyAgeFilter();
            updateAutodelHint();
            apply();
        });

        bar.querySelector('#parent-autodel-btn').addEventListener('click', async () => {
            const maxH = parseInt(ageSel.value, 10) || 0;
            if (!maxH) { alert('Select an age window first.'); return; }
            if (typeof window.autoDeleteRecentParents === 'function') {
                await window.autoDeleteRecentParents(maxH);
                updateAutodelHint();
            } else {
                alert('Auto-delete is unavailable (app.js not loaded).');
            }
        });

        updateAutodelHint();
        return bar;
    }

    function init() {
        const body = document.getElementById('parents-body');
        const grid = document.getElementById('parent-grid');
        if (!body || !grid) return;

        body.insertBefore(buildBar(), grid.parentElement === body ? grid : body.firstChild);

        let timer = 0;
        const observer = new MutationObserver(() => {
            clearTimeout(timer);
            timer = setTimeout(() => { reindex(); apply(); }, 80);
        });
        observer.observe(grid, { childList: true });

        reindex();
        apply();
    }

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', init);
    } else {
        init();
    }
})();
