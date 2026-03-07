"""Flask API for advisor agent orchestration."""

from __future__ import annotations

import json
import os
import sys
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

import requests
from flask import Flask, jsonify, request

try:
    from dotenv import load_dotenv

    # Consolidated env loading:
    # 1) repo root .env (shared source of truth, overrides process env)
    # 2) local advisor .env (optional, does not override root .env)
    service_dir = Path(__file__).resolve().parent
    root_env_path = service_dir.parent / ".env"
    root_evn_path = service_dir.parent / ".evn"
    local_env_path = service_dir / ".env"
    if root_env_path.exists():
        load_dotenv(root_env_path, override=True)
    elif root_evn_path.exists():
        load_dotenv(root_evn_path, override=True)
    if local_env_path.exists():
        load_dotenv(local_env_path, override=False)
except ImportError:
    pass

_SERVICE_DIR = Path(__file__).resolve().parent
_REPO_ROOT = _SERVICE_DIR.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))
_CLIENT_PROFILE_AGENT_DIR = _REPO_ROOT / "client-profile-agent-service"
if str(_CLIENT_PROFILE_AGENT_DIR) not in sys.path:
    sys.path.insert(0, str(_CLIENT_PROFILE_AGENT_DIR))

from advisor_agent import AdvisorAgent, AdvisorConfig
from client_profile_agent import ClientProfileAgent, build_client_profile_agent
from policy_ui_transform.generator import PolicyUiGenerator

app = Flask(__name__)

_SOLUTION_AGENT: Optional[AdvisorAgent] = None
_CLIENT_PROFILE_AGENT: Optional[ClientProfileAgent] = None
_POLICY_UI_GENERATOR: Optional[PolicyUiGenerator] = None
_CONSULTATION_INGESTS: Dict[str, Dict[str, Any]] = {}
_INGEST_LOCK = threading.Lock()

_INGEST_STORE_PATH = Path(
    os.getenv(
        "ADVISOR_INGEST_STORE_PATH",
        str(_SERVICE_DIR / "logs" / "consultation_ingests.ndjson"),
    )
)


def _load_ingests_from_disk() -> None:
    """Hydrate in-memory ingest cache from NDJSON store."""
    if not _INGEST_STORE_PATH.exists():
        return

    loaded_rows: Dict[str, Dict[str, Any]] = {}
    try:
        for raw_line in _INGEST_STORE_PATH.read_text(encoding="utf-8").splitlines():
            line = raw_line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            if not isinstance(row, dict):
                continue
            ingest_id = str(row.get("ingest_id", "") or "").strip()
            if ingest_id:
                loaded_rows[ingest_id] = row
    except OSError:
        # Non-fatal: API still works with in-memory ingest cache.
        pass

    if loaded_rows:
        with _INGEST_LOCK:
            _CONSULTATION_INGESTS.update(loaded_rows)


def _append_ingest_to_disk(ingest_payload: Dict[str, Any]) -> None:
    """Append ingest payload to NDJSON store for restart resilience."""
    _INGEST_STORE_PATH.parent.mkdir(parents=True, exist_ok=True)
    record = json.dumps(ingest_payload, ensure_ascii=True)
    with _INGEST_LOCK:
        with _INGEST_STORE_PATH.open("a", encoding="utf-8") as handle:
            handle.write(record + "\n")


_load_ingests_from_disk()


def _get_ingested_consultation(ingest_id: str) -> Optional[Dict[str, Any]]:
    """Fetch consultation ingest payload by ID."""
    if not ingest_id:
        return None
    with _INGEST_LOCK:
        return _CONSULTATION_INGESTS.get(ingest_id)


