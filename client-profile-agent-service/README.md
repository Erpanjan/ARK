# Client Profile Agent

This agent is the first stage in the two-agent advisory flow.

Responsibilities:
- Understand client context from consultation conversation input.
- Run cashflow-based baseline and stress diagnostics.
- Identify needs and gap categories (`investment related`, `insurance related`, `spending related`, `liability related`).

Tool access:
- `runCashflowModel` only.

Output:
- Structured client profile/gap analysis JSON used as the Stage-2 input package for the solution agent.
