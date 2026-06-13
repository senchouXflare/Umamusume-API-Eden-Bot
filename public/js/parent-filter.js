/* Parent Spark Filter — filters the Parents grid by spark data parsed from the
   already-rendered tooltips. Never removes or reorders DOM nodes (app.js selects
   parents by element index), only toggles display and CSS order. */
(() => {
    'use strict';

    const STORE_KEY = 'parentFilter';
    const CATEGORIES = ['stat', 'aptitude', 'unique', 'skill', 'race', 'scenario'];

    const state = {
        search: '',
        cats: [],
        factor: '',
        minStars: 0,
        scope: 'lineage', // 'lineage' | 'self'
        sort: 'none',     // 'none' | 'factor' | 'stars' | 'rank'
        maxAgeH: 0,       // age filter window in hours (0 = off)
    };
    try { Object.assign(state, JSON.parse(localStorage.getItem(STORE_KEY) || '{}')); } catch (e) {}

    let cards = []; // [{el, name, rank, factors: Map(nameLower -> {label, cat, total, self}), totalStars}]
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

    function factorScore(card) {
        if (!state.factor) return card.totalStars;
        const row = card.factors.get(state.factor);
        if (!row) return 0;
        return state.scope === 'self' ? row.self : row.total;
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
        if (state.factor) {
            if (factorScore(card) < (state.minStars || 1)) return false;
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
            if (state.sort === 'factor') order = -factorScore(card);
            else if (state.sort === 'stars') order = -card.totalStars;
            else if (state.sort === 'rank') order = -(RANK_ORDER[card.rank] || 0);
            card.el.style.order = String(order);
        });
        const count = bar && bar.querySelector('#parent-filter-count');
        if (count) count.textContent = `${shown}/${cards.length} parents`;
        save();
    }

    function rebuildFactorOptions() {
        const select = bar && bar.querySelector('#parent-filter-factor');
        if (!select) return;
        const names = new Map();
        cards.forEach(card => card.factors.forEach((row, key) => {
            if (!names.has(key)) names.set(key, row);
        }));
        const sorted = Array.from(names.entries()).sort((a, b) => {
            if (a[1].cat !== b[1].cat) return a[1].cat.localeCompare(b[1].cat);
            return a[1].label.localeCompare(b[1].label);
        });
        const current = state.factor;
        select.innerHTML = '<option value="">— factor —</option>' + sorted.map(([key, row]) =>
            `<option value="${key.replace(/"/g, '&quot;')}">[${row.cat}] ${row.label}</option>`
        ).join('');
        if (current && names.has(current)) select.value = current;
        else if (current) { state.factor = ''; }
    }

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
            <div class="pf-row">
                <select id="parent-filter-factor" class="form-input pf-select"></select>
                <select id="parent-filter-stars" class="form-input pf-select pf-select-sm">
                    ${[1,2,3,4,5,6,7,8,9].map(n => `<option value="${n}">≥ ${n}★</option>`).join('')}
                </select>
                <select id="parent-filter-scope" class="form-input pf-select pf-select-sm">
                    <option value="lineage">Cả 3 đời</option>
                    <option value="self">Chỉ bản thân</option>
                </select>
                <select id="parent-filter-sort" class="form-input pf-select pf-select-sm">
                    <option value="none">Sort: mặc định</option>
                    <option value="factor">Sort: ★ factor</option>
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

        const factorSel = bar.querySelector('#parent-filter-factor');
        factorSel.addEventListener('change', () => { state.factor = factorSel.value; apply(); });

        const starsSel = bar.querySelector('#parent-filter-stars');
        starsSel.value = String(state.minStars || 1);
        starsSel.addEventListener('change', () => { state.minStars = parseInt(starsSel.value, 10) || 1; apply(); });

        const scopeSel = bar.querySelector('#parent-filter-scope');
        scopeSel.value = state.scope;
        scopeSel.addEventListener('change', () => { state.scope = scopeSel.value; apply(); });

        const sortSel = bar.querySelector('#parent-filter-sort');
        sortSel.value = state.sort;
        sortSel.addEventListener('change', () => { state.sort = sortSel.value; apply(); });

        bar.querySelector('#parent-filter-clear').addEventListener('click', () => {
            state.search = '';
            state.cats = [];
            state.factor = '';
            state.minStars = 0;
            state.sort = 'none';

            state.scope = 'lineage';
            search.value = '';
            factorSel.value = '';
            starsSel.value = '1';
            scopeSel.value = 'lineage';
            sortSel.value = 'none';
            bar.querySelectorAll('.pf-chip').forEach(c => c.classList.remove('active'));
            ageSel.value = '0';
            state.maxAgeH = 0;
            updateAutodelHint();
            apply();
        });

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

        ageSel.addEventListener('change', () => {
            state.maxAgeH = parseInt(ageSel.value, 10) || 0;
            applyAgeFilter();
            updateAutodelHint();
            save();
        });

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

        bar.querySelector('#parent-autodel-btn').addEventListener('click', async () => {
            const maxH = parseInt(ageSel.value, 10) || 0;
            if (!maxH) { alert('Select an age window first.'); return; }
            if (typeof autoDeleteRecentParents === 'function') {
                await autoDeleteRecentParents(maxH);
                updateAutodelHint();
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