def _build_profile_agent_input_with_consultation_context(
    body: Dict[str, Any]
) -> Tuple[Optional[Dict[str, Any]], str, Optional[Tuple[Any, int]]]:
    """Build Stage-1 profile-agent input from consultation context only."""
    advisor_request = str(body.get("advisor_request", "") or "")
    consultation_ingest_id = str(body.get("consultation_ingest_id", "") or "").strip()
    provided_transcript = body.get("consultation_transcript")
    profile_input: Dict[str, Any] = {}

    if consultation_ingest_id:
        ingested = _get_ingested_consultation(consultation_ingest_id)
        if not ingested:
            return None, advisor_request, (
                jsonify(
                    {
                        "success": False,
                        "error": "consultation_ingest_id not found",
                        "consultation_ingest_id": consultation_ingest_id,
                    }
                ),
                404,
            )

        profile_input["consultation_transcript"] = ingested.get("transcript", {})
        profile_input["consultation_ingest_ref"] = {
            "ingest_id": consultation_ingest_id,
            "session_id": ingested.get("session_id"),
            "created_at": ingested.get("created_at"),
        }
    else:
        if isinstance(provided_transcript, dict):
            profile_input["consultation_transcript"] = provided_transcript

    transcript = profile_input.get("consultation_transcript")
    turns = transcript.get("turns") if isinstance(transcript, dict) else None
    if not isinstance(turns, list) or not any(isinstance(turn, dict) for turn in turns):
        return None, advisor_request, (
            jsonify(
                {
                    "success": False,
                    "error": (
                        "consultation_transcript with non-empty turns is required for Stage-1 "
                        "client profile generation"
                    ),
                }
            ),
            400,
        )

    return profile_input, advisor_request, None


def get_solution_agent() -> AdvisorAgent:
    """Lazily initialize solution agent from environment config."""
    global _SOLUTION_AGENT
    if _SOLUTION_AGENT is None:
        config = AdvisorConfig.from_env()
        config.max_tool_iterations = int(
            os.getenv(
                "SOLUTION_AGENT_MAX_TOOL_ITERATIONS",
                str(config.max_tool_iterations),
            )
        )
        config.max_cashflow_calls = int(
            os.getenv(
                "SOLUTION_AGENT_MAX_CASHFLOW_CALLS",
                str(config.max_cashflow_calls),
            )
        )
        config.max_neo_calls = int(
            os.getenv(
                "SOLUTION_AGENT_MAX_NEO_CALLS",
                str(config.max_neo_calls),
            )
        )
        prompts_dir = Path(__file__).resolve().parent / "prompts"
        _SOLUTION_AGENT = AdvisorAgent(config=config, prompts_dir=prompts_dir)
    return _SOLUTION_AGENT


def get_client_profile_agent() -> ClientProfileAgent:
    """Lazily initialize client profile agent from environment config."""
    global _CLIENT_PROFILE_AGENT
    if _CLIENT_PROFILE_AGENT is None:
        config = AdvisorConfig.from_env()
        config.max_tool_iterations = int(
            os.getenv(
                "CLIENT_PROFILE_AGENT_MAX_TOOL_ITERATIONS",
                str(config.max_tool_iterations),
            )
        )
        config.max_cashflow_calls = int(
            os.getenv(
                "CLIENT_PROFILE_AGENT_MAX_CASHFLOW_CALLS",
                str(config.max_cashflow_calls),
            )
        )
        # Profile agent is cashflow-only; keep Neo calls disabled by default.
        config.max_neo_calls = int(
            os.getenv(
                "CLIENT_PROFILE_AGENT_MAX_NEO_CALLS",
                "0",
            )
        )
        _CLIENT_PROFILE_AGENT = build_client_profile_agent(config)
    return _CLIENT_PROFILE_AGENT


def _run_two_agent_step1_pipeline(
    profile_input: Dict[str, Any],
    advisor_request: str,
) -> Dict[str, Any]:
    """Run client-profile analysis first, then solution policy generation."""
    profile_agent = get_client_profile_agent()
    profile_result = profile_agent.analyze_client_profile(
        client_payload=profile_input,
        advisor_request=advisor_request,
    )
    profile_analysis = (
        profile_result.get("profile_analysis")
        if isinstance(profile_result.get("profile_analysis"), dict)
        else None
    )
    if profile_analysis is None:
        raise ValueError("Client profile agent returned invalid profile_analysis payload")

    # Stage-2 receives only Stage-1 output package.
    solution_payload = profile_analysis
    solution_agent = get_solution_agent()
    step1_result = solution_agent.generate_step1_policy_json(
        client_payload=solution_payload,
        advisor_request=advisor_request,
    )
    step1_result["client_profile_analysis"] = profile_analysis
    return step1_result


