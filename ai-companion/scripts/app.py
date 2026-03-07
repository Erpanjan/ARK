"""Gemini-backed AI Companion chat service.

Flow enforced:
1) normal text conversation,
2) detect financial consultation intent,
3) ask for confirmation,
4) activate consultation only after explicit confirmation.
"""

from __future__ import annotations

import json
import os
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Literal, Optional

from flask import Flask, jsonify, request
from flask_cors import CORS

Stage = Literal["chat", "awaiting_confirmation", "consultation_active"]


@dataclass
class CompanionState:
    stage: Stage = "chat"


REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))
PROMPT_PATH = REPO_ROOT / "ai-companion" / "ai-companion-prompt" / "ai_companion_system_prompt.txt"

from shared.llm import LLMClientFactory, LLMGenerateRequest, LLMMessage, dedupe_model_chain, parse_fallback_chain


def _load_root_env() -> Dict[str, str]:
    """Lightweight .env parser to avoid extra dependency footprint."""
    env_path = REPO_ROOT / ".env"
    values: Dict[str, str] = {}
    if not env_path.exists():
        return values

    for raw in env_path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        values[key] = value
    return values


def _get_gemini_key() -> str:
    env = _load_root_env()
    return (
        os.getenv("GOOGLE_GENAI_API_KEY", "").strip()
        or os.getenv("GEMINI_API_KEY", "").strip()
        or env.get("GOOGLE_GENAI_API_KEY", "").strip()
        or env.get("GEMINI_API_KEY", "").strip()
    )


def _get_openai_key() -> str:
    env = _load_root_env()
    return os.getenv("OPENAI_API_KEY", "").strip() or env.get("OPENAI_API_KEY", "").strip()


def _extract_json(raw: str) -> Dict[str, Any]:
    text = raw.strip()
    if not text:
        raise ValueError("Empty model response")

    try:
        parsed = json.loads(text)
        if isinstance(parsed, dict):
            return parsed
    except json.JSONDecodeError:
        pass

    match = re.search(r"\{[\s\S]*\}", text)
    if not match:
        raise ValueError("No JSON object in model response")

    parsed = json.loads(match.group(0))
    if not isinstance(parsed, dict):
        raise ValueError("Model response JSON must be an object")
    return parsed


def _normalize_stage(value: Any) -> Stage:
    text = str(value or "").strip().lower()
    if text in {"chat", "awaiting_confirmation", "consultation_active"}:
        return text  # type: ignore[return-value]
    return "chat"


def _is_affirmative(text: str) -> bool:
    normalized = re.sub(r"[^a-z0-9\s]", " ", text.lower())
    patterns = [
        r"\byes\b",
        r"\byep\b",
        r"\byeah\b",
        r"\bsure\b",
        r"\bok\b",
        r"\bokay\b",
        r"\bstart\b",
        r"\blet s do it\b",
        r"\bgo ahead\b",
        r"\bdo it\b",
    ]
    return any(re.search(pattern, normalized) for pattern in patterns)


def _is_negative(text: str) -> bool:
    normalized = re.sub(r"[^a-z0-9\s]", " ", text.lower())
    patterns = [r"\bno\b", r"\bnot now\b", r"\blater\b", r"\bwait\b", r"\bhold on\b"]
    return any(re.search(pattern, normalized) for pattern in patterns)


def _detect_consultation_intent(text: str) -> bool:
    normalized = re.sub(r"[^a-z0-9\s]", " ", text.lower())
    keywords = [
        "financial advice",
        "financial guidance",
        "investment advice",
        "retirement plan",
        "retirement planning",
        "portfolio",
        "asset allocation",
        "budget",
        "debt plan",
        "insurance planning",
        "financial consultation",
        "financial plan",
        "wealth plan",
        "help me invest",
        "help with my finances",
    ]
    return any(keyword in normalized for keyword in keywords)


def _sanitize_messages(messages: Any) -> List[Dict[str, str]]:
    if not isinstance(messages, list):
        return []
    clean: List[Dict[str, str]] = []
    for item in messages:
        if not isinstance(item, dict):
            continue
        role = str(item.get("role", "")).strip().lower()
        content = str(item.get("content", "")).strip()
        if role not in {"user", "assistant"} or not content:
            continue
        clean.append({"role": role, "content": content})
    return clean[-20:]


