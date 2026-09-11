# Contract: Theme Tokens & Toggle

This is the interface every component in `openKinetics_data`'s frontend consumes: a fixed set of CSS custom properties, scoped by the `data-theme` attribute on `<html>`, plus the JS contract for reading/changing the active theme. Anything that renders UI must use these tokens rather than hardcoding new colors, so the "harmonized" guarantee (FR-001, FR-005, FR-006) holds across the whole app, not just the navbar.

## `data-theme` attribute contract

- `<html data-theme="dark">` or `<html data-theme="light">`, set by `ThemeProvider` (see `data-model.md`).
- No attribute / any other value never occurs after first paint — `ThemeProvider` always writes one of the two values, defaulting to `"dark"`.
- CSS selects dark values from bare `:root` (or `:root:not([data-theme="light"])` if a value must be explicit), and light overrides from `[data-theme="light"]` — this matches the predictor's existing selector pattern exactly.

## JS contract (`context/ThemeContext.jsx`)

```js
const { theme, toggleTheme } = useTheme();
// theme: 'dark' | 'light'
// toggleTheme(): flips theme, persists to localStorage, applies the transition class
```

Ported 1:1 from `openKinetics_pred/frontend/src/context/ThemeContext.jsx`, with the `localStorage` key renamed to something namespaced to this app (e.g. `okd-theme`) since the two frontends are separate origins and must not collide or be confused with each other's stored preference.

## Harmonized chrome tokens (copied directly from the predictor)

These map 1:1 to values already defined in `openKinetics_pred/frontend/src/styles/global.css`. `openKinetics_data` keeps its existing variable *names* (already used across ~1,800 lines of `styles.css`) and repoints their *values* to these:

| `_data` token (existing name) | Source in predictor | Dark value | Light value |
|---|---|---|---|
| `--bg` (page/body background — now a flat color, FR-009) | `--primary-color` | `#0f0c29` | `#f5f2ff` |
| `--surface-2` (secondary panel tone) | `--secondary-color` | `#302b63` | `#ede8ff` |
| `--ink` (primary text) | `--text-color` | `#ffffff` | `#1c1443` |
| `--muted` (secondary/muted text — used pervasively for labels, captions, table headers) | derived from `--text-color` at reduced opacity, matching the opacity range (~0.5–0.65) the predictor itself uses for muted text across its components (e.g. `.gpu-panel__intro`, `.gpu-status-intro`) | `rgba(255, 255, 255, 0.6)` | `rgba(28, 20, 67, 0.6)` |
| `--surface` (cards, topbar, panels, table surfaces) | `--card-background` | `rgba(24, 22, 50, 0.9)` | `rgba(255, 255, 255, 0.92)` |
| `--line` (borders) | `--border-color-1` | `hsla(345, 7, 89, 1)` | `rgba(110, 90, 200, 0.18)` |
| `--shadow` | `--box-shadow-1` | `0 2px 5px hsla(345, 7, 89, 1)` | `0 2px 12px rgba(90, 70, 180, 0.1)` |
| *(new)* `--input-bg` | `--input-background` | `white` | `#ffffff` |
| *(new)* `--dropdown-bg` / `--dropdown-text` | `--dropdown-bg` / `--dropdown-text` | `#f0f0f0` / `#333333` | `#f5f2ff` / `#1c1443` |

> Note: the predictor's own `hsla(345, 7, 89, 1)` omits the required `%` units on saturation/lightness — copied verbatim for fidelity. If a browser renders it oddly, it already does so identically in the predictor; do not "fix" it as part of this feature since that would make the two sites diverge again.

Fonts (also copied 1:1):

- `--font-brand: 'Orbitron', sans-serif` — used only for the logo/brand text (FR-005).
- `--font-body: 'Roboto', sans-serif` — used for `body` and everything else (FR-006).
- Same Google Fonts `@import` line as the predictor's `global.css`.

## Derived accent tokens (no single 1:1 predictor variable exists)

The predictor has one translucent `--accent-color` (a glow, not a solid UI color) and otherwise hardcodes solid purple hex values per-component rather than exposing one canonical "solid accent" variable. `_data` needs solid accent colors (links, primary actions, focus rings) to replace its current teal/blue (`--accent: #126b57`, `--accent-2: #205493`). Pick literal values already used repeatedly in the predictor's own CSS, so the result still reads as "the same palette," rather than inventing new hues:

| `_data` token | Suggested dark value | Suggested light value | Literal source in predictor |
|---|---|---|---|
| `--accent` (primary interactive color: links, primary buttons, focus rings) | `rgba(200, 188, 248, 0.92)`-ish solid, e.g. `#9b85f0` | `#4835b4` | `#4835b4` is used verbatim for `.mpill-pub-link`, `.contribute-link` in `light-mode.css`; the dark-mode purple family (`rgba(140-155, 118-135, 222-235, …)`) around `.btn-kave-toggle` informs the dark equivalent. |
| `--accent-2` (secondary interactive tone) | `rgba(200, 188, 248, 0.72)` | `#5040a8` | Both are literal values already in `light-mode.css`/`navbar.css` (`.btn-kave-toggle` dark color; `.step-number` light color). |

Whoever implements this should re-check these two against the predictor's rendered UI (not just the CSS text) before finalizing, since this pairing is a reasonable synthesis rather than a value the predictor stores under one named variable.

## Domain-specific semantic colors (explicitly NOT harmonized — FR-010)

These keep their current hue family. Only add `[data-theme="dark"]`-scoped adjustments for contrast; do not repoint them to the accent tokens above.

- `--amber` (`#8a5a00` light) — pending/manual-review status, truncation/artifact notes.
- `--danger` (`#9e2f2f` light) — error states, alert boxes.
- Status pill backgrounds: `.status-corrected`/`.status-verified` (green), `.status-manual_review_required` (amber), `.status-unverified` (gray).
- Venn diagram fills: `.venn-kcatOnly`, `.venn-kmOnly`, `.venn-both`.
- `.score-ramp` gradient (`#dbeafe → #fde68a → #f97316 → #b91c1c`).

## Background contract (FR-009)

`body { background: var(--bg); }` only — a single flat color, no `background-image`, no gradient, no canvas/SVG animation layer. `--bg` takes the values from the harmonized chrome table above.
