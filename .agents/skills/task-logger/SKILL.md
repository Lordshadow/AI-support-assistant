---
name: task-logger
description: >-
  Standardized protocol for logging development progress, task execution rationale,
  files modified, test verification outcomes, and next steps into logs.md.
  Use before starting and immediately after completing any task.
---

# Task Logger Skill

## Purpose & Scope
This skill provides a rigorous, standardized logging protocol for tracking development tasks, technical rationale ("why"), architectural boundaries, file changes, and verification outcomes in `logs.md` at the project root. It ensures full auditability and transparency for both the developer and AI agent across turns.

---

## 1. Logging Principles
1. **Precision & Transparency**: Record exact file paths, configuration changes, test outcomes, and technical decisions.
2. **The "Why" Behind Changes**: Always explain the business, architectural, or security reasoning for every implementation step.
3. **Traceability**: Link requirements (e.g., R1–R5, Section 1.3, Section 15.1) directly to the files and components implemented.
4. **Verification Evidence**: Document exact test execution commands, outputs, pass/fail counts, and regression tests.
5. **Human Gate**: Clearly indicate task completion status and state the exact next planned task pending user permission.

---

## 2. Standard `logs.md` Entry Schema

Each task entry appended to `logs.md` must follow this structure:

```markdown
## [Task-ID] - Task Title
**Timestamp:** YYYY-MM-DD HH:MM:SS (Timezone)  
**Status:** [COMPLETED / IN-PROGRESS / BLOCKED / VERIFIED]  
**Objective & Rationale ("Why"):**  
- Brief explanation of why this task is being done and how it connects to project specifications.

**Architectural Boundaries & Modularity:**
- Explanation of decoupled ports, adapters, or modules created/modified.

**Files Touched:**
- `path/to/created_or_modified_file` (Action: Created/Modified/Deleted - Summary of changes)

**Verification & Quality Assurance:**
- Commands executed: `...`
- Test results: `X/Y passed` (with details on edge cases verified)

**Git Commit:**
- Commit Hash & Message: `feat(scope): descriptive name`

**Next Planned Task (Awaiting User Permission):**
- [ ] Task ID: Title & planned objective
```

---

## 3. Maintenance Rules
- Never delete prior log entries; preserve historical chronology.
- Keep `logs.md` at the repository root so it is immediately visible to both the user and the agent.
- Log entries must be written immediately upon task completion prior to requesting user approval for the next section.