def _extract_financial_diagnoses(profile_analysis: Optional[Dict[str, Any]]) -> list[Dict[str, str]]:
    """Normalize profile-agent gaps into frontend card payloads.

    Includes all supported client-profile diagnosis categories for UI display.
    """
    if not isinstance(profile_analysis, dict):
        return []

    # Schema from client-profile agent: gaps_by_category.
    identified = profile_analysis.get("gaps_by_category")
    if not isinstance(identified, dict):
        return []

    def _find_items(source: Dict[str, Any], aliases: list[str]) -> list[Any]:
        for alias in aliases:
            candidate = source.get(alias)
            if isinstance(candidate, list):
                return candidate
            if isinstance(candidate, str) and candidate.strip() == "None":
                return []
        return []

    def _pick_text(row: Dict[str, Any], keys: list[str]) -> str:
        for key in keys:
            value = str(row.get(key, "") or "").strip()
            if value:
                return value
        return ""

    category_specs = [
        (
            "investment related",
            [
                "investment related",
                "investment_related",
            ],
        ),
        (
            "insurance related",
            ["insurance related", "insurance_related", "insurance"],
        ),
        (
            "spending related",
            ["spending related", "spending_related", "spending"],
        ),
        (
            "liability related",
            ["liability related", "liability_related", "liability", "debt"],
        ),
    ]

    cards: list[Dict[str, str]] = []
    for category, aliases in category_specs:
        entries = _find_items(identified, aliases)
        for index, entry in enumerate(entries):
            if isinstance(entry, dict):
                title = _pick_text(entry, ["gap", "title", "name"])
                description = _pick_text(entry, ["discussion", "description", "explanation", "summary"])
            elif isinstance(entry, str):
                title = entry.strip()
                description = entry.strip()
            else:
                title = ""
                description = ""
            if not title or not description:
                continue
            cards.append(
                {
                    "id": f"{category}-{index + 1}",
                    "category": category,
                    "title": title,
                    "description": description,
                }
            )

    return cards


def _parse_nonempty_json_body() -> Tuple[Optional[Dict[str, Any]], Optional[Tuple[Any, int]]]:
    """Parse and validate that request body is a non-empty JSON object."""
    body = request.get_json(silent=True) or {}
    if not isinstance(body, dict) or not body:
        return None, (jsonify({"success": False, "error": "Request JSON body is required"}), 400)
    return body, None


def _build_step1_result_from_body(
    body: Dict[str, Any]
) -> Tuple[Optional[Dict[str, Any]], Optional[Tuple[Any, int]]]:
    """Build step-1 policy result from request body using conversation-first Stage-1 context."""
    profile_input, advisor_request, error_response = _build_profile_agent_input_with_consultation_context(body)
    if error_response is not None:
        return None, error_response

    step1_result = _run_two_agent_step1_pipeline(
        profile_input=profile_input,
        advisor_request=advisor_request,
    )
    step1_policy = step1_result.get("step1_policy")
    if not isinstance(step1_policy, dict):
        return None, (
            jsonify({"success": False, "error": "Advisor returned invalid Step-1 policy payload"}),
            500,
        )
    return step1_result, None


def get_policy_ui_generator() -> PolicyUiGenerator:
    """Lazily initialize standalone UI policy transformer."""
    global _POLICY_UI_GENERATOR
    if _POLICY_UI_GENERATOR is None:
        config = AdvisorConfig.from_env()
        ui_stage = config.stage_models.get("policy_ui", {})
        _POLICY_UI_GENERATOR = PolicyUiGenerator(
            google_api_key=config.gemini_api_key,
            openai_api_key=config.openai_api_key,
            provider=str(ui_stage.get("primary_provider", "gemini")),
            model=str(ui_stage.get("primary_model", "models/gemini-3-pro-preview")),
            fallbacks=list(ui_stage.get("fallbacks", [])),
            llm_timeout_ms=config.llm_timeout_ms,
            prompts_dir=_REPO_ROOT / "policy_ui_transform" / "prompts",
        )
    return _POLICY_UI_GENERATOR


def require_api_key() -> Tuple[bool, Optional[Dict[str, Any]]]:
    """Validate optional advisor API key if configured."""
    configured_key = os.getenv("ADVISOR_API_KEY", "").strip()
    if not configured_key:
        return True, None

    received_key = request.headers.get("X-Api-Key", "").strip()
    if received_key != configured_key:
        return False, {"success": False, "error": "Invalid or missing advisor API key"}

    return True, None


