---

description: "Task list for: Harmonize UI Theme with OpenKineticsPredictor"
---

# Tasks: Harmonize UI Theme with OpenKineticsPredictor

**Input**: Design documents from `/specs/001-harmonize-ui-theme/`

**Prerequisites**: plan.md, spec.md, research.md, data-model.md, contracts/theme-tokens.md, quickstart.md (all present)

**Tests**: Not requested in the spec. This repo has no automated frontend test runner (confirmed in plan.md/research.md), so verification is manual via `quickstart.md`; each user-story phase ends with a task that runs the relevant quickstart steps.

**Organization**: Tasks are grouped by user story (from spec.md: US1 = P1 theme toggle, US2 = P2 typography, US3 = P3 legibility + flat background) so each can be delivered and verified independently.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependencies on incomplete tasks)
- **[Story]**: Maps the task to US1, US2, or US3
- All file paths are relative to the repository root

## Path Conventions

Single existing web app: `frontend/src/` (this feature is frontend-only; `backend/` is untouched — see plan.md Project Structure).

---

## Phase 1: Setup

**Purpose**: Load the shared fonts this whole feature depends on.

- [X] T001 Add the Google Fonts `@import` for Orbitron and Roboto to the top of `frontend/src/styles.css`, copying the exact line from `openKinetics_pred/frontend/src/styles/global.css` (`@import url('https://fonts.googleapis.com/css2?family=Orbitron&family=Roboto&display=swap');`) per contracts/theme-tokens.md "Harmonized chrome tokens (Fonts)".

**Checkpoint**: Fonts are loadable; no visual change yet.

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: The theme-switching mechanism and color/font token system that every user story depends on. No user story is independently testable until this phase is done.

**⚠️ CRITICAL**: Complete this phase before starting any user story.

- [X] T002 [P] Create `frontend/src/context/ThemeContext.jsx` porting `openKinetics_pred/frontend/src/context/ThemeContext.jsx` 1:1 per data-model.md: a `ThemeProvider` holding `theme` (`'dark' | 'light'`) that reads/writes the `localStorage` key `okd-theme` (defaulting to `'dark'` unless the stored value is exactly `'light'`), applies `document.documentElement.setAttribute('data-theme', theme)` via `useLayoutEffect`, and a `toggleTheme()` that flips the value and toggles a `theme-transitioning` class on `document.documentElement` for 300ms; export a `useTheme()` hook.
- [X] T003 Wrap `<App />` in `<ThemeProvider>` (imported from `./context/ThemeContext.jsx`) inside `frontend/src/main.jsx`, so the whole router tree is inside the provider. Depends on T002.
- [X] T004 In `frontend/src/styles.css`, replace the existing single `:root { ... }` token block (currently `--bg`, `--surface`, `--surface-2`, `--ink`, `--muted`, `--line`, `--accent`, `--accent-2`, `--amber`, `--danger`, `--shadow`, plus `color-scheme: light`) with the harmonized **dark**-theme values from contracts/theme-tokens.md: `--bg: #0f0c29`, `--surface-2: #302b63`, `--ink: #ffffff`, `--surface: rgba(24, 22, 50, 0.9)`, `--line: hsla(345, 7, 89, 1)`, `--shadow: 0 2px 5px hsla(345, 7, 89, 1)`, plus new vars `--input-bg: white`, `--dropdown-bg: #f0f0f0`, `--dropdown-text: #333333`, `--font-brand: 'Orbitron', sans-serif`, `--font-body: 'Roboto', sans-serif`, `--accent: #9b85f0`, `--accent-2: rgba(200, 188, 248, 0.72)`, `--muted: rgba(255, 255, 255, 0.6)` (secondary/muted text is shared chrome, not a domain-specific FR-010 color, so it needs a harmonized value now rather than being deferred); change `color-scheme: light` to `color-scheme: dark`; keep `--amber`, `--danger` declared with their current values unchanged (those two get dark-mode-specific treatment later, per FR-010, in US3). Depends on T001 (same file).
- [X] T005 In `frontend/src/styles.css`, add a `[data-theme="light"] { ... }` block (placed after the `:root` block, loaded so it wins) with the harmonized **light**-theme values from contracts/theme-tokens.md for the same token set introduced in T004: `--bg: #f5f2ff`, `--surface-2: #ede8ff`, `--ink: #1c1443`, `--surface: rgba(255, 255, 255, 0.92)`, `--line: rgba(110, 90, 200, 0.18)`, `--shadow: 0 2px 12px rgba(90, 70, 180, 0.1)`, `--input-bg: #ffffff`, `--dropdown-bg: #f5f2ff`, `--dropdown-text: #1c1443`, `--accent: #4835b4`, `--accent-2: #5040a8`, `--muted: rgba(28, 20, 67, 0.6)`, and `color-scheme: light`. Depends on T004 (same file, appended after it).

