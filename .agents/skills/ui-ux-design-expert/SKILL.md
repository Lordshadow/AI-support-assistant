---
name: ui-ux-design-expert
description: >-
  Expert guidance for modern enterprise dashboard UI/UX design, glassmorphism design systems,
  WCAG 2.1/2.2 AA accessibility standards, responsive ergonomics, and high-density data presentation.
  Use when designing, auditing, or implementing frontend components, layout shells, color systems, and token architectures.
---

# UI/UX Design Expert Skill

The teal glassmorphism system below records this project's preference; it is not a universal requirement. For unrelated products, follow the user's brief and existing design system. For UI audits, also consult the current [Vercel Web Interface Guidelines](https://github.com/vercel-labs/agent-skills/tree/main/skills/web-design-guidelines) for accessibility, forms, navigation, performance, and interaction. Resolve conflicts in favor of the user's requirements and applicable accessibility standards.

## Purpose & Scope
This skill provides comprehensive, production-grade principles, design system tokens, and accessibility standards for enterprise dashboards. It emphasizes operational clarity, low eye strain for full-day support staff, robust glassmorphic layering, and strict WCAG 2.1/2.2 AA compliance.

---

## 1. Glassmorphism Architecture & Surface Tiers
Glassmorphism in enterprise applications must balance aesthetic sophistication with strict readability. Never sacrifice operational speed or legibility for decorative effect.

### Three Surface Tiers
1. **`glass-chrome` (Top Navigation, User Chips, Floating Headers, Status Bars)**
   - **Role:** Structural navigation and floating chrome controls.
   - **Properties:** Moderate translucency (`rgba(11, 74, 71, 0.65)` on dark / `rgba(232, 242, 240, 0.70)` on light), backdrop-filter blur `16px - 20px`, 1px subtle frosted border `rgba(255, 255, 255, 0.18)` or `rgba(63, 210, 192, 0.25)`, soft elevation shadow.
2. **`glass-panel` (Cards, Summaries, Metric Widgets, Sidebars)**
   - **Role:** Intermediate containers grouping related metrics or controls.
   - **Properties:** Lower translucency / higher opacity (`rgba(6, 47, 46, 0.82)` on dark / `rgba(232, 242, 240, 0.90)` on light), backdrop-filter blur `12px - 16px`, 1px crisp border `rgba(63, 210, 192, 0.15)`, layered box shadow `0 8px 32px rgba(0, 0, 0, 0.25)`.
3. **`glass-data` (Data Tables, Transcripts, Traces, Form Inputs, Code/Diff Views)**
   - **Role:** High-density, prolonged-reading surfaces where eye strain and contrast matter most.
   - **Properties:** **Nearly opaque to solid** (`rgba(6, 47, 46, 0.96)` on dark / `rgba(245, 250, 249, 0.98)` on light), minimal to zero background pattern distraction, sharp inner/outer contrast border.
   - **Rule:** Never render tabular data, dense prose, or input forms over low-opacity glass.

### Backdrop & Nebula Gradients
- Generated purely via CSS gradients and SVG meshes (no heavy raster image dependencies).
- Deep teal base palette with soft aqua (`#3FD2C0`) and emerald (`#17A58F`) ambient light blobs.
- Stacking budget: Maximum 2-3 overlapping backdrop-filter layers in any viewport to prevent GPU frame drops.

---

## 2. Signature Visual & Component Language
- **Notched/Tabbed Panels:** Panels with generous corner radii (`rounded-2xl` or `rounded-3xl`) featuring distinct tab pills attached to panel edges as section markers.
- **Pill Top Nav & Chip Elements:** Floating pill-shaped navigation container with pill tab buttons, pill user profile chips (avatar, name, role badge).
- **Micro-Labels:** Wide letter-spaced (`tracking-widest` or `tracking-wider`), uppercase micro-captions (`text-[10px]` or `text-xs font-semibold`) for section headers.
- **Action Buttons:** Pill buttons for primary actions; circular icon buttons (`h-10 w-10 rounded-full`) for secondary actions (favorite, bookmark, more, add).
- **Card Detail Trigger:** Rounded cards with a square or rounded-square arrow button in the top/bottom corner for "open detail".
- **Arch Navigation Control:** Arch-shaped jump/scroll widget for jump-to-section or back-to-top navigation.
- **Bottom Status Bar:** Persistent pill status bar with centered circular home/action button (adapting to bottom tab navigation on mobile).

---

## 3. WCAG 2.1 / 2.2 AA Accessibility & Ergonomics
- **Contrast Ratios:**
  - Standard text: Minimum **4.5:1** contrast ratio against its effective background (evaluating worst-case light blob positions).
  - Large text & interactive borders: Minimum **3:1** contrast ratio.
  - Semantic status indicators: Pair color with clear icons and text labels (never color alone).
- **Reduced Motion & Reduced Transparency Fallbacks:**
  - `@media (prefers-reduced-motion: reduce)`: Disable CSS gradient animations, blob drift, and transitions.
  - `@media (prefers-reduced-transparency: reduce)` or `@supports not (backdrop-filter: blur(16px))`: Swap all glass surfaces to solid teal/mint opaque backgrounds.
- **Keyboard Navigation & Focus States:**
  - 100% full keyboard tab order.
  - Pronounced, high-contrast focus rings (`outline: 2px solid #3FD2C0; outline-offset: 2px;`) that clearly distinguish focused elements on glass.
  - Global keyboard shortcuts (e.g., `Cmd/Ctrl + K` search, `J`/`K` queue navigation).
- **Radix UI / Headless Primitives:**
  - Accessible dialogs, dropdowns, tooltips, tabs, and alerts with proper ARIA attributes (`aria-expanded`, `aria-live`, `aria-describedby`).

---

## 4. Design System Token Standards
```css
:root {
  /* Teal Theme Palette */
  --color-teal-base: #0B4A47;
  --color-teal-darker: #062F2E;
  --color-teal-lighter: #0F5C58;
  --color-mint-surface: #E8F2F0;
  --color-mint-bg: #C9D8D6;
  --color-aqua-accent: #3FD2C0;
  --color-emerald-deep: #17A58F;

  /* Typography Colors */
  --color-text-on-light: #0F3D3B;
  --color-text-on-dark: #EAF6F4;
  --color-text-muted: #8EB4B0;

  /* Semantic Alerts */
  --color-status-success: #2ED573;
  --color-status-warning: #FFA502;
  --color-status-danger: #FF4757;
  --color-status-info: #1E90FF;

  /* Glassmorphism Tiers */
  --glass-chrome: rgba(11, 74, 71, 0.70);
  --glass-panel: rgba(6, 47, 46, 0.85);
  --glass-data: rgba(6, 47, 46, 0.96);
  --glass-border: rgba(63, 210, 192, 0.20);
  --glass-border-light: rgba(255, 255, 255, 0.15);
  --glass-shadow: 0 12px 40px 0 rgba(0, 0, 0, 0.35);
  --glass-blur-sm: 10px;
  --glass-blur-md: 16px;
  --glass-blur-lg: 24px;
}
```

---

## 5. Screen Layout & UX Patterns
- **Loading Skeletons:** Animated shimmering placeholders matching card and table structures.
- **Empty States:** Clear graphic placeholder, informative explanation, and one primary action trigger.
- **Error States:** Actionable error message, retry button, and correlation/request ID display for support escalations.
- **Responsive Adaptations:**
  - Desktop: Multi-column split views (e.g., list + side-by-side detail drawer).
  - Tablet: Collapsible drawer or tabbed master-detail.
  - Mobile: Full-width stacked cards, fixed bottom pill navigation bar.
