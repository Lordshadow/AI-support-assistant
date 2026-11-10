---
name: react-nextjs-engineering
description: Build and optimize production React and Next.js interfaces, focusing on rendering boundaries, data fetching, bundle size, accessibility, and JavaScript performance.
license: MIT
---

# React, Next.js, and JavaScript engineering

First inspect the framework version, router (App Router or Pages Router), rendering model, and existing component/state conventions. Follow the installed version's official docs; do not apply APIs from a newer React or Next.js release without confirming support.

## Performance priorities

1. Remove avoidable request waterfalls. Run independent I/O concurrently and defer work until the relevant branch or component needs it.
2. Keep client bundles small. Avoid unnecessary client components, broad barrel imports, eager heavy dependencies, and duplicate packages; dynamically load large noncritical features when it improves the actual route.
3. Choose server/client boundaries deliberately. Keep secrets and privileged data access server-side, pass minimal serializable props, and authenticate/authorize every server action and route handler.
4. Fetch data at the layer that owns it. Define cache and revalidation behavior explicitly; avoid stale cross-user or cross-tenant data and duplicate fetches.
5. Prevent expensive rerenders and layout work based on observed hot paths. Use stable state ownership and derived state; do not add memoization indiscriminately.
6. Keep URL state shareable when it represents navigation, filters, pagination, or selected records.

## JavaScript and UI behavior

- Preserve immutability where state updates depend on identity; use `Map`/`Set` for repeated membership lookups when appropriate.
- Avoid read/write layout thrashing and unbounded rendering of long lists. Profile before micro-optimizing.
- Use semantic HTML, keyboard-accessible interaction, visible focus, labeled form controls, clear loading/error/empty states, and reduced-motion support.
- Prevent hydration mismatches by aligning server and client output. Use client-only rendering only for genuinely browser-dependent behavior.
- Treat UI review as a check against the product's real user tasks and design system, not a mandate to impose a visual theme.

## Review workflow

- Identify route and component entry points, data dependencies, client/server boundaries, and current performance/accessibility conventions.
- Address critical latency and bundle issues before micro-optimizations; preserve behavior and avoid unrelated redesigns.
- Verify with the repository's existing lint, type-check, build, accessibility, or performance tooling only when requested or part of the task.

## Primary references

- [Vercel React Best Practices](https://github.com/vercel-labs/agent-skills/tree/main/skills/react-best-practices): impact-ordered React and Next.js performance guidance. Rules and counts change; check the upstream version when needed.
- [Next.js documentation](https://nextjs.org/docs): version-specific routing, rendering, caching, and data-fetching behavior.
- [React documentation](https://react.dev/learn): current component, state, and rendering guidance.
- [Vercel Web Interface Guidelines](https://github.com/vercel-labs/agent-skills/tree/main/skills/web-design-guidelines): UI review coverage for accessibility, forms, navigation, performance, and interaction.
