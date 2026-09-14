# Feature Specification: Harmonize UI Theme with OpenKineticsPredictor

**Feature Branch**: `001-harmonize-ui-theme`

**Created**: 2026-09-11

**Status**: Draft

**Input**: User description: "I want the interface for openKinetics_data to have exact harmonized color pallets and fonts as the interface for openKinetics_pred. Notics how the _preds have a button to change to the night mode and day mode and the default is night mode. Do the exact thing for the _data. Also see how on the top right the text representing the logo for openKineticsPredicter has a special font? use the same font for the data version and harmonise them. All exept the backgournd dynamic visualisation in the predictor. skip that for now. instead use a plain color with the same color pallet. No dynamic animation is needed for the background for now in the _data repo"

## Clarifications

### Session 2026-09-11

- Q: Should the existing semantic status colors in OpenKinetics Data (green for verified, amber for pending/warning, red for error, plus the teal/blue Venn-diagram and score-legend chart colors) keep their current color families (just adapted for dark-mode contrast), or should they be recolored to use the predictor's purple/neutral accent instead? → A: Keep semantic colors, adapt for dark mode — status pills, the Venn diagram, and score gradients retain their current green/amber/red/teal/blue meaning, adjusted only for legibility on the dark surface.
- Q: For the new plain (non-animated) page background, should it be a single flat color from the harmonized palette, or a frozen (motionless) version of the predictor's existing multi-stop gradient? → A: Single flat color — no gradient stops, just one solid harmonized color per theme.

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Consistent dark/light theme toggle (Priority: P1)

As a visitor who already uses OpenKineticsPredictor, I want OpenKinetics Data to open in the same dark theme by default and offer the same one-click toggle to light mode, so both sites feel like one connected product instead of two unrelated tools.

**Why this priority**: This is the core of the request — without the shared default theme and toggle, no other harmonization matters. It is also the most visible, most-used piece of the interface (present on every page).

**Independent Test**: Open OpenKinetics Data with no stored preference and confirm it renders in the dark theme; click the toggle and confirm it switches to a light theme using the harmonized palette; reload the page and confirm the chosen theme persists.

**Acceptance Scenarios**:

1. **Given** a visitor opens OpenKinetics Data for the first time (no saved preference), **When** the page loads, **Then** the site renders in the dark theme, matching OpenKinetics Predictor's default.
2. **Given** the site is in dark theme, **When** the visitor activates the theme toggle, **Then** the site switches to the light theme immediately, with a smooth visual transition and no page reload.
3. **Given** a visitor has previously switched to light theme, **When** they return in a new session, **Then** the site remembers and re-applies their chosen theme.

---

### User Story 2 - Matching brand typography (Priority: P2)

As a visitor comparing the two sites, I want the "OpenKinetics Data" logo text to use the same distinctive typeface as the "OpenKineticsPredictor" logo text, so the branding reads as one family of products.

**Why this priority**: Typography is the second most visible harmonization cue after color/theme, and it is cheap to apply once the shared font is loaded, but it depends on the theme/font system from User Story 1 being in place.

**Independent Test**: Compare the rendered logo text on both sites side by side and confirm the same font family, weight, and letter styling is used; confirm the rest of the interface (body text, navigation) uses the same shared body font as the predictor.

**Acceptance Scenarios**:

1. **Given** the OpenKinetics Data navigation bar, **When** it renders, **Then** the "OpenKinetics Data" brand text uses the same distinctive display font used for "OpenKineticsPredictor" in the predictor's navigation bar.
2. **Given** any page of OpenKinetics Data, **When** body text, navigation links, buttons, and tables render, **Then** they use the same standard body font family as the predictor's equivalent elements.

---

### User Story 3 - Legible data views in both themes, without a dynamic background (Priority: P3)

As a researcher browsing kinetic measurement data, I want tables, filters, charts, and status indicators to stay clear and readable whether I'm in dark or light theme, with a simple static background (no moving visualization), so I can focus on the data without distraction or added page weight.

**Why this priority**: This ensures the harmonization doesn't break the site's actual purpose (browsing/downloading data). It's lower priority than the theme system itself because it is a follow-on consequence of introducing dark mode, but it's required for the feature to be usable end-to-end.

**Independent Test**: Toggle through every existing page (search/browse, measurement detail, downloads, API docs, about) in both dark and light theme and confirm all text, table rows, charts, and status pills remain readable with adequate contrast, and confirm the page background is a single flat color with no gradient, animation, or canvas rendering.

**Acceptance Scenarios**:

1. **Given** any existing OpenKinetics Data page, **When** viewed in dark theme, **Then** all text, table borders, status pills, chart elements (e.g., the kinetic-parameter Venn diagram, score legend), and code/citation blocks remain legible with sufficient contrast against the dark surface.
2. **Given** any existing OpenKinetics Data page, **When** viewed in light theme, **Then** the same elements remain legible, matching the current (pre-feature) light appearance or better.
3. **Given** the page background, **When** the site is loaded in either theme, **Then** the background is a single flat color drawn from the harmonized palette, with no gradient, animation, or interactive visualization.

---