def _build_contents(messages: List[Dict[str, str]]) -> List[LLMMessage]:
    contents: List[LLMMessage] = []
    for row in messages:
        role = "user" if row["role"] == "user" else "assistant"
        contents.append(LLMMessage(role=role, content=row["content"]))
    return contents


class MultiProviderCompanion:
    def __init__(self) -> None:
        self.google_api_key = _get_gemini_key()
        self.openai_api_key = _get_openai_key()
        provider = os.getenv("AI_COMPANION_PROVIDER", "gemini").strip().lower() or "gemini"
        model = (
            os.getenv("AI_COMPANION_MODEL", "").strip()
            or os.getenv("AI_COMPANION_GEMINI_MODEL", "").strip()
            or "models/gemini-2.5-pro"
        )
        fallback_raw = os.getenv("AI_COMPANION_FALLBACKS", "").strip()
        fallbacks = parse_fallback_chain(fallback_raw) if fallback_raw else []
        self.chain = dedupe_model_chain((provider, model), fallbacks)
        if not self.chain:
            raise RuntimeError("AI companion model chain is empty")
        if not self.google_api_key and not self.openai_api_key:
            raise RuntimeError(
                "Missing LLM API key. Set GOOGLE_GENAI_API_KEY/GEMINI_API_KEY and/or OPENAI_API_KEY."
            )
        self.provider = self.chain[0][0]
        self.model = self.chain[0][1]
        self.system_prompt = PROMPT_PATH.read_text(encoding="utf-8").strip()

    def chat(self, messages: List[Dict[str, str]], state: CompanionState) -> Dict[str, Any]:
        latest_user = ""
        for row in reversed(messages):
            if row["role"] == "user":
                latest_user = row["content"]
                break

        if not latest_user:
            return {
                "assistant_message": "Share what is on your mind, and I will help you sort it out.",
                "detected_consultation_intent": False,
                "needs_confirmation": False,
                "activate_consultation": False,
                "ui_action": "none",
                "state": {"stage": state.stage},
            }

        affirmative = _is_affirmative(latest_user)
        negative = _is_negative(latest_user)
        intent = _detect_consultation_intent(latest_user)

        # Hard gate: consultation cannot activate without explicit confirmation.
        if state.stage == "awaiting_confirmation" and affirmative:
            return {
                "assistant_message": "Great, I am starting your structured financial consultation now.",
                "detected_consultation_intent": True,
                "needs_confirmation": False,
                "activate_consultation": True,
                "ui_action": "activate_consultation_phone",
                "state": {"stage": "consultation_active"},
            }

        if state.stage == "awaiting_confirmation" and negative:
            return {
                "assistant_message": "No problem. We can stay in chat mode and continue whenever you are ready.",
                "detected_consultation_intent": False,
                "needs_confirmation": False,
                "activate_consultation": False,
                "ui_action": "none",
                "state": {"stage": "chat"},
            }

        if state.stage == "awaiting_confirmation" and not (affirmative or negative):
            return {
                "assistant_message": "Whenever you are ready, reply yes to start the structured financial consultation.",
                "detected_consultation_intent": True,
                "needs_confirmation": True,
                "activate_consultation": False,
                "ui_action": "none",
                "state": {"stage": "awaiting_confirmation"},
            }

        contents = _build_contents(messages)
        instructions = (
            "Current stage: "
            f"{state.stage}\n"
            "Heuristic signals:\n"
            f"- intent_detected={str(intent).lower()}\n"
            f"- latest_user_affirmative={str(affirmative).lower()}\n"
            f"- latest_user_negative={str(negative).lower()}\n"
            "Return strict JSON only."
        )
        contents.append(LLMMessage(role="user", content=instructions))

        response = None
        last_error: Optional[Exception] = None
        provider_used = self.provider
        model_used = self.model
        for provider_name, model_name in self.chain:
            try:
                adapter = LLMClientFactory.create(
                    provider=provider_name,
                    google_api_key=self.google_api_key,
                    openai_api_key=self.openai_api_key,
                    timeout_ms=int(os.getenv("AI_COMPANION_LLM_TIMEOUT_MS", "90000") or "90000"),
                )
                response = adapter.generate(
                    request=LLMGenerateRequest(
                        messages=contents,
                        system_instruction=self.system_prompt,
                        temperature=0.35,
                    ),
                    model=model_name,
                )
                provider_used = provider_name
                model_used = model_name
                break
            except Exception as exc:  # pylint: disable=broad-except
                last_error = exc
                message = str(exc)
                if "429" in message or "RESOURCE_EXHAUSTED" in message:
                    continue
                if "404" in message or "NOT_FOUND" in message:
                    continue
                raise

        if response is None:
            raise RuntimeError(f"AI companion generation failed: {last_error}")

        raw = (response.text or "").strip()
        parsed = _extract_json(raw)

        assistant_message = str(parsed.get("assistant_message", "")).strip()
        if not assistant_message:
            assistant_message = "I can help with that. Tell me a bit more about your financial goal."

        result = {
            "assistant_message": assistant_message,
            "detected_consultation_intent": bool(parsed.get("detected_consultation_intent", False)),
            "needs_confirmation": bool(parsed.get("needs_confirmation", False)),
            "activate_consultation": bool(parsed.get("activate_consultation", False)),
            "ui_action": str(parsed.get("ui_action", "none") or "none"),
        }

        # Deterministic transition overrides for required UX behavior.
        if state.stage == "chat" and intent:
            result["detected_consultation_intent"] = True
            result["needs_confirmation"] = True
            result["activate_consultation"] = False
            result["ui_action"] = "none"
            if "consultation" not in result["assistant_message"].lower():
                result["assistant_message"] += " I can switch us into a structured financial consultation now. Do you want to start it?"

        if result["activate_consultation"]:
            result["detected_consultation_intent"] = True
            result["needs_confirmation"] = False
            result["ui_action"] = "activate_consultation_phone"

        next_stage: Stage = state.stage
        if result["activate_consultation"]:
            next_stage = "consultation_active"
        elif result["needs_confirmation"]:
            next_stage = "awaiting_confirmation"
        elif state.stage != "consultation_active":
            next_stage = "chat"

        result["state"] = {"stage": next_stage}
        result["provider_used"] = provider_used
        result["model_used"] = model_used
        return result