def _get_elevenlabs_config() -> Tuple[str, str, str, str]:
    """Resolve ElevenLabs config from environment."""
    api_key = str(os.getenv("ELEVENLABS_API_KEY", "") or "").strip()
    base_url = str(os.getenv("ELEVENLABS_BASE_URL", "https://api.elevenlabs.io") or "").strip().rstrip("/")
    consultation_agent_id = str(
        os.getenv("ELEVENLABS_CONSULTATION_AGENT_ID", os.getenv("ELEVENLABS_INITIAL_AGENT_ID", "")) or ""
    ).strip()
    presentation_agent_id = str(
        os.getenv("ELEVENLABS_PRESENTATION_AGENT_ID", "") or ""
    ).strip()
    return api_key, base_url, consultation_agent_id, presentation_agent_id


def _create_elevenlabs_signed_url_response(agent_id: str, missing_agent_env_name: str) -> Tuple[Any, int]:
    """Create standardized signed-url response payload for a given ElevenLabs agent."""
    api_key, base_url, _, _ = _get_elevenlabs_config()
    if not api_key:
        return jsonify({"success": False, "error": "ELEVENLABS_API_KEY is not configured"}), 500
    if not agent_id:
        return jsonify({"success": False, "error": f"{missing_agent_env_name} is not configured"}), 500
    if not base_url:
        return jsonify({"success": False, "error": "ELEVENLABS_BASE_URL is not configured"}), 500

    signed_url_endpoint = f"{base_url}/v1/convai/conversation/get_signed_url"
    try:
        response = requests.get(
            signed_url_endpoint,
            params={"agent_id": agent_id},
            headers={"xi-api-key": api_key},
            timeout=20,
        )
    except requests.RequestException as exc:
        return (
            jsonify(
                {
                    "success": False,
                    "error": "Failed to reach ElevenLabs signed URL endpoint",
                    "details": str(exc),
                }
            ),
            502,
        )

    if response.status_code >= 400:
        error_body: Any
        try:
            error_body = response.json()
        except ValueError:
            error_body = response.text
        return (
            jsonify(
                {
                    "success": False,
                    "error": "ElevenLabs signed URL request failed",
                    "status_code": response.status_code,
                    "details": error_body,
                }
            ),
            502,
        )

    payload = response.json() if response.content else {}
    signed_url = str(payload.get("signed_url", "") or "").strip()
    if not signed_url:
        return (
            jsonify(
                {
                    "success": False,
                    "error": "ElevenLabs response did not include signed_url",
                    "details": payload,
                }
            ),
            502,
        )

    return (
        jsonify(
            {
                "success": True,
                "agent_id": agent_id,
                "signed_url": signed_url,
            }
        ),
        200,
    )


@app.route("/health", methods=["GET"])
def health() -> Any:
    """Service health endpoint."""
    config = AdvisorConfig.from_env()
    stage_rows = {
        stage: {
            "primary_provider": row.get("primary_provider"),
            "primary_model": row.get("primary_model"),
            "fallbacks": row.get("fallbacks", []),
        }
        for stage, row in config.stage_models.items()
    }
    return jsonify(
        {
            "status": "healthy",
            "service": "solution-agent-service",
            "llm_stages": stage_rows,
        }
    ), 200


@app.route("/advisor/api/v1/tool-health", methods=["GET"])
def tool_health() -> Any:
    """Check downstream tool connectivity."""
    ok, error = require_api_key()
    if not ok:
        return jsonify(error), 401

    try:
        solution_agent = get_solution_agent()
        status = solution_agent.check_tool_access()
        is_healthy = status["cashflow"]["ok"] and status["neo_engine"]["ok"]
        http_status = 200 if is_healthy else 503
        return jsonify({"success": is_healthy, "tool_health": status}), http_status
    except Exception as exc:  # pylint: disable=broad-except
        return (
            jsonify(
                {
                    "success": False,
                    "error": "Failed to run tool health check",
                    "details": str(exc),
                }
            ),
            500,
        )


@app.route("/advisor/api/v1/consultation-voice/signed-url", methods=["POST"])
def consultation_voice_signed_url() -> Any:
    """Create ElevenLabs signed URL for consultation voice session."""
    ok, error = require_api_key()
    if not ok:
        return jsonify(error), 401

    _, _, consultation_agent_id, _ = _get_elevenlabs_config()
    return _create_elevenlabs_signed_url_response(
        consultation_agent_id,
        "ELEVENLABS_CONSULTATION_AGENT_ID",
    )


