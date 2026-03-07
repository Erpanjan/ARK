# Full App Sessions

This repo includes five runtime services that must be up for the end-to-end app flow:
- `frontend` (Next.js)
- `solution-agent-service` (Flask)
- `ai-companion` (Flask, multi-provider LLM chat endpoint for AI Companion UI)
- `cashflow-modeling-service` API (Flask)
- `neoengine-service` API (Flask)

## Commands

From repo root:

Start all sessions:

```bash
./scripts/dev-up.sh
```

Stop all sessions:

```bash
./scripts/dev-down.sh
```

Verify services:

```bash
curl http://localhost:3000 >/dev/null && echo "frontend ok"
curl http://localhost:8002/health && echo
curl http://localhost:8010/health && echo
curl http://localhost:8001/health && echo
curl http://localhost:8000/health && echo
```

## Prerequisites (one-time setup)

1. Python dependencies:

```bash
pip install -r solution-agent-service/requirements.txt
pip install -r cashflow-modeling-service/api/requirements.txt
pip install -r neoengine-service/api/requirements.txt
```

Notes:
- `./scripts/dev-up.sh` auto-checks AI Companion runtime deps and will attempt to install missing `ai-companion/scripts/requirements.txt` with the same interpreter used for advisor/companion.
- Cashflow still requires its Python runtime dependencies to be pre-installed for `CASHFLOW_PYTHON`.

2. Frontend dependencies:

```bash
cd frontend && pnpm install
```

3. Environment file:
- Ensure repo root `.env` exists and contains required API keys/settings (Gemini/OpenAI, ElevenLabs, etc.).
- `ELEVENLABS_PRESENTATION_AGENT_ID` is required for Policy Detail voice presentation sessions.
- The startup script auto-loads root `.env`.

### Multi-provider LLM config (root `.env`)

Global keys:
- `GOOGLE_GENAI_API_KEY` or `GEMINI_API_KEY`
- `OPENAI_API_KEY`

Advisor stages:
- `CLIENT_PROFILE_TOOL_LOOP_PROVIDER`, `CLIENT_PROFILE_TOOL_LOOP_MODEL`, `CLIENT_PROFILE_TOOL_LOOP_FALLBACKS`
- `CLIENT_PROFILE_SYNTHESIS_PROVIDER`, `CLIENT_PROFILE_SYNTHESIS_MODEL`, `CLIENT_PROFILE_SYNTHESIS_FALLBACKS`
- `SOLUTION_TOOL_LOOP_PROVIDER`, `SOLUTION_TOOL_LOOP_MODEL`, `SOLUTION_TOOL_LOOP_FALLBACKS`
- `SOLUTION_SYNTHESIS_PROVIDER`, `SOLUTION_SYNTHESIS_MODEL`, `SOLUTION_SYNTHESIS_FALLBACKS`
- `POLICY_UI_PROVIDER`, `POLICY_UI_MODEL`, `POLICY_UI_FALLBACKS`

AI Companion stage:
- `AI_COMPANION_PROVIDER`, `AI_COMPANION_MODEL`, `AI_COMPANION_FALLBACKS`

Fallback format: comma-separated `provider:model` entries, e.g. `openai:gpt-4.1-mini,gemini:models/gemini-2.5-pro`.

## Default Local URLs

- Frontend: `http://localhost:3000`
- Advisor health: `http://localhost:8002/health`
- AI Companion health: `http://localhost:8010/health`
- Cashflow health: `http://localhost:8001/health`
- Neo health: `http://localhost:8000/health`

## Optional Port Overrides

If needed, override ports before the command:

```bash
FRONTEND_PORT=3001 ADVISOR_PORT=8102 AI_COMPANION_PORT=8110 CASHFLOW_PORT=8101 NEOENGINE_PORT=8100 ./scripts/dev-up.sh
```

If your default `python3` is not the one with required deps, pin interpreter explicitly:

```bash
ADVISOR_PYTHON=/Users/erpanjianyasen/opt/anaconda3/bin/python3 ./scripts/dev-up.sh
```

The same environment variable overrides are honored by:

```bash
FRONTEND_PORT=3001 ADVISOR_PORT=8102 AI_COMPANION_PORT=8110 CASHFLOW_PORT=8101 NEOENGINE_PORT=8100 ./scripts/dev-down.sh
```

## Port Conflicts (`EADDRINUSE`)

`./scripts/dev-up.sh` now performs a mandatory preflight using `lsof` on required ports
(`3000`, `8002`, `8010`, `8001`, `8000` by default). If any port is already in use, startup exits
immediately with:
- Which service expected that port
- The PID/command currently listening
- A suggested `kill -TERM ...` command

Recommended workflow when you see `EADDRINUSE`:

1. Stop known local app listeners:

```bash
./scripts/dev-down.sh
```

2. Start cleanly:

```bash
./scripts/dev-up.sh
```

Why this matters:
- Prevents mixed old/new process states.
- Ensures requests hit the instance you just started.
- Makes debugging deterministic by failing fast before partial startup.

## Logs / Troubleshooting

All runtime logs are in `.logs/`:
- `.logs/frontend.log`
- `.logs/advisor.log`
- `.logs/ai-companion.log`
- `.logs/cashflow.log`
- `.logs/neoengine.log`

Useful checks:

```bash
tail -n 120 .logs/ai-companion.log
tail -n 120 .logs/frontend.log
```

## Temporary LLM Prompt Logging (Debug)

To inspect the exact context sent to the configured LLM during advisor runs, temporary prompt logging is enabled by default.

### Log file

- `solution-agent-service/logs/gemini_prompt_debug.ndjson`

Each line is a JSON object with:
- `stage` (`client_profile_tool_loop`, `client_profile_synthesis`, `solution_tool_loop`, `solution_synthesis`, or `ui_transform_generate_content`)
- `timestamp`
- `provider`
- `model`
- `system_instruction`
- `temperature`
- `use_tools` (advisor stage)
- `contents` (serialized request content)

### Toggle / override

Disable logging:

```bash
ADVISOR_TEMP_LOG_PROMPTS=false ./scripts/dev-up.sh
```

Override log path:

```bash
ADVISOR_TEMP_PROMPT_LOG_PATH=/tmp/gemini_prompt_debug.ndjson ./scripts/dev-up.sh
```

### Inspect latest entries

```bash
tail -n 20 solution-agent-service/logs/gemini_prompt_debug.ndjson
```
