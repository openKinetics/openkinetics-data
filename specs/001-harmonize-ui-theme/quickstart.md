# Quickstart: Validating the Harmonized UI Theme

Manual validation guide — this repo has no automated frontend test suite (see `research.md`), so use this checklist against a running instance of both apps.

## Prerequisites

- Node.js installed (matches `frontend/package.json` engines used elsewhere in this repo).
- This feature's changes applied to `openKinetics_data/frontend` (theme tokens in `styles.css`, `ThemeContext.jsx`, toggle control in `App.jsx`).
- Optionally, `openKinetics_pred/frontend` runnable too, for side-by-side comparison (SC-004).

## Run it

```bash
cd openKinetics_data/frontend
npm install   # only if dependencies changed; this feature adds none
npm run dev
```

Open the printed local URL (Vite default: `http://localhost:5173`).

For side-by-side comparison, in another terminal:

```bash
cd openKinetics_pred/frontend
npm install
npm run dev
```

## Validation steps

1. **Default theme (SC-001, FR-002)**
   - Open the app in a fresh/incognito browser profile (no `localStorage` for this origin).
   - Expect: the page renders in the dark theme immediately — no flash of the old light-only layout, no manual action required.

2. **Toggle behavior (FR-003, FR-007, SC-002)**
   - Click/tap the theme-toggle control.
   - Expect: the site switches to light theme in well under 0.5s, with a smooth color/background transition (not an instant jump, not a full page reload — check the URL bar/network tab shows no navigation).
   - Toggle back to dark; confirm it reverses cleanly.

3. **Persistence (FR-004, SC-005)**
   - With light theme active, reload the page (F5).
   - Expect: light theme is still active after reload.
   - Close and reopen the tab (same browser, same profile): still light.

4. **Typography (User Story 2, FR-005, FR-006)**
   - Compare the "OpenKinetics Data" logo text against OpenKineticsPredictor's "OpenKineticsPredictor" logo text (run both apps per above).
   - Expect: same distinctive display font (Orbitron), same weight/style treatment.
   - Compare body text, nav links, buttons, and table text between the two apps.
   - Expect: same body font (Roboto).

5. **Background (FR-009, SC-006)**
   - In both dark and light theme, inspect the page background.
   - Expect: a single flat color with no gradient banding, no motion, no canvas element in the DOM (check devtools Elements panel — there should be no `<canvas>` and no `background-image` gradient on `body`).

6. **Page-by-page legibility sweep (FR-008, SC-003)**
   - Visit every route in both themes: `/downloads`, `/search`, a `/records/:recordKey` detail page, `/releases`, `/citation`, `/api-docs`.
   - For each, confirm: body text, table rows/borders, filters, status pills, the kinetic-parameter Venn diagram, the score-legend gradient, download panels, and citation/code blocks are all clearly readable with no low-contrast or invisible text in either theme.

7. **Domain-color semantics preserved (FR-010)**
   - On a page with status pills (e.g., a records list with verified/pending/error rows), confirm green still means verified/corrected, amber still means pending/manual-review, red still means error — in both themes.
   - On the releases/stats page with the Venn diagram and score legend, confirm the same color families (not recolored to purple) in both themes.

8. **Mobile width (Edge case)**
   - Resize the viewport to a narrow (mobile) width.
   - Expect: the theme toggle remains visible and usable (not hidden inside a collapsed menu with no other way to reach it).

9. **Storage-blocked fallback (Edge case)**
   - Block/clear site data or use a private window that disables storage.
   - Expect: the app still loads without erroring, defaulting to dark theme.

## Sign-off

All 9 steps above pass in at least one modern desktop browser and one mobile-width viewport before considering this feature complete.