**Checkpoint**: Theme tokens exist for both themes, the provider applies `data-theme` and persists the choice, and fonts are loaded. Nothing in the UI visibly changes yet (no consumer of the new tokens/toggle exists) — that starts in US1.

---

## Phase 3: User Story 1 - Consistent dark/light theme toggle (Priority: P1) 🎯 MVP

**Goal**: A visible control that switches the whole site between the dark theme (default) and the light theme, with the choice persisted and an animated transition.

**Independent Test**: Open the app fresh (no stored preference) → confirm dark theme. Click the toggle → confirm it switches to light theme with a smooth transition, no reload. Reload the page → confirm the choice persisted.

### Implementation for User Story 1

- [X] T006 [P] [US1] In `frontend/src/App.jsx`, inside the `Layout()` component's `<header className="topbar">`, add a theme-toggle button (sun/moon icon pair via `lucide-react`, e.g. `Sun`/`Moon`) that calls `useTheme()` from `../context/ThemeContext.jsx` and renders `toggleTheme` on click, with an `aria-label`/`title` that reflects the action ("Switch to light mode" / "Switch to dark mode"), mirroring the predictor's `Header.jsx` `ThemeToggle` component structure (track + thumb spans). Depends on T002/T003 (Foundational).
- [X] T007 [P] [US1] In `frontend/src/styles.css`, add `.theme-toggle-btn`, `.theme-toggle-track`, `.theme-toggle-thumb` rules (circular track, border/background from `--line`/`--surface-2`, icon color from `--ink`/`--accent`) plus a `[data-theme="light"] .theme-toggle-track` variant, matching the predictor's `navbar.css` toggle styling and using the harmonized tokens from T004/T005 rather than new literals. Depends on T004/T005 (Foundational).
- [X] T008 [US1] In `frontend/src/styles.css`, add a `.theme-transitioning *, .theme-transitioning *::before, .theme-transitioning *::after { transition: background-color 0.25s ease, background 0.25s ease, border-color 0.25s ease, color 0.25s ease, box-shadow 0.25s ease !important; }` rule, copied from the predictor's `global.css`, so toggling (via T002's `theme-transitioning` class) animates smoothly (FR-007). Depends on T007 (same file).
- [X] T009 [US1] Manually run quickstart.md steps 1-3 ("Default theme", "Toggle behavior", "Persistence") against `npm run dev` in `frontend/`; confirm all three pass before moving on. Depends on T006-T008.

**Checkpoint**: User Story 1 is fully functional and independently testable — the site defaults to dark, toggles to light, and remembers the choice.

---

## Phase 4: User Story 2 - Matching brand typography (Priority: P2)

**Goal**: The "OpenKinetics Data" logo text uses the same distinctive font as the predictor's logo, and the rest of the interface uses the same body font.

**Independent Test**: Compare the rendered logo text and body text against OpenKineticsPredictor side by side; fonts should match.

### Implementation for User Story 2

- [X] T010 [US2] In `frontend/src/styles.css`, add `font-family: var(--font-brand);` to the `.brand` rule (the "OpenKinetics Data" logo/link in the topbar).
- [X] T011 [US2] In `frontend/src/styles.css`, change the `body` rule's `font-family` from the current `Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif` stack to `var(--font-body)`; also update `.residue-gap`'s hardcoded `font-family: Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;` declaration to `var(--font-body)` so it doesn't diverge from the rest of the page. Depends on T010 (same file).
- [X] T012 [US2] Manually run quickstart.md step 4 ("Typography") comparing against a running `openKinetics_pred/frontend` instance; confirm the brand font and body font match. Depends on T010-T011.

**Checkpoint**: User Stories 1 and 2 both work independently; the app now looks and switches themes like the predictor.

---

## Phase 5: User Story 3 - Legible data views in both themes, without a dynamic background (Priority: P3)

**Goal**: Every existing page (search/browse, detail, downloads, API docs, citation) stays fully legible in both themes, domain-specific status/chart colors keep their meaning, and the page background is a single flat harmonized color with no gradient or animation.

**Independent Test**: Toggle through every route in both themes; confirm all text/tables/charts/status pills stay legible, and confirm the background is one flat color with no motion.

### Implementation for User Story 3