@app.route("/advisor/api/v1/policy-voice/signed-url", methods=["POST"])
def policy_voice_signed_url() -> Any:
    """Create ElevenLabs signed URL for policy explanation voice session."""
    ok, error = require_api_key()
    if not ok:
        return jsonify(error), 401

    _, _, _, presentation_agent_id = _get_elevenlabs_config()
    return _create_elevenlabs_signed_url_response(
        presentation_agent_id,
        "ELEVENLABS_PRESENTATION_AGENT_ID",
    )


@app.route("/advisor/api/v1/generate-policy-json", methods=["POST"])
def generate_policy_json() -> Any:
    """Generate final UI policy JSON from Step-1 advisor policy + standalone UI transformation."""
    ok, error = require_api_key()
    if not ok:
        return jsonify(error), 401

    try:
        body, error_response = _parse_nonempty_json_body()
        if error_response is not None:
            return error_response

        step1_result, error_response = _build_step1_result_from_body(body)
        if error_response is not None:
            return error_response

        step1_policy = step1_result.get("step1_policy")

        ui_generator = get_policy_ui_generator()
        ui_result = ui_generator.generate_ui_policy_json(
            step1_policy=step1_policy,
            supporting_context={
                "tool_loop_model_used": step1_result.get("tool_loop_model_used"),
                "finalize_signal": step1_result.get("finalize_signal"),
                "portfolio": step1_result.get("portfolio"),
                "flat_securities": step1_result.get("flat_securities"),
            },
        )
        raw_ui_policy = ui_result.get("ui_policy")
        if not isinstance(raw_ui_policy, dict):
            return jsonify({"success": False, "error": "UI transformer returned invalid policy payload"}), 500

        normalization_securities = ui_result.get("normalization_securities")
        if not isinstance(normalization_securities, list):
            normalization_securities = step1_result.get("flat_securities", [])
        normalization_portfolio = ui_result.get("normalization_portfolio")
        if not isinstance(normalization_portfolio, dict):
            normalization_portfolio = step1_result.get("portfolio", {})

        solution_agent = get_solution_agent()
        final_policy = solution_agent.normalize_ui_policy_json(
            payload=raw_ui_policy,
            securities=normalization_securities,
            portfolio=normalization_portfolio,
        )
        ui_generation = ui_result.get("ui_generation")
        if isinstance(ui_generation, dict):
            final_policy["ui_generation"] = ui_generation

        fallback_diagnoses = ui_result.get("financial_diagnoses")
        if isinstance(fallback_diagnoses, list) and fallback_diagnoses:
            final_policy["financial_diagnoses"] = fallback_diagnoses
        else:
            final_policy["financial_diagnoses"] = _extract_financial_diagnoses(
                step1_result.get("client_profile_analysis")
            )

        return jsonify(final_policy), 200

    except ValueError as exc:
        return jsonify({"success": False, "error": str(exc)}), 400
    except Exception as exc:  # pylint: disable=broad-except
        return (
            jsonify(
                {
                    "success": False,
                    "error": "Advisor final policy generation failed",
                    "details": str(exc),
                }
            ),
            500,
        )


@app.route("/advisor/api/v1/generate-step1-policy-json", methods=["POST"])
def generate_step1_policy_json() -> Any:
    """Generate Step-1 policy JSON only (advisor policy generation output)."""
    ok, error = require_api_key()
    if not ok:
        return jsonify(error), 401

    try:
        body, error_response = _parse_nonempty_json_body()
        if error_response is not None:
            return error_response

        step1_result, error_response = _build_step1_result_from_body(body)
        if error_response is not None:
            return error_response

        return jsonify(step1_result["step1_policy"]), 200
    except ValueError as exc:
        return jsonify({"success": False, "error": str(exc)}), 400
    except Exception as exc:  # pylint: disable=broad-except
        return (
            jsonify(
                {
                    "success": False,
                    "error": "Advisor Step-1 policy generation failed",
                    "details": str(exc),
                }
            ),
            500,
        )


