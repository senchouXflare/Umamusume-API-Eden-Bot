# Eden ← SweepyCL Convergence — Design Spec

**Date:** 2026-06-18
**Status:** Approved (Approach A)
**Author:** Charles + Claude (brainstorming)

## Goal

Bring SweepyCL v7.6.3's superior decision-making and operational systems into
the Eden bot, while keeping Eden's clean UI/UX and multi-account operating
model. Eden stays the product; SweepyCL is the donor codebase.

## Core philosophy: keep Eden's shell, converge Eden's engine

Split the project into two layers and treat them differently:

- **Shell (keep Eden):** the web UI in `public/` (`index.html`, `app.js`,
  `styles.css`) and the multi-account operating model. SweepyCL's UI is
  explicitly rejected as cluttered. We only *extend* Eden's UI to surface new
  features, reusing Eden's existing design language.
- **Engine (converge to SweepyCL):** `runner.py`, all of `career_bot/*`, and
  `uma_api/*`. Because SweepyCL is a strict superset of Eden here (with ~85
  tests), we adopt SweepyCL as the baseline and **re-graft Eden's verified
  deltas**: the 5-minute MANT fast path, multi-account hooks, and the "UI
  contract" (fields the Eden UI reads).

## Module comparison (measured 2026-06-18)

Shared `career_bot` modules — line counts SweepyCL vs Eden, and the verdict:

| Module | SweepyCL | Eden | Verdict |
|---|---|---|---|
| `delay.py` | 183 | 183 | Identical — keep as-is |
| `events.py` | 605 | 48 | Eden is a stub → adopt SweepyCL |
| `master_data.py` | 2334 | 599 | Adopt SweepyCL (data backbone) |
| `races.py` | 890 | 161 | Adopt SweepyCL (smart solver, trackblazer) |
| `skills.py` | 1358 | 522 | Adopt SweepyCL |
| `items.py` | 1755 | 1288 | Merge — keep Eden MANT fast path |
| `runner.py` | 3549 | 1253 | Careful merge — Eden multi-account/MANT deltas |
| `report.py` | 220 | 151 | Adopt SweepyCL + keep Eden UI fields |
| `presets.py` | 221 | 162 | Adopt SweepyCL + keep Eden fields |
| `uma_api/client.py` | 1068 | 1045 | Diff carefully — near-equal, compare endpoints |

SweepyCL-only modules to bring in: `ai_advisor`, `ai_dataset`, `ai_modeling`,
`ai_trainer`, `calibration`, `character_data`, `character_profiles`,
`config_store`, `diagnostics`, `discord_logger`, `dynamic_skill_profiles`,
`event_outcomes`, `local_llm`, `policy_guards`, `race_intelligence`,
`recommended_stats`, `running_style`, `style_adaptation`, `trackblazer`,
`trackblazer_guide`, `trackblazer_rules`, `training_scorer`, plus
`uma_api/career_recovery.py` and the root `manager.py`.

## Reconciliation method (per module)

Each module passes through a 4-step gate, executed by agents:

1. **Audit & diff** — read both versions, build a function-by-function compare
   table, classify each difference `ADOPT_SWEEPY` / `KEEP_EDEN` / `MERGE`.
2. **Reconcile** — write the merged module per the verdicts, preserving Eden's
   UI contract and MANT fast path.
3. **Shadow validate** — for decision logic (scorer, race, event), run the new
   path in parallel (shadow) and log a comparison for N turns before promoting
   it to authoritative.
4. **Verify** — a second agent reviews the diff and runs tests before merge.

Deliverable artifact: `docs/superpowers/specs/module-comparison-matrix.md`,
recording per-module/per-function which side is better and the final verdict.

## Phase roadmap and agent ownership

Subagent-driven: each phase has a Porter agent (does the merge in an isolated
git worktree) and a Verifier agent (review + tests). Order by dependency and
rising risk:

- **P0 — Baseline & safety net.** Snapshot Eden, get the existing test suite
  green, stand up the shadow harness and the comparison matrix doc.
- **P1 — Multi-account supervision.** Port `manager.py`, add `/api/health`,
  add `/api/accounts*`. Lowest risk, immediate value, designed for Eden.
- **P2 — Spine.** Reconcile `uma_api/client.py` + `career_recovery.py` and the
  `runner.py` skeleton; re-graft Eden's MANT/multi-account deltas.
- **P3 — `master_data.py` + data assets** (support cards, succession, skills).
- **P4 — Training intelligence.** `training_scorer.py`, upgraded mant
  `_score_command`, `recommended_stats`, `running_style`/`style_adaptation`
  (shadow first).
- **P5 — Race intelligence.** `races.py` superset, `race_intelligence.py`,
  smart solver (MILP), trackblazer modules.
- **P6 — Events & items.** `events.py` (48→605), `event_outcomes` KB, merge
  `items.py`.
- **P7 — AI self-learning layer.** `ai_dataset/ai_trainer/ai_advisor/
  ai_modeling`, `local_llm`, `calibration`, `policy_guards`, `diagnostics`,
  `config_store`. Adds `scipy` (offline only — no MANT-speed impact).
- **P8 — Eden UI integration.** Extend `public/` to surface new features
  (accounts manager panel, AI/Misc, race-solver settings, training hints) in
  Eden's design language. Incremental, after each engine phase.
- **P9 — Final verification.** Full test suite, live multi-account run, 5-min
  MANT timing check, performance profiling.

## UI/UX policy

Keep Eden's shell (`index.html`, `app.js`, `styles.css`) intact. Each new
feature adds components to the existing layout, reusing Eden classes/CSS — no
SweepyCL styles imported. Extend `tests/test_ui_contract.py` to lock new DOM
ids/fields so engine changes can't break the UI.

## Testing & risk

Every phase keeps existing tests green and adds behavior-locking tests
(following SweepyCL's ~85-test example). Highest risk is P2 (runner) and any
MANT fast-path vs heavy-logic conflict; mitigated by isolated worktrees,
shadow mode, and the MANT timing gate at P9.

## Scope note

This spec covers nine independent subsystems. Per the writing-plans scope
rule, each phase gets its own implementation plan. The first plan
(`2026-06-18-p0-p1-baseline-multiaccount.md`) covers P0 + P1; later phases are
planned when reached.