- [X] T013 [US3] In `frontend/src/styles.css`, re-theme the topbar/nav/banner using the tokens from Phase 2 (add `[data-theme="dark"]`/rely on the new `:root` dark defaults as needed): `.topbar`, `.brand`, `.navlinks a` (+ `.active`/`:hover`), `.catlog-banner` (currently hardcoded `background: #fff8e8; color: #422f0b;`), `.banner-actions`, `.icon-button` (+ `.primary`/`.subtle`).
- [X] T014 [US3] In `frontend/src/styles.css`, re-theme the stats band: `.stats-band`, `.release-chip`, `.stat-item`. Depends on T013 (same file).
- [X] T015 [US3] In `frontend/src/styles.css`, re-theme search/filters: `.search-layout`, `.filters-panel`, `.filter-heading`, and the `.filters-panel input`/`select` rule (currently hardcoded `background: #fff`). Depends on T014 (same file).
- [X] T016 [US3] In `frontend/src/styles.css`, re-theme the results table: `.results-panel`, `.table-toolbar`, `.data-table` (`th`, `td`, hover, `.is-expanded`/`.expanded-row` states), `.measurement-row` (+ `:focus`), `.enzyme-cell`, `.link-button`. Depends on T015 (same file).
- [X] T017 [US3] In `frontend/src/styles.css`, re-theme status/pagination/alert elements for dark-mode contrast while **keeping their current semantic hues** (FR-010): `.status-pill`/`.pending-pill`, `.status-corrected`/`.status-verified` (green), `.status-manual_review_required` (amber), `.status-unverified` (gray), `.pagination-row` (+ button `:disabled`), `.table-state`, `.alert-box` (currently hardcoded `background: #fff0f0`). Depends on T016 (same file).
- [X] T018 [US3] In `frontend/src/styles.css`, re-theme the detail page: `.detail-page`, `.back-link`, `.detail-grid`, `.inline-detail-grid`, `.panel`, `.compact-table`, `.key-values`. Depends on T017 (same file).
- [X] T019 [US3] In `frontend/src/styles.css`, re-theme sequence/manifest/code blocks and the citation panel: `.sequence-block`, `.manifest-block`, `.code-block`, `.citation-subsection`, `.citation-box`/`.citation-box-header`, `.citation-actions`. Verify `.citation-code` (already a dark terminal-style block, `background: #101817; color: #e8f4ef;`) still reads correctly with a dark page around it and doesn't visually clash (edge case from spec.md). Depends on T018 (same file).
- [X] T020 [US3] In `frontend/src/styles.css`, re-theme the API docs page: `.api-overview-grid`, `.api-doc-section`, `.api-endpoint-list`/`.api-endpoint`/`.api-endpoint-heading`, `.method-pill`, `.api-param-table`, `.api-example-tabs`/`.api-tab-list`/its `button`/`.active`, `.api-code`. Depends on T019 (same file).
- [X] T021 [US3] In `frontend/src/styles.css`, re-theme the enzyme/binding-site detail panel: `.enzyme-panel`/`.enzyme-panel-header`, `.compact-state`, `.compact-table-wrap`, `.compact-measurement-table`, `.compact-row`, `.binding-site-summary` (+ `.muted`). Depends on T020 (same file).
- [X] T022 [US3] In `frontend/src/styles.css`, re-theme domain-color chart/annotation elements for dark-mode contrast while **keeping their current semantic hues** (FR-010): `.truncation-note`/`.artifact-note` (amber family), `.score-legend`/`.score-ramp`/`.score-stats`, `.sequence-heatmap`, `.residue-token`, `.residue-gap`, `.smiles-line`, `.evidence-note`. Depends on T021 (same file).
- [X] T023 [US3] In `frontend/src/styles.css`, re-theme downloads & stats charts: `.download-section`, `.download-stats`/`.download-stats-header`/`.download-stat-grid`/`.download-stat`, `.included-stats-grid`, `.sequence-row-grid`, `.chart-heading`, `.kinetic-venn`/`.venn-region`/`.venn-kcatOnly`/`.venn-kmOnly`/`.venn-both` (**keep these three hues per FR-010**), `.venn-label`, `.venn-detail`, `.stats-bar-chart`/`.stats-bar-row`/`.stats-bar-label`/`.stats-bar-track`, `.stats-kv-grid`, `.rejected-rows-panel`/`.rejected-rows-heading`/`.rejected-rows-grid`, `.stats-table`. Depends on T022 (same file).
- [X] T024 [US3] In `frontend/src/styles.css`, re-theme download rows/artifacts, the command panel, and format tables: `.download-list`, `.download-row`/`.artifact-row`/`.artifact-list`, `.command-panel-shell`/`.command-panel`/`.command-block`/`.command-block-header`/`.command-panel-note`, `.download-details`/`.download-details-body`, `.format-table`, `.field-list`. Depends on T023 (same file).
- [X] T025 [US3] In `frontend/src/styles.css`, set `body { background: var(--bg); }` as the page background — a single flat color per theme, confirming no `background-image`/gradient is present anywhere on `body` (FR-009) — and re-theme `.footer` using the harmonized surface/border tokens. Depends on T024 (same file).
- [X] T026 [US3] Manually run quickstart.md steps 5-9 ("Background", "Page-by-page legibility sweep", "Domain-color semantics preserved", "Mobile width", "Storage-blocked fallback"). Depends on T013-T025.

