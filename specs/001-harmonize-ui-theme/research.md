# Phase 0 Research: Harmonize UI Theme with OpenKineticsPredictor

All Technical Context fields were resolved directly from inspecting the two codebases (no NEEDS CLARIFICATION remained). This document records the decisions and why, for anyone implementing tasks later.

## Decision: Reuse the predictor's React Context + `localStorage` theme pattern verbatim

**Decision**: Port `openKinetics_pred/frontend/src/context/ThemeContext.jsx` into `openKinetics_data` almost unchanged — a `ThemeProvider` holding `theme` state (`'dark' | 'light'`), defaulting to `localStorage.getItem(<key>) === 'light' ? 'light' : 'dark'`, applying `document.documentElement.setAttribute('data-theme', theme)` via `useLayoutEffect`, and a `toggleTheme()` that also toggles a `theme-transitioning` class for 300ms to drive a CSS transition.

**Rationale**: This is the exact mechanism the spec asks to harmonize with (FR-002, FR-003, FR-004, FR-007). It has no dependencies beyond React itself, works in a plain client-rendered Vite SPA (this project's setup — no SSR, so no hydration mismatch risk), and keeps the two codebases' theming code structurally identical, which will make future cross-repo maintenance easier.

**Alternatives considered**:
- A dedicated theming library (e.g., a `next-themes`-style package): rejected — this project isn't Next.js, and pulling in a new dependency for something the predictor already solved in ~30 lines adds no value and breaks parity.
- `prefers-color-scheme` media query as the default instead of a hardcoded dark default: rejected — the predictor's default is unconditionally dark regardless of OS preference (confirmed by reading its `ThemeContext.jsx`), and the spec (FR-002, clarified) requires matching that default exactly.
- CSS-only toggle (checkbox hack, no JS state): rejected — would not match the predictor's persisted-preference + smooth-transition behavior (FR-004, FR-007), and the predictor's own implementation already uses React state, so mirroring it is simpler than reinventing a CSS-only approach.

## Decision: Reuse the predictor's exact CSS custom-property token values

**Decision**: Copy the dark-theme and light-theme custom property values from `openKinetics_pred/frontend/src/styles/global.css` (`:root` and `[data-theme="light"]` blocks) into `openKinetics_data/frontend/src/styles.css`, replacing the current single light-only `:root` palette. Existing `_data`-specific variable names (`--bg`, `--surface`, `--ink`, `--muted`, `--line`, `--accent-2`) are kept as the variable names already used throughout `styles.css`, but their *values* are re-pointed to the harmonized dark/light tokens (e.g., `--bg` becomes the flat dark/light background color, `--ink` becomes the harmonized text color, etc.) rather than renaming every CSS class to the predictor's variable names.

**Rationale**: FR-001 requires "the same color tokens," which is about the values (what a user sees), not the internal variable-naming scheme of a different repo's stylesheet. Keeping `_data`'s existing variable names but repointing their values is the smallest, least error-prone change across ~1,800 lines of existing component CSS, and avoids a large mechanical rename that provides no user-visible benefit.

**Alternatives considered**:
- Renaming all `_data` CSS variables to match `_pred`'s exact names (`--primary-color`, `--secondary-color`, etc.): rejected — larger diff, higher regression risk across many component classes, no functional or visual difference for users.

## Decision: Single flat background color, not a gradient (per clarification)

**Decision**: Add one new token (e.g., `--page-bg`) per theme holding a single solid color drawn from the harmonized palette, applied to `body`. No `background-image`/gradient, no canvas element, no `ProteinBackground`-equivalent component.

**Rationale**: Directly resolves the clarified answer ("Single flat color") and FR-009. Confirmed the predictor's animated background lives in `openKinetics_pred/frontend/src/components/ProteinBackground.jsx` — that file and its canvas/particle logic are not touched or ported.

**Alternatives considered**: A frozen (static) copy of the predictor's multi-stop gradient — explicitly rejected during clarification in favor of a single flat color.

## Decision: Keep domain-specific semantic colors, adapt only for dark-mode contrast (per clarification)

**Decision**: Status pill colors (`.status-corrected`/`.status-verified` green, `.status-manual_review_required` amber, danger red), the kinetic-parameter Venn diagram fills (`.venn-kcatOnly`, `.venn-kmOnly`, `.venn-both`), and the score-legend gradient (`.score-ramp`) keep their current hue families. New `[data-theme="dark"]` overrides will be added for each so they retain sufficient contrast against the new dark surface — the same pattern the predictor itself uses for its own dark/light-specific overrides in `light-mode.css` and the `[data-theme="dark"]` blocks in `global.css`.

**Rationale**: Directly resolves the clarified answer and FR-010. These colors carry data semantics (verified/pending/error, kcat-only/Km-only/both, low→high score) that the predictor has no equivalent for; recoloring them to the shared purple accent would erase that meaning.

**Alternatives considered**: Recolor everything to the harmonized accent palette — explicitly rejected during clarification.

## Decision: No automated test suite added for this feature

**Decision**: Verification is manual, via `quickstart.md`. No new test files, no new test runner/dependency.

**Rationale**: `frontend/package.json` has no test script or test dependency today, and neither does the predictor's frontend for its equivalent theme system. Introducing a testing framework as a side effect of a theming feature would be a scope increase beyond what either codebase currently does, and beyond what the spec asks for (the spec's acceptance criteria are visual/behavioral, verified by looking at the rendered app).

**Alternatives considered**: Adding Vitest + React Testing Library snapshot/contrast tests — rejected for this feature; could be proposed separately as its own initiative if the project later decides to adopt frontend testing generally.

## Decision: Load Orbitron/Roboto the same way the predictor does

**Decision**: Add the identical Google Fonts `@import url('https://fonts.googleapis.com/css2?family=Orbitron&family=Roboto&display=swap');` line to `frontend/src/styles.css` (or a location that loads before first paint), and apply `font-family: 'Orbitron', sans-serif` to the brand/logo element, `font-family: 'Roboto', sans-serif` to `body`.

**Rationale**: FR-005/FR-006 require the same fonts; reusing the predictor's exact `@import` line guarantees the exact same font weights/subsets load, with zero new dependencies.

**Alternatives considered**: Self-hosting the font files — rejected, would diverge from the predictor's own loading strategy and add build complexity with no benefit.