@app.route("/advisor/api/v1/consultation-ingest", methods=["POST"])
def consultation_ingest() -> Any:
    """Ingest structured consultation transcript for advisor preprocessing."""
    ok, error = require_api_key()
    if not ok:
        return jsonify(error), 401

    body = request.get_json() or {}
    if not isinstance(body, dict):
        return jsonify({"success": False, "error": "Request JSON body is required"}), 400

    session_id = str(body.get("session_id", "") or "").strip()
    turns = body.get("turns")
    language = str(body.get("language", "en") or "en").strip()

    if not session_id:
        return jsonify({"success": False, "error": "session_id is required"}), 400
    if not isinstance(turns, list):
        return jsonify({"success": False, "error": "turns must be a list"}), 400

    normalized_turns = []
    for idx, turn in enumerate(turns):
        if not isinstance(turn, dict):
            return jsonify({"success": False, "error": f"turns[{idx}] must be an object"}), 400

        speaker = str(turn.get("speaker", "") or "").strip()
        text = str(turn.get("text", "") or "").strip()
        ts_start_ms = turn.get("ts_start_ms")

        if speaker not in {"agent", "client", "system"}:
            return jsonify({"success": False, "error": f"turns[{idx}].speaker is invalid"}), 400
        if not text:
            continue
        if not isinstance(ts_start_ms, (int, float)):
            return jsonify({"success": False, "error": f"turns[{idx}].ts_start_ms must be numeric"}), 400

        normalized_turns.append(
            {
                "speaker": speaker,
                "text": text,
                "ts_start_ms": int(ts_start_ms),
                "ts_end_ms": int(turn.get("ts_end_ms")) if isinstance(turn.get("ts_end_ms"), (int, float)) else None,
            }
        )

    agent_utterances = [t["text"] for t in normalized_turns if t["speaker"] == "agent"]

    ingest_id = str(uuid.uuid4())
    ingest_payload = {
        "ingest_id": ingest_id,
        "session_id": session_id,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "transcript": {
            "session_id": session_id,
            "started_at": body.get("started_at"),
            "ended_at": body.get("ended_at"),
            "completion_reason": body.get("completion_reason"),
            "turns": normalized_turns,
            "metadata": body.get("metadata", {}),
            "language": language,
        },
        "agent_preview": {
            "last_agent_message": agent_utterances[-1] if agent_utterances else "",
        },
    }
    with _INGEST_LOCK:
        _CONSULTATION_INGESTS[ingest_id] = ingest_payload
    try:
        _append_ingest_to_disk(ingest_payload)
    except OSError:
        # Keep response success even if persistence write fails.
        pass

    return (
        jsonify(
            {
                "success": True,
                "ingest_id": ingest_id,
            }
        ),
        200,
    )


@app.route("/advisor/api/v1/consultation-ingest/latest", methods=["GET"])
def consultation_ingest_latest() -> Any:
    """Fetch the latest ingested transcript payload."""
    ok, error = require_api_key()
    if not ok:
        return jsonify(error), 401

    latest_in_memory: Optional[Dict[str, Any]] = None
    with _INGEST_LOCK:
        ingests = list(_CONSULTATION_INGESTS.values())
    if ingests:
        latest_in_memory = max(
            ingests,
            key=lambda row: str(row.get("created_at", "") or ""),
        )

    latest = latest_in_memory
    if not latest:
        return jsonify({"success": False, "error": "No consultation ingests found"}), 404

    return jsonify({"success": True, "consultation_ingest": latest}), 200


@app.route("/advisor/api/v1/consultation-ingest/<ingest_id>", methods=["GET"])
def consultation_ingest_get(ingest_id: str) -> Any:
    """Fetch an ingested transcript payload by ingest ID."""
    ok, error = require_api_key()
    if not ok:
        return jsonify(error), 401

    ingest_id = str(ingest_id or "").strip()
    if not ingest_id:
        return jsonify({"success": False, "error": "ingest_id is required"}), 400

    payload = _get_ingested_consultation(ingest_id)
    if not payload:
        return jsonify({"success": False, "error": "consultation ingest not found"}), 404

    return jsonify({"success": True, "consultation_ingest": payload}), 200


if __name__ == "__main__":
    # Prefer an advisor-specific port to avoid colliding with the frontend server.
    port_str = os.getenv("ADVISOR_PORT")
    if not port_str:
        fallback_port = os.getenv("PORT", "").strip()
        port_str = fallback_port if fallback_port and fallback_port != "3000" else "8002"
    port = int(port_str) if port_str else 8002
    debug = os.getenv("FLASK_DEBUG", "false").lower() == "true"

    print(f"Starting solution-agent-service on port {port}")
    app.run(host="0.0.0.0", port=port, debug=debug)
