# Michael & Emily Pipeline Timings (Latest)

- Stage 1 (Client Profile Agent): 95.15s
- Stage 2 (Solution Agent Step-1 JSON): 129.74s
- Stage 3 (UI Policy Transform + Normalize): 31.86s
- Total End-to-End: 256.75s

## Output Files
- /Users/erpanjianyasen/Desktop/Arc/backend-experiement-ai-architecture/examples & discussions/Michael & Emily.profile-agent-output.latest.json
- /Users/erpanjianyasen/Desktop/Arc/backend-experiement-ai-architecture/examples & discussions/Michael & Emily.solution-agent-step1-output.latest.json
- /Users/erpanjianyasen/Desktop/Arc/backend-experiement-ai-architecture/examples & discussions/Michael & Emily.solution-agent-final-policy.latest.json
- /Users/erpanjianyasen/Desktop/Arc/backend-experiement-ai-architecture/examples & discussions/Michael & Emily.solution-agent-output.latest.md

## Route-Level App Timings (In-Process Test Client)
- Endpoint 1 `POST /advisor/api/v1/consultation-ingest`: 0.00s
- Endpoint 2 `POST /advisor/api/v1/generate-policy-json`: 254.81s
- Route-Level Total: 254.81s
