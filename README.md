# Full App Sessions

This repo includes five runtime services that must be up for the end-to-end app flow:
- `frontend` (Next.js)
- `solution-agent-service` (Flask)
- `ai-companion` (Flask, Gemini chat endpoint for AI Companion UI)
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

## Prerequisites (one-time setup)

1. Python dependencies:

```bash
pip install -r solution-agent-service/requirements.txt
pip install -r cashflow-modeling-service/api/requirements.txt
pip install -r neoengine-service/api/requirements.txt
```

2. Frontend dependencies:

```bash
cd frontend && pnpm install
```

3. Environment file:
- Ensure repo root `.env` exists and contains required API keys/settings (Gemini, ElevenLabs, etc.).
- `ELEVENLABS_PRESENTATION_AGENT_ID` is required for Policy Detail voice presentation sessions.
- The startup script auto-loads root `.env`.

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

## Temporary Gemini Prompt Logging (Debug)

To inspect the exact context sent to Gemini during advisor runs, temporary prompt logging is enabled by default.

### Log file

- `solution-agent-service/logs/gemini_prompt_debug.ndjson`

Each line is a JSON object with:
- `stage` (`advisor_generate_content` or `ui_transform_generate_content`)
- `timestamp`
- `model`
- `system_instruction`
- `temperature`
- `use_tools` (advisor stage)
- `contents` (serialized Gemini request content)

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
