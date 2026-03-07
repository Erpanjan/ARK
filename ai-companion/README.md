# AI Companion Module

This folder contains all AI Companion-specific assets:

- `ai-companion-prompt/`: imported Poke prompts + adapted prompt set for this product.
- `scripts/app.py`: Gemini-backed chat agent service used by the frontend AI Companion screen.
- `scripts/requirements.txt`: Python dependencies for the AI Companion service.

## Implemented interaction flow

1. User chats with AI Companion in text.
2. If user expresses financial-guidance intent, assistant acknowledges and asks for confirmation.
3. After explicit confirmation, backend returns `ui_action=activate_consultation_phone`.
4. Frontend uses that signal to auto-transition into consultation screen (voice starts only when user taps start there).

## Run the AI Companion service

From repo root:

```bash
python3 -m venv .venv-ai-companion
source .venv-ai-companion/bin/activate
pip install -r ai-companion/scripts/requirements.txt
python ai-companion/scripts/app.py
```

Service defaults:

- Base URL: `http://localhost:8010`
- Chat endpoint: `POST /api/v1/ai-companion/chat`
- Health endpoint: `GET /health`

## Frontend wiring

The existing AI Companion UI in `frontend/components/product-vision/screens/Screen7.tsx` now sends chat requests to:

- Next route: `frontend/app/api/ai-companion/chat/route.ts`
- Proxy target: `AI_COMPANION_SERVICE_URL` (default `http://localhost:8010`)

Required API keys are read from repo root `.env` via the backend service (`GOOGLE_GENAI_API_KEY` or `GEMINI_API_KEY`).
