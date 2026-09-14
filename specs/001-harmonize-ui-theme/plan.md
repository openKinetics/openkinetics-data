# Implementation Plan: Harmonize UI Theme with OpenKineticsPredictor

**Branch**: `001-harmonize-ui-theme` | **Date**: 2026-09-11 | **Spec**: [spec.md](./spec.md)

**Input**: Feature specification from `/specs/001-harmonize-ui-theme/spec.md`

**Note**: This template is filled in by the `/speckit-plan` command; its definition describes the execution workflow.

## Summary

Port OpenKineticsPredictor's dark/light theme system (CSS custom-property color tokens, Orbitron/Roboto font pairing, React Context + `localStorage` toggle defaulting to dark) into the OpenKinetics Data frontend, replacing its current single light-only palette. The theme toggle and shared chrome (backgrounds, surfaces, borders, accent, text, logo font) reuse the predictor's exact token values; domain-specific semantic colors (status pills, Venn diagram, score-legend gradient) keep their current hue families, only adjusted for dark-surface legibility. The predictor's animated canvas background is explicitly excluded — OpenKinetics Data gets a single flat color per theme instead.

## Technical Context

**Language/Version**: JavaScript (ES2020+), React 18.3, JSX (no TypeScript in this frontend)

**Primary Dependencies**: Vite 6 (build/dev server), react-router-dom 6, react-bootstrap 2 / bootstrap 5, lucide-react (icons). No new npm dependency is required — the theme is CSS custom properties + a small React Context, mirroring `openKinetics_pred/frontend/src/context/ThemeContext.jsx` exactly. Fonts (Orbitron, Roboto) load the same way the predictor loads them: a Google Fonts `@import` in the global stylesheet.

**Storage**: N/A for the feature itself — theme preference is persisted client-side only, in the browser's `localStorage` (mirrors predictor's `wkp-theme` key pattern with a data-repo-specific key). No backend/API changes.

**Testing**: No automated frontend test runner exists in this repo today (`frontend/package.json` has no devDependencies/test script), and the predictor's equivalent theme system also ships without automated tests. This feature follows the same convention: verification is manual, via the `quickstart.md` checklist below, run in a real browser against both themes and against the predictor for side-by-side comparison.

**Target Platform**: Browser-based SPA (desktop + mobile widths), built with `vite build` and served as static files by nginx (see `frontend/Dockerfile` / `frontend/nginx.conf`); no SSR, so no server-side theme injection is needed.

**Project Type**: Web application (existing `backend/` + `frontend/` split). This feature is frontend-only; the Django backend (`backend/data_api`) is untouched.

**Performance Goals**: Theme toggle re-renders the full page in under 0.5s (SC-002); removing the possibility of an animated/canvas background means no added per-frame rendering cost (SC-006).

**Constraints**: Reuse the predictor's existing token values/fonts rather than inventing new ones (FR-001, FR-005, FR-006); no gradient or animation in the new background (FR-009); existing domain-specific semantic colors (status pills, Venn diagram, score gradient) must keep their hue families (FR-010); no new pages, routes, or backend endpoints.

**Scale/Scope**: One SPA, 7 routes (`/downloads`, `/search`, `/records/:recordKey`, `/releases`, `/citation`, `/api-docs`, plus the `/` redirect), a single global stylesheet (`frontend/src/styles.css`) plus the inline topbar/nav markup in `frontend/src/App.jsx`. All existing markup stays; only tokens, the new toggle control, and color values change.

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

`.specify/memory/constitution.md` in this repo is still the unfilled bootstrap template (all sections contain placeholder text like `[PRINCIPLE_1_NAME]` — no principles have actually been ratified). There are no project-specific gates to evaluate this plan against. **Result: PASS (no constitution constraints defined).**

**Post-Phase 1 re-check**: Design artifacts (`research.md`, `data-model.md`, `contracts/theme-tokens.md`, `quickstart.md`) introduce no new dependencies, services, or architectural layers beyond what Technical Context already declared — still a single frontend-only change. **Result: PASS (unchanged).**

## Project Structure

### Documentation (this feature)

```text
specs/001-harmonize-ui-theme/
├── plan.md              # This file (/speckit-plan command output)
├── research.md          # Phase 0 output (/speckit-plan command)
├── data-model.md        # Phase 1 output (/speckit-plan command)
├── quickstart.md        # Phase 1 output (/speckit-plan command)
├── contracts/           # Phase 1 output (/speckit-plan command)
│   └── theme-tokens.md
└── tasks.md             # Phase 2 output (/speckit-tasks command - NOT created by /speckit-plan)
```

### Source Code (repository root)

```text
backend/                       # Django API — untouched by this feature
└── ...

frontend/
├── index.html                # unchanged (font loads via CSS @import, matching predictor)
├── src/
│   ├── main.jsx               # wraps <App /> in the new ThemeProvider
│   ├── App.jsx                # topbar/nav markup gains the theme-toggle control
│   ├── context/
│   │   └── ThemeContext.jsx   # NEW — ported from openKinetics_pred/frontend/src/context/ThemeContext.jsx
│   └── styles.css             # tokens reworked to dark/light pairs + Orbitron/Roboto import;
│                               # existing component classes (topbar, data-table, status pills,
│                               # venn/score chart classes, download panels, etc.) gain
│                               # theme-aware values in place
└── ... (Dockerfile, nginx.conf, vite.config.js — unchanged)
```

**Structure Decision**: Existing web-application layout (`backend/` + `frontend/`) is kept as-is. This feature only adds one new file (`frontend/src/context/ThemeContext.jsx`, a direct port of the predictor's) and edits two existing ones (`frontend/src/App.jsx` for the toggle control, `frontend/src/styles.css` for theme tokens and per-component dark/light values). No new directories, routes, or backend changes.

## Complexity Tracking

> **Fill ONLY if Constitution Check has violations that must be justified**

Not applicable — the Constitution Check above found no ratified project principles to violate, so no complexity needs justifying.
