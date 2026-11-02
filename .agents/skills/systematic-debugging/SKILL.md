---
name: systematic-debugging
description: >-
  Enforces a disciplined, hypothesis-driven 4-phase root cause analysis process for diagnosing
  code defects, agent test failures, and intermittent errors. Use when investigating bugs,
  failing test suites, or unexpected system behavior.
---

# Systematic Debugging Skill

## Purpose & Scope
Eliminates blind trial-and-error by enforcing a rigorous 4-phase debugging methodology. Ensures fixes address true root causes rather than symptoms.

---

## The 4-Phase Root Cause Protocol

### Phase 1: Reproduce & Isolate
1. **Establish a Minimal Reproduction**: Identify the exact command line, input data, or test case that triggers the defect reliably.
2. **Isolate Variables**: Strip away unnecessary dependencies, mock non-deterministic external services, and observe standard error/output.
3. **Capture the Failure State**: Record exact error codes, stack traces, and environment conditions before making any code modifications.

### Phase 2: Formulate & Rank Hypotheses
1. Brainstorm at least 2–3 plausible hypotheses for the failure based on the stack trace and data flow.
2. Rank hypotheses by probability and ease of verification.
3. Explicitly state the prediction: "If hypothesis A is correct, we should observe value X at line Y."

### Phase 3: Gather Evidence & Inspect State
1. **Targeted Instrumentation**: Add minimal, non-destructive logging or inspect execution state at critical decision points.
2. **Verify Assumptions**: Check types, boundary values, null pointers, path separators, and environment variables.
3. **Eliminate Hypotheses**: Disprove hypotheses that contradict the collected evidence.

### Phase 4: Targeted Fix & Regression Verification
1. **Atomic Remediation**: Apply the smallest possible targeted change that eliminates the root cause.
2. **Avoid Anti-Patterns**:
   - Never suppress errors with empty `catch` / `except` blocks.
   - Never add arbitrary delays (`sleep`) to resolve race conditions.
   - Never modify unrelated code or style during a bugfix.
3. **Regression Test**: Run the full test suite to guarantee the fix did not introduce secondary regressions.

---

## Safety Guardrails
- Always perform read-only inspection first before altering files or dependencies.
- Keep backups or version-control track of modified files.
