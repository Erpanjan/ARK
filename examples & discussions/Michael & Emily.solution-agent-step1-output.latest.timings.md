# Michael & Emily - Step1 Timing Breakdown (Latest Run)

- HTTP status: `200`
- Total API time (`/advisor/api/v1/generate-step1-policy-json`): `107.923531s`
- LLM stage-window span (first stage log to last): `88.492s`

## Stage Timings (from prompt log timestamps)

### client_profile_tool_loop
- provider/model: `openai` / `gpt-4.1-mini`
- call count: `3`
- first log timestamp: `2026-03-07T10:26:10.774746+00:00`
- last log timestamp: `2026-03-07T10:26:19.478003+00:00`
- stage span: `8.703s`

### client_profile_synthesis
- provider/model: `openai` / `gpt-4.1`
- call count: `1`
- first log timestamp: `2026-03-07T10:26:31.954740+00:00`
- last log timestamp: `2026-03-07T10:26:31.954740+00:00`
- stage span: `0.000s`

### solution_tool_loop
- provider/model: `openai` / `gpt-4.1-mini`
- call count: `6`
- first log timestamp: `2026-03-07T10:26:51.555366+00:00`
- last log timestamp: `2026-03-07T10:27:36.432920+00:00`
- stage span: `44.878s`

### solution_synthesis
- provider/model: `openai` / `gpt-4.1`
- call count: `1`
- first log timestamp: `2026-03-07T10:27:39.266292+00:00`
- last log timestamp: `2026-03-07T10:27:39.266292+00:00`
- stage span: `0.000s`

## Notes

- Stage spans are derived from request log timestamps, not wall-clock tool/service internals.
- Gaps between stages include tool execution and orchestration time not captured as LLM generate logs.