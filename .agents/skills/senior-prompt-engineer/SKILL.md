---
name: senior-prompt-engineer
description: >-
  Expert guidelines for designing, refining, and optimizing LLM system prompts, agent instructions,
  and few-shot evaluations. Use when architecting agent skills, creating prompt benchmarks,
  or tuning agent behaviors.
---

# Senior Prompt Engineer Skill

## Purpose & Scope
Provides advanced methodologies for constructing high-reliability system prompts, structured agent runbooks, and self-improving prompt architectures. Designed to maximize reasoning fidelity, reduce hallucinations, and establish robust guardrails.

---

## 1. System Prompt Architecture

### Core Building Blocks
Every production-grade agent instruction file or system prompt should follow a hierarchical structure:
1. **Identity & Role**: Concise definition of domain expertise and operational posture.
2. **Context & Environment**: Description of the runtime environment, tools available, and scope of autonomy.
3. **Behavioral Principles & Constraints**: Non-negotiable boundaries, safety rules, and negative constraints ("Never do X").
4. **Execution Protocol (Step-by-Step)**: Clear, phased workflows for handling tasks from input to completion.
5. **Output Schema & Formatting**: Deterministic formats (JSON, structured Markdown, XML tags) for downstream consumption.
6. **Edge Case Handling**: Explicit instructions for ambiguous, hostile, or incomplete inputs.

---

## 2. Advanced Prompting Techniques

### Chain-of-Thought (CoT) & Reasoning Scaffolding
- Prompt the model to analyze context and constraints internally before committing to stateful tool calls or customer-facing responses.
- Explicitly instruct: "Verify all relevant policies before formulating the resolution."

### Few-Shot & In-Context Calibration
- Provide balanced, high-variance examples covering edge cases (e.g., standard request, borderline policy case, adversarial prompt injection attempt).
- Ensure examples illustrate the exact desired output format and tone.

### Negative Constraints vs. Positive Alternatives
- Pair every prohibition with a concrete permitted alternative:
  - *Bad*: "Do not give refunds for digital items."
  - *Good*: "Digital items are non-refundable once delivered. If a customer insists, offer store credit or escalate to a supervisor."

---

## 3. Optimization & Self-Evolution (SkillOpt Alignment)
When refining skills using iterative optimization loops (e.g., SkillOpt):
- **Bounded Edits**: Make incremental, atomic modifications to policies rather than full rewrites.
- **Validation Gates**: Ensure prompt changes improve target metrics on held-out test splits without introducing regressions on baseline tests.
- **Semantic Density**: Keep skill markdown concise (typically 300–2,000 tokens) to minimize context window overhead.
