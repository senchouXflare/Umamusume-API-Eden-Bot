/* Career Monitor — bottom drawer with LIVE LOG (left) and STATS CHART (right)
   side by side. Self-contained: injects its own DOM, polls only while open. */
(() => {
    'use strict';

    const POLL_LOG_MS = 2000;
    const POLL_CHART_MS = 5000;

    const STAT_SERIES = [
        { key: 'speed', label: 'SPD', color: '#4fc3f7' },
        { key: 'stamina', label: 'STA', color: '#ffb74d' },
        { key: 'power', label: 'PWR', color: '#e57373' },
        { key: 'guts', label: 'GUT', color: '#ba68c8' },
        { key: 'wit', label: 'WIT', color: '#81c784' },
        { key: 'skill_point', label: 'SP', color: '#fff176' },
    ];

    const LOG_KIND = [
        { match: /^(error|race_clock_failed|command_blocked_loop|race_resume_loop)$/, kind: 'error' },
        { match: /reconciled|recover|race_reject|race_skip/, kind: 'warn' },
        { match: /^race/, kind: 'race' },
        { match: /^(skills|items_buy|items_use)$/, kind: 'gain' },
        { match: /^(command_exec|command|train|event_choice)/, kind: 'info' },
    ];

    const state = {
        open: false,
        filter: 'all',
        paused: false,
        crashVisible: false,
        logTimer: 0,
        chartTimer: 0,
        lastLogKey: '',
        history: null,
        userClosed: false,
        wasRunning: false,
    };

    function el(tag, cls, html) {
        const node = document.createElement(tag);
        if (cls) node.className = cls;
        if (html !== undefined) node.innerHTML = html;
        return node;
    }

    function esc(value) {
        return String(value ?? '').replace(/[&<>"']/g, c => ({
            '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'
        }[c]));
    }

    async function getJson(url) {
        const res = await fetch(url, { headers: { 'Accept': 'application/json' } });
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        return res.json();
    }

    /* ---------- DOM ---------- */

    const root = el('div', 'monitor-drawer collapsed');
    root.id = 'career-monitor';
    root.setAttribute('role', 'region');
    root.setAttribute('aria-label', 'Career monitor');
    root.innerHTML = `
        <button class="monitor-handle" id="monitor-toggle" type="button" aria-expanded="false" aria-controls="monitor-body">
            <span class="monitor-handle-dot" id="monitor-live-dot"></span>
            MONITOR
            <span class="monitor-handle-status" id="monitor-status"></span>
            <span class="monitor-handle-chevron">&#9650;</span>
        </button>
        <div class="monitor-body" id="monitor-body">
            <div class="monitor-split">
                <div class="monitor-col monitor-col-log">
                    <div class="monitor-col-head">
                        <span class="monitor-col-title">LIVE LOG</span>
                        <div class="monitor-tools" id="monitor-tools"></div>
                    </div>
                    <div class="monitor-log" id="monitor-log" aria-live="polite"></div>
                </div>
                <div class="monitor-col monitor-col-chart">
                    <div class="monitor-col-head">
                        <span class="monitor-col-title" id="monitor-chart-title">STATS</span>
                        <button class="monitor-filter" id="monitor-crash-toggle" type="button">CRASH TRACE</button>
                    </div>
                    <div class="monitor-pane-chart" id="monitor-pane-chart">
                        <canvas id="monitor-chart-canvas" height="220" aria-label="Stat progression chart"></canvas>
                        <div class="monitor-chart-legend" id="monitor-chart-legend"></div>
                        <div class="monitor-empty" id="monitor-chart-empty">No career data yet — start a run to see stat progression.</div>
                    </div>
                    <pre class="monitor-crash" id="monitor-crash" hidden>Loading...</pre>
                </div>
            </div>
        </div>
    `;

    const FILTERS = ['all', 'race', 'gain', 'info', 'warn', 'error'];
    const tools = root.querySelector('#monitor-tools');
    FILTERS.forEach(f => {
        const btn = el('button', `monitor-filter ${f === 'all' ? 'active' : ''}`, f.toUpperCase());
        btn.type = 'button';
        btn.dataset.filter = f;
        btn.addEventListener('click', () => {
            state.filter = f;
            tools.querySelectorAll('.monitor-filter[data-filter]').forEach(b => b.classList.toggle('active', b === btn));
            state.lastLogKey = '';
            refreshLog();
        });
        tools.appendChild(btn);
    });
    const pauseBtn = el('button', 'monitor-filter monitor-pause', 'PAUSE');
    pauseBtn.type = 'button';
    pauseBtn.addEventListener('click', () => {
        state.paused = !state.paused;
        pauseBtn.textContent = state.paused ? 'RESUME' : 'PAUSE';
        pauseBtn.classList.toggle('active', state.paused);
    });
    tools.appendChild(pauseBtn);

    /* ---------- behaviour ---------- */

    function setOpen(open) {
        state.open = open;
        root.classList.toggle('collapsed', !open);
        root.querySelector('#monitor-toggle').setAttribute('aria-expanded', String(open));
        if (open) {
            startPolling();
        } else {
            stopPolling();
        }
    }

    function setCrashVisible(visible) {
        state.crashVisible = visible;
        root.querySelector('#monitor-pane-chart').hidden = visible;
        root.querySelector('#monitor-crash').hidden = !visible;
        root.querySelector('#monitor-chart-title').textContent = visible ? 'CRASH TRACE' : 'STATS';
        root.querySelector('#monitor-crash-toggle').classList.toggle('active', visible);
        root.querySelector('#monitor-crash-toggle').textContent = visible ? 'SHOW STATS' : 'CRASH TRACE';
        if (visible) refreshCrash();
        else drawChart();
    }

    function startPolling() {
        stopPolling();
        state.logTimer = setInterval(() => {
            refreshLog();
            refreshStatus();
        }, POLL_LOG_MS);
        state.chartTimer = setInterval(() => {
            if (!state.crashVisible) refreshChart();
        }, POLL_CHART_MS);
        refreshStatus();
        refreshLog();
        refreshChart();
    }

    function stopPolling() {
        if (state.logTimer) clearInterval(state.logTimer);
        if (state.chartTimer) clearInterval(state.chartTimer);
        state.logTimer = 0;
        state.chartTimer = 0;
    }

    /* ---------- status strip ---------- */

    async function refreshStatus() {
        try {
            const data = await getJson('/api/career/runner');
            const runner = data.runner || {};
            const dot = root.querySelector('#monitor-live-dot');
            const status = root.querySelector('#monitor-status');
            const running = Boolean(runner.running);
            dot.classList.toggle('live', running);
            dot.classList.toggle('error', Boolean(runner.last_error));
            root.classList.toggle('is-live', running);
            if (running) {
                status.textContent = `turn ${runner.turn ?? '?'} · ${runner.last_action || 'running'}`;
            } else if (runner.last_error) {
                status.textContent = `stopped · ${String(runner.last_error).slice(0, 60)}`;
            } else if (runner.finished) {
                status.textContent = 'finished';
            } else {
                status.textContent = 'idle — start a career to see live data';
            }
            if (running && !state.wasRunning && !state.open && !state.userClosed) {
                setOpen(true);
            }
            state.wasRunning = running;
        } catch (e) { /* server unreachable; keep quiet */ }
    }

    /* ---------- live log ---------- */

    function classifyAction(action) {
        const name = String(action || '');
        for (const rule of LOG_KIND) {
            if (rule.match.test(name)) return rule.kind;
        }
        return 'info';
    }

    async function refreshLog() {
        if (state.paused || !state.open) return;
        let runner;
        try {
            const data = await getJson('/api/career/runner');
            runner = data.runner || {};
        } catch (e) { return; }
        const rows = (runner.log || []).map(item => ({
            ...item,
            kind: classifyAction(item.action),
        })).filter(item => state.filter === 'all' || item.kind === state.filter);

        const key = rows.length ? `${rows.length}:${rows[rows.length - 1].id}:${state.filter}` : `0:${state.filter}`;
        if (key === state.lastLogKey) return;
        state.lastLogKey = key;

        const box = root.querySelector('#monitor-log');
        const stick = box.scrollHeight - box.scrollTop - box.clientHeight < 40;
        box.innerHTML = rows.length ? rows.map(item => `
            <div class="monitor-log-row kind-${item.kind}">
                <span class="monitor-log-time">${esc(item.time || '')}</span>
                <span class="monitor-log-turn">T${esc(item.turn ?? 0)}</span>
                <span class="monitor-log-action">${esc(item.action || '')}</span>
                <span class="monitor-log-detail">${esc(item.detail || '')}</span>
            </div>
        `).join('') : '<div class="monitor-empty">No log entries (for this filter) yet.</div>';
        if (stick) box.scrollTop = box.scrollHeight;
    }

    /* ---------- crash trace ---------- */

    async function refreshCrash() {
        const pane = root.querySelector('#monitor-crash');
        try {
            const data = await getJson('/api/career/crash_trace');
            pane.textContent = (data.trace || '').trim() || 'No crash trace recorded. Clean so far!';
        } catch (e) {
            pane.textContent = `Could not load crash trace: ${e.message}`;
        }
    }

    /* ---------- chart ---------- */

    async function refreshChart() {
        if (!state.open) return;
        try {
            const data = await getJson('/api/career/history');
            state.history = data;
        } catch (e) { return; }
        drawChart();
    }

    function drawChart() {
        const canvas = root.querySelector('#monitor-chart-canvas');
        const empty = root.querySelector('#monitor-chart-empty');
        const legendBox = root.querySelector('#monitor-chart-legend');
        if (!canvas || state.crashVisible) return;
        const stats = (state.history && state.history.stats || []).filter(r => r && r.turn != null);
        if (!stats.length) {
            empty.style.display = 'block';
            canvas.style.display = 'none';
            legendBox.innerHTML = '';
            return;
        }
        empty.style.display = 'none';
        canvas.style.display = 'block';

        const dpr = window.devicePixelRatio || 1;
        const host = canvas.parentElement;
        const cssWidth = Math.max(220, host.clientWidth - 16);
        const cssHeight = Math.max(160, host.clientHeight - 40);
        canvas.width = cssWidth * dpr;
        canvas.height = cssHeight * dpr;
        canvas.style.width = cssWidth + 'px';
        canvas.style.height = cssHeight + 'px';
        const ctx = canvas.getContext('2d');
        ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
        ctx.clearRect(0, 0, cssWidth, cssHeight);

        const padding = { l: 42, r: 10, t: 12, b: 22 };
        const plotW = cssWidth - padding.l - padding.r;
        const plotH = cssHeight - padding.t - padding.b;

        const turns = stats.map(r => Number(r.turn) || 0);
        const minTurn = Math.min(...turns);
        const maxTurn = Math.max(...turns, minTurn + 1);
        let maxVal = 100;
        for (const row of stats) {
            for (const s of STAT_SERIES) {
                const v = Number(row[s.key]) || 0;
                if (v > maxVal) maxVal = v;
            }
        }
        maxVal = Math.ceil(maxVal / 100) * 100;

        const x = t => padding.l + ((t - minTurn) / (maxTurn - minTurn)) * plotW;
        const y = v => padding.t + plotH - (v / maxVal) * plotH;

        const muted = getComputedStyle(document.body).getPropertyValue('--text-muted') || 'rgba(255,255,255,0.6)';
        ctx.strokeStyle = 'rgba(255,255,255,0.12)';
        ctx.fillStyle = muted;
        ctx.font = '10px Inter, system-ui, sans-serif';
        ctx.lineWidth = 1;
        const gridLines = 4;
        for (let i = 0; i <= gridLines; i++) {
            const v = (maxVal / gridLines) * i;
            const gy = y(v);
            ctx.beginPath();
            ctx.moveTo(padding.l, gy);
            ctx.lineTo(cssWidth - padding.r, gy);
            ctx.stroke();
            ctx.fillText(String(Math.round(v)), 4, gy + 3);
        }
        const turnTicks = Math.min(8, maxTurn - minTurn);
        for (let i = 0; i <= turnTicks; i++) {
            const t = Math.round(minTurn + ((maxTurn - minTurn) / turnTicks) * i);
            ctx.fillText('T' + t, x(t) - 8, cssHeight - 8);
        }

        for (const s of STAT_SERIES) {
            ctx.strokeStyle = s.color;
            ctx.lineWidth = 1.6;
            ctx.beginPath();
            let started = false;
            for (const row of stats) {
                const v = Number(row[s.key]) || 0;
                const px = x(Number(row.turn) || 0);
                const py = y(v);
                if (!started) { ctx.moveTo(px, py); started = true; }
                else ctx.lineTo(px, py);
            }
            ctx.stroke();
        }

        legendBox.innerHTML = STAT_SERIES.map(s => {
            const last = stats[stats.length - 1];
            const v = Number(last && last[s.key]) || 0;
            return `<span class="monitor-legend-item"><span class="monitor-legend-swatch" style="background:${s.color}"></span>${s.label} ${v}</span>`;
        }).join('');
    }

    /* ---------- wire-up ---------- */

    root.querySelector('#monitor-toggle').addEventListener('click', () => {
        if (state.open) state.userClosed = true;
        setOpen(!state.open);
    });
    root.querySelector('#monitor-crash-toggle').addEventListener('click', () => setCrashVisible(!state.crashVisible));
    window.addEventListener('resize', () => {
        if (state.open && !state.crashVisible) drawChart();
    });

    let mounted = false;
    function mount() {
        if (mounted) return;
        mounted = true;
        const host = document.getElementById('monitor-host');
        if (host) {
            // inline mode: monitor lives at the top of the dashboard, open by default
            root.classList.add('inline');
            host.appendChild(root);
            setOpen(true);
        } else {
            document.body.appendChild(root);
        }
        refreshStatus();
        // keep the handle status fresh even while collapsed
        setInterval(() => {
            if (!state.open) refreshStatus();
        }, 4000);
    }
    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', mount);
    } else {
        mount();
    }
})();