### Edge Cases

- What happens when a visitor's browser blocks or clears local storage? → Theme preference cannot persist; the site MUST still load correctly and default to dark theme on each visit rather than erroring.
- What happens to data-specific colors that were only ever designed for a light background (e.g., status pill greens/ambers, Venn diagram fills, score-ramp gradient) once dark theme is introduced? → They MUST be adapted so they remain legible on the dark surface, not left unchanged and hard to read.
- What happens on very narrow (mobile) viewports where the predictor collapses its nav into a hamburger menu? → The theme toggle MUST remain reachable and usable at all viewport widths, consistent with how the predictor exposes it outside the collapsed menu on mobile.
- What happens to code/citation blocks that are already styled as dark terminal-style panels in the current light-only interface? → They MUST continue to read correctly once the surrounding page can also be dark, avoiding a dark-on-dark or duplicated-style clash.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: The interface MUST support a dark theme and a light theme, using the same color tokens (primary/secondary background colors, accent color, text color, card/surface color, border color) as OpenKineticsPredictor's respective themes.
- **FR-002**: The interface MUST render in the dark theme by default for a visitor with no previously saved preference, matching OpenKineticsPredictor's default.
- **FR-003**: Users MUST be able to switch between dark and light theme via a single, clearly labeled control, without a full page reload.
- **FR-004**: The system MUST remember a visitor's chosen theme and re-apply it on their next visit to the site.
- **FR-005**: The site logo/brand text MUST use the same distinctive display font used for the OpenKineticsPredictor logo/brand text.
- **FR-006**: All other interface text (body copy, navigation, buttons, form fields, tables) MUST use the same standard body font family used by OpenKineticsPredictor.
- **FR-007**: Switching themes MUST apply a smooth visual transition across the interface, consistent with the transition behavior in OpenKineticsPredictor, rather than an abrupt/jarring change.
- **FR-008**: All existing OpenKinetics Data pages and components (search/browse table, filters, measurement detail views, download panels, API docs, about/citation pages, charts, and status indicators) MUST remain fully readable and usable in both the dark and light theme.
- **FR-009**: The page background MUST be a single, flat (non-gradient) color drawn from the harmonized palette for each theme, with no animated or interactive visualization. The animated/dynamic background visualization used in OpenKineticsPredictor MUST NOT be implemented in OpenKinetics Data as part of this feature.
- **FR-010**: Data-specific semantic indicators (status pills for verified/pending/manual-review/error states, the kinetic-parameter Venn diagram, and the score-legend gradient) MUST retain their current color families (green/amber/red/teal/blue) rather than being recolored to the harmonized accent palette; these colors MUST be adjusted only as needed for legibility against the dark theme's surface.

### Key Entities

- **Theme Preference**: The visitor's chosen appearance mode (dark or light). Tracked per browser/device; determines which color tokens are applied; defaults to dark when no preference has been recorded yet.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: A first-time visitor sees the dark theme with no manual action, matching OpenKineticsPredictor's default theme.
- **SC-002**: A visitor can switch themes in a single interaction, with the new theme fully rendered in under 0.5 seconds.
- **SC-003**: Every existing page in OpenKinetics Data (100% of current routes) is confirmed readable — no illegible or low-contrast text/elements — in both dark and light theme.
- **SC-004**: Side-by-side comparison of OpenKinetics Data and OpenKineticsPredictor shows the same shared-chrome color palette (backgrounds, surfaces, borders, accent, text) in both dark and light theme, and the same logo/body font choices — with data-specific semantic colors (status pills, charts) intentionally excluded from this comparison per FR-010.
- **SC-005**: Returning visitors see their previously chosen theme re-applied automatically on 100% of subsequent visits (barring cleared browser storage).
- **SC-006**: The interface introduces no animated background rendering, so page responsiveness is unaffected by this change.

## Assumptions

- OpenKineticsPredictor's existing frontend styling (its color tokens, Google Fonts choices, and theme-toggle behavior) is the canonical source of truth to copy from; "exact harmonized" means reusing the same token values and fonts rather than approximating a similar look.
- The distinctive display font is used only for the logo/brand text, and the standard body font is used everywhere else — matching the same split already used in OpenKineticsPredictor.
- The animated background visualization in OpenKineticsPredictor is explicitly out of scope for this feature; OpenKinetics Data instead gets a single flat color background (one solid color per theme, no gradient) using the harmonized palette. Adding an equivalent dynamic visualization to OpenKinetics Data may be considered as a separate, future feature.
- Domain-specific data-visualization colors in OpenKinetics Data that aren't part of the shared design system (status pill semantics, Venn diagram fills, score-ramp gradient) keep their existing green/amber/red/teal/blue meaning/hues rather than being recolored to the harmonized accent palette (see FR-010); they are adapted only as needed so they stay legible against both new theme surfaces. Syntax/citation code-block colors follow the same principle.
- Theme preference is stored client-side (e.g., in the browser) per device, mirroring OpenKineticsPredictor's current approach; no account or server-side preference storage is introduced.
- This feature is a visual/theming pass only — no new pages, routes, or functional data features are introduced or removed.
