# Workspace Skills (Vetted & Audited)

These skills are adapted and curated from [`alirezarezvani/claude-skills`](https://github.com/alirezarezvani/claude-skills) and aligned with this project's customer support and SkillOpt engineering workflows.

## Safety & Security Verification
Every skill in this directory has undergone static safety auditing:
- **100% Declarative**: Pure Markdown instructions without arbitrary execution scripts or unverified dependencies.
- **Zero Injections**: Screened against prompt overrides, hidden instructions, and delimiter escapes.
- **Privacy & Safety Preserving**: Built-in guardrails against PII leakage, unauthorized refunds, and destructive system commands.

## Installed Skills
| Skill | Description | Location |
| :--- | :--- | :--- |
| **`customer-support-expert`** | Customer support ticket triage, de-escalation, policy enforcement, and resolution | [SKILL.md](./customer-support-expert/SKILL.md) |
| **`senior-prompt-engineer`** | Instruction architecture, CoT scaffolding, and few-shot calibration for SkillOpt | [SKILL.md](./senior-prompt-engineer/SKILL.md) |
| **`systematic-debugging`** | 4-phase root cause analysis protocol (reproduce → hypothesize → gather evidence → fix) | [SKILL.md](./systematic-debugging/SKILL.md) |
| **`senior-qa-engineer`** | Quality assurance, boundary testing, and adversarial red-teaming for agent policies | [SKILL.md](./senior-qa-engineer/SKILL.md) |
| **`skill-security-auditor`** | Audit checklist to screen future external skills, plugins, and scripts before adoption | [SKILL.md](./skill-security-auditor/SKILL.md) |