app = Flask(__name__)
CORS(app)


def _build_agent() -> MultiProviderCompanion:
    return MultiProviderCompanion()


try:
    AGENT = _build_agent()
except Exception as exc:  # pylint: disable=broad-except
    AGENT = None
    STARTUP_ERROR = str(exc)
else:
    STARTUP_ERROR = None


@app.get("/health")
def health() -> Any:
    if STARTUP_ERROR:
        return jsonify({"success": False, "error": STARTUP_ERROR}), 500
    return jsonify(
        {
            "success": True,
            "service": "ai-companion",
            "provider": AGENT.provider,
            "model": AGENT.model,
            "fallbacks": AGENT.chain[1:],
        }
    )


@app.post("/api/v1/ai-companion/chat")
def chat() -> Any:
    if STARTUP_ERROR or AGENT is None:
        return jsonify({"success": False, "error": STARTUP_ERROR or "Agent unavailable"}), 500

    payload = request.get_json(silent=True) or {}
    messages = _sanitize_messages(payload.get("messages"))
    state_payload = payload.get("state") if isinstance(payload.get("state"), dict) else {}
    state = CompanionState(stage=_normalize_stage(state_payload.get("stage")))

    try:
        result = AGENT.chat(messages=messages, state=state)
        return jsonify({"success": True, **result})
    except Exception as exc:  # pylint: disable=broad-except
        return jsonify({"success": False, "error": "AI companion chat failed", "details": str(exc)}), 500


if __name__ == "__main__":
    port = int(os.getenv("AI_COMPANION_PORT", "8010"))
    app.run(host="0.0.0.0", port=port, debug=os.getenv("FLASK_DEBUG", "false").lower() == "true")
