# Method of Procedure (MOP) — required sections

Fill in every section with specific technical detail. No placeholder text.
Every CLI command must be exact and vendor-specific.

1. **Purpose & Scope** — what this change accomplishes and what systems are affected
2. **Change Description** — technical summary of the change
3. **Prerequisites** — hardware, software, backups, approvals required before starting
4. **Pre-Maintenance Verification** — exact CLI commands to verify system state before starting
5. **Step-by-Step Procedure** — numbered steps with expected output for each step
6. **Post-Maintenance Verification** — exact CLI commands to confirm success
7. **Rollback Procedure** — specific steps to revert, triggered by defined failure criteria
8. **Communication Plan** — who to notify before, during, and after the change
9. **Sign-Off** — engineer, peer reviewer, change manager approval lines

## Quality bar

Every step must have an expected output. Rollback must have specific trigger criteria,
not just "if something goes wrong".

Mark any section you could not ground in retrieved vendor data as
**UNVERIFIED — confirm with vendor documentation before executing**.