**Checkpoint**: All three user stories are independently functional; the app is fully re-themed and legible in both modes with no animated background.

---

## Phase 6: Polish & Cross-Cutting Concerns

**Purpose**: Final sign-off across the whole feature.

- [X] T027 [P] Run the complete quickstart.md checklist (all 9 steps) end-to-end, including the side-by-side comparison against a running `openKinetics_pred/frontend` instance (SC-004), as final sign-off.
- [X] T028 [P] Grep `frontend/src/styles.css` for any remaining hardcoded light-only literal colors (hex/`rgb`/`rgba` values outside the token declarations and the intentionally-domain-colored sections named in T017/T022/T023) that Phase 5 may have missed, and route them through the theme tokens from contracts/theme-tokens.md.

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)**: No dependencies — start immediately.
- **Foundational (Phase 2)**: Depends on Setup (T001, same file as T004/T005) — BLOCKS all user stories.
- **User Stories (Phase 3-5)**: All depend on Foundational completion.
  - US1, US2, and US3 are each independently testable once Foundational is done.
  - US3 additionally makes the most sense done last since it re-themes nearly every remaining selector in `styles.css` and benefits from the toggle (US1) already existing to visually check both themes while working — but there is no hard technical dependency forcing that order.
- **Polish (Phase 6)**: Depends on US1 + US2 + US3 all being complete.

### User Story Dependencies

- **User Story 1 (P1)**: Depends only on Foundational.
- **User Story 2 (P2)**: Depends only on Foundational. Independent of US1 (fonts apply regardless of whether the toggle button exists yet).
- **User Story 3 (P3)**: Depends only on Foundational. Independent of US1/US2, though verifying it is easier once US1's toggle exists.

### Within Each Phase

- Nearly every task in this feature edits `frontend/src/styles.css`, which is the single shared stylesheet — tasks touching it are listed in the exact sequential order they must be applied (each depends on the previous one landing first) and are **not** marked `[P]`.
- Tasks touching a different file (`ThemeContext.jsx`, `main.jsx`, `App.jsx`) are marked `[P]` where they have no unmet dependency on a sibling task in the same phase.

### Parallel Opportunities

- T002 (`ThemeContext.jsx`) can be done in parallel with nothing else in Phase 2 (it's the only other-file task; T001/T004/T005 are a sequential `styles.css` chain).
- T006 (`App.jsx`) and T007 (`styles.css`) in Phase 3 touch different files and have no dependency on each other (both only need Phase 2 done) — can be done in parallel.
- T027 and T028 in Phase 6 are independent activities and can run in parallel.

---

## Parallel Example: Phase 3 (User Story 1)

```bash
# T006 and T007 touch different files and only depend on Phase 2 — run together:
Task: "Add theme-toggle button to frontend/src/App.jsx topbar, wired to useTheme()"
Task: "Add .theme-toggle-btn/.theme-toggle-track/.theme-toggle-thumb styles to frontend/src/styles.css"
```

---

## Implementation Strategy

### MVP First (User Story 1 Only)

1. Complete Phase 1 (Setup) + Phase 2 (Foundational) — required for anything to work.
2. Complete Phase 3 (US1): the toggle itself.
3. **STOP and VALIDATE**: run quickstart.md steps 1-3 (T009).
4. This alone already delivers the most visible piece of the request — a working dark-default/light-toggle site.

### Incremental Delivery

1. Setup + Foundational → theme infrastructure ready, nothing visibly different yet.
2. Add US1 → toggle works end-to-end → validate (T009) → this is the MVP.
3. Add US2 → logo/body fonts match the predictor → validate (T012).
4. Add US3 → every page re-themed, semantic colors preserved, flat background → validate (T026).
5. Polish → full quickstart + stray-literal-color audit (T027-T028).

### Team Strategy

Given nearly all of US3 is one shared file (`styles.css`) edited section-by-section, US3 is best done by one person/session working through T013→T025 in order rather than split across people, to avoid merge conflicts. US1 (`App.jsx` + `styles.css` toggle bits) and US2 (`styles.css` font lines) are small enough that a second contributor could take US2 while US1 is in progress, once Foundational is merged.
