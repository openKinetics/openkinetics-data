# Phase 1 Data Model: Harmonize UI Theme with OpenKineticsPredictor

This feature has a single conceptual entity (matching the spec's Key Entities section). There is no backend/database change — everything below lives in the browser.

## Theme Preference

| Field | Type | Description |
|---|---|---|
| `theme` | enum: `"dark"` \| `"light"` | The visitor's active appearance mode. |

**Storage**: Browser `localStorage`, one string value under a dedicated key (e.g., `okd-theme`, namespaced separately from the predictor's own `wkp-theme` key since these are two independent sites/origins). No server-side or account-level storage.

**Default**: `"dark"` when the key is absent or holds any value other than `"light"` — mirrors the predictor's `ThemeContext.jsx` logic (`localStorage.getItem(key) === 'light' ? 'light' : 'dark'`) exactly, per FR-002.

**Lifecycle**:
1. On app load, `ThemeProvider` reads the stored value (or defaults to `dark`) and applies it as the `data-theme` attribute on `<html>`.
2. On toggle, the in-memory value flips, is written back to `localStorage`, and the `data-theme` attribute updates — triggering the CSS custom properties scoped under `[data-theme="light"]` (or the bare `:root` dark values) to take effect immediately (FR-003).
3. A `theme-transitioning` class is added to `<html>` for ~300ms around the flip so color/background/border-color/box-shadow transitions animate smoothly (FR-007), then removed.

**Relationships**: None — this is a standalone UI preference, not linked to any data-domain entity (measurements, enzymes, releases, etc. are unaffected in structure; only their rendered colors change per FR-008/FR-010).

**Validation rules**: N/A beyond the two-value enum; any unrecognized stored value is treated as "not light," i.e. falls back to dark (fail-safe default, addresses the "storage blocked/cleared" edge case in the spec).
