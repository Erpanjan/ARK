# Solution Agent Service

Flask service that runs an agentic workflow using configurable LLM providers and two external tools:
- Cashflow modeling API
- Neo engine optimization API

The service now uses a two-agent pipeline:
- Client Profile Agent (cashflow-only): understands client context and identifies needs/gaps.
- Solution Agent (existing advisor logic): builds Step-1 financial planning policy.

## Key Design Choices

- Stage-selectable LLM provider/model (Gemini/OpenAI) with stage-local fallbacks.
- Three-step policy pipeline:
  1) Client Profile Agent runs a cashflow-only loop and outputs profile/gap analysis.
  2) Solution Agent runs a tool-enabled loop (cashflow + Neo) and produces Step-1 policy JSON.
  3) A standalone UI generation step calls configured LLM again to convert Step-1 policy JSON into UI JSON.
- Neo tool inputs exposed to the model: only:
  - `target_volatility`
  - `active_risk_percentage`
- Neo internals are fixed by service config:
  - `risk_profile` (default `RP3`)
  - `weight_type` (default `dynamic`)
- Prompts are externalized under `prompts/` for easy edits.
- Neo output is compacted before entering model context to avoid context bloat.

## Files

- `app.py`: Flask API.
- `advisor_agent.py`: core agent loop, tool clients, compaction logic.
- `../client-profile-agent-service/client_profile_agent.py`: client profile agent implementation.
- `../client-profile-agent-service/prompts/`: prompts for profile analysis stage.
- `prompts/agent_system.txt`: system prompt used for tool-enabled advisor reasoning.
- `prompts/core_policy_prompt.txt`: Step-1 policy JSON template.
- `../policy_ui_transform/generator.py`: standalone policy->UI generation step.
- `../policy_ui_transform/prompts/system_prompt.txt`: system prompt for UI generation step.

## Setup

1. Use repo root `.env` as the source of truth.

Supported env names (advisor reads either form):
- Gemini key: `GOOGLE_GENAI_API_KEY` or `GEMINI_API_KEY`
- OpenAI key: `OPENAI_API_KEY`
- Neo URL: `NEOENGINE_API_URL` or `PYTHON_NEO_ENGINE_URL`
- Neo key: `NEOENGINE_API_KEY` or `NEO_ENGINE_API_KEY`
- Cashflow URL: `CASHFLOW_API_URL` or `CASHFLOW_MODEL_URL`
- Optional cashflow key: `CASHFLOW_API_KEY`

Stage-level LLM config (primary + fallback chain):
- `CLIENT_PROFILE_TOOL_LOOP_PROVIDER`, `CLIENT_PROFILE_TOOL_LOOP_MODEL`, `CLIENT_PROFILE_TOOL_LOOP_FALLBACKS`
- `CLIENT_PROFILE_SYNTHESIS_PROVIDER`, `CLIENT_PROFILE_SYNTHESIS_MODEL`, `CLIENT_PROFILE_SYNTHESIS_FALLBACKS`
- `SOLUTION_TOOL_LOOP_PROVIDER`, `SOLUTION_TOOL_LOOP_MODEL`, `SOLUTION_TOOL_LOOP_FALLBACKS`
- `SOLUTION_SYNTHESIS_PROVIDER`, `SOLUTION_SYNTHESIS_MODEL`, `SOLUTION_SYNTHESIS_FALLBACKS`
- `POLICY_UI_PROVIDER`, `POLICY_UI_MODEL`, `POLICY_UI_FALLBACKS`

Fallback format: comma-separated `provider:model` entries, for example:
`openai:gpt-4.1-mini,gemini:models/gemini-2.5-pro`.

2. Install dependencies:

```bash
pip install -r solution-agent-service/requirements.txt
```

3. Run service:

```bash
cd solution-agent-service
python app.py
```

Service default port: `8002` (set `ADVISOR_PORT` to override).
If repo root `.env` has `PORT=3000` for frontend, advisor will still stay on `8002` unless `ADVISOR_PORT` is set.

## Endpoints

- `GET /health`
- `GET /advisor/api/v1/tool-health`
- `POST /advisor/api/v1/generate-policy-json`
- `POST /advisor/api/v1/generate-step1-policy-json`
- `POST /advisor/api/v1/consultation-ingest`
- `GET /advisor/api/v1/consultation-ingest/latest`
- `GET /advisor/api/v1/consultation-ingest/<ingest_id>`

## Request Example

```json
{
  "consultation_transcript": {
    "session_id": "consult-123",
    "turns": [
      { "speaker": "agent", "text": "What prompted you to seek planning support?", "ts_start_ms": 1710000000000 },
      { "speaker": "client", "text": "I want to be ready for retirement and college costs.", "ts_start_ms": 1710000005000 }
    ]
  },
  "advisor_request": "Focus on retirement sufficiency and liquidity resilience."
}
```

You can also provide `consultation_ingest_id` instead of `consultation_transcript` after calling `POST /advisor/api/v1/consultation-ingest`.

## Response Shape

`POST /advisor/api/v1/generate-policy-json` returns one structured JSON payload used as single source of truth for menu/detail/execution UI.
Error responses remain JSON.

## Notes

- `tool-health` is the quickest way to validate connectivity/auth to both tool APIs.
- If `ADVISOR_API_KEY` is set, include it as `X-Api-Key` header for advisor endpoints.
- Legacy vars still work:
  - `ADVISOR_GEMINI_MODEL`
  - `ADVISOR_UI_GEMINI_MODEL`
  - `ADVISOR_GEMINI_FALLBACK_MODELS` (Gemini-only list)
