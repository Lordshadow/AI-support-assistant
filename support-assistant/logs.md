
## REFUND-PRESENTATION-20261116 - Standard customer refund wording
**Timestamp:** 2026-11-16 13:30 Asia/Calcutta
**Status:** VERIFIED
**Objective & Rationale ("Why"):**
- Use concise, standard processed wording for the demo presentation while retaining the internal simulation marker and avoiding claims that funds were credited.
**Architectural Boundaries & Modularity:**
- Internal refund records remain marked as simulated; only customer-facing messages and serialized order history are normalized.
**Files Touched:**
- `support-assistant/adapters/postgres/refund_repository.py`, `support-assistant/services/worker/llm_client.py`, `support-assistant/services/worker/orchestrator.py`, and focused tests.
**Verification & Quality Assurance:**
- Commands: targeted adapter and orchestrator tests passed.
**Git Commit:**
- Pending.
**Next Planned Task (Awaiting User Permission):**
- Deploy the updated assistant image.
