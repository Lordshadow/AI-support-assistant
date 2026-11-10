# Project Bug Fixes and Feature Checklist

Track each item through reproduction, implementation, regression verification, and end-to-end acceptance. A checked item means its acceptance checks passed, not merely that code changed.

## P0 — Customer identity, order, and refund correctness

- [x] **Remove customer ID aliasing in order access.** Reproduce cross-customer access using `1`, `3`, and `CUST-42`; remove shared-ID exceptions from single-order and recent-order lookup. Test database and storefront fallback paths to prove each identity receives only its own orders. Verified: `test_order_import_and_ownership` (strict repository + fallback cases).
- [x] **Fail closed on unknown source order status or item type.** Preserve explicit source status/category/digital flags. Unknown or absent refund-critical values must not create an automatically eligible refund. Tested delivered/non-delivered, digital, missing, malformed, and unknown values in targeted core/import tests.
- [x] **Preserve paise accurately.** Decimal values now flow through import, domain policy, persistence, refund validation, and a new NUMERIC migration. Verified ₹ paise import/domain/idempotency tests and offline migration SQL generation. PostgreSQL runtime persistence still requires integration verification.
- [x] **Do not invent delivery dates.** Preserve missing/malformed delivered timestamps; reject unknown/future delivery dates. Verified targeted missing/malformed/future and policy tests. Day-30/day-31 boundaries still require additional coverage.
- [ ] **Enforce configured refund and spend limits at runtime.** Read tenant configuration at the decision point (with safe defaults only when unset), and make updates effective without stale process-local values. Test across tenants, after setting changes, and after service restart.

## P1 — Dashboard correctness and trust

- [x] **Render only actual conversation trace fields.** Removed trace defaults and demo fallback values; missing values display as unavailable and failed loads offer retry. Complete trace and failed response tests pass; partial/empty trace assertions remain to add.
- [ ] **Align frontend routes with backend authorization.** Make allowed roles match endpoint policy. Test executive, manager, and admin navigation plus direct URL access; denied views must explain access requirements without repeated failing requests.
- [ ] **Remove fake metrics and status.** Replace fixed latency/online labels and fabricated deflection defaults with API-backed values and timestamps. Show unavailable/degraded states on empty or failed health/report responses. Test success, degraded, empty, and network failure.
- [ ] **Add consistent data-fetch error handling.** On every data-backed page, distinguish loading, empty, and error states, and provide retry. Verify request failures can never look like a successful empty queue.

## P1 — Dashboard features

- [ ] **Implement tenant-scoped global search.** Replace static sample records with authenticated live search. Add a tenant-scoped API endpoint if existing APIs cannot support cross-record lookup. Results must open the selected record. Test exact and partial IDs, empty results, authorization, tenant isolation, and failures.
- [ ] **Complete staff administration.** Add staff listing and account creation using existing staff endpoints. Include role selection, input validation, success/error feedback, and loading states. Test all supported roles and unauthorized access.
- [ ] **Add queue filters, sorting, and pagination.** Wire conversation and escalation list controls to their existing API parameters. Preserve filter/page state when opening and closing a record. Test first/last page, empty results, filter changes, and failures.
- [ ] **Make dashboard navigation usable on narrow screens.** Group infrequent admin/settings destinations, replace the crowded desktop-only strip with responsive navigation, and retain clear access to urgent queues. Verify keyboard operation, visible focus, contrast, reduced motion, and desktop/tablet/mobile layouts.

## Verification gates

- [ ] Add a regression test for each bug, demonstrating the failure before the fix and the safe result after the fix.
- [ ] For each feature, verify its API contract, role authorization, tenant isolation, loading/empty/error states, and user flow.
- [ ] Run targeted tests after each change; then run all backend tests, dashboard tests, dashboard type-check/build, and relevant integration checks. Record exact commands and results below.
- [ ] Perform browser checks for login/MFA, role-bound navigation, refund review, trace loading, search, staff administration, settings enforcement, and responsive navigation.
- [ ] Review the final diff for unrelated changes and production demo values. Do not mark a task done while any required check is failing or unavailable.

## Verification record

| Date | Check | Result | Evidence |
|---|---|---|---|
| 2026-11-10 | Order/refund policy regressions | Passed | `python -m unittest support-assistant.tests.test_core_policy support-assistant.tests.test_order_import_and_ownership -v` — 21 passed. |
| 2026-11-10 | Dashboard tests and production build | Passed | `npm test -- --run` — 24 passed; `npm run build` — TypeScript and Vite build passed. |
| 2026-11-10 | Alembic/offline schema checks | Passed | `python -m unittest support-assistant.tests.test_alembic_and_rls.TestAlembicAndRLS -v` — 3 passed; upgrade and downgrade SQL generation passed. |
| 2026-11-10 | Contrast tokens and Python compile | Passed | `node scripts/verify-contrast.js` — 13 token pairs passed; `python -m compileall -q support-assistant` passed. |
| 2026-11-10 | Full backend and browser workflows | Incomplete | DB-backed tests and `npx playwright test` did not finish in the local Windows harness; see Task-59 in `logs.md`. Not accepted as pass. |
