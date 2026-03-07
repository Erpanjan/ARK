"""
Advisor agent orchestration with Gemini function-calling.

The agent uses two HTTP tools:
1) Cashflow model API
2) Neo engine optimization API

Tool calls are intentionally constrained so the Neo tool only exposes:
- target_volatility
- active_risk_percentage

Risk profile and weight type are kept internal defaults.
"""

from __future__ import annotations

import copy
import hashlib
import hmac
import json
import os
import re
import sys
import time
from datetime import datetime, timezone
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import requests
from dotenv import dotenv_values

_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from shared.llm import (
    LLMClientFactory,
    LLMGenerateRequest,
    LLMMessage,
    ToolSchema,
    dedupe_model_chain,
    parse_fallback_chain,
)


REQUIRED_STEP1_POLICY_FIELDS: List[str] = [
    "policy_title",
    "executive_summary",
    "sections",
    "portfolio",
    "execution",
    "risk_framework",
    "evaluation_metrics",
    "fee_and_governance_notes",
    "disclaimer",
    "tool_execution_log",
]

STEP1_FORBIDDEN_UI_FIELDS: List[str] = ["menu", "detail"]

REQUIRED_STEP1_SECTION_TITLES: List[str] = [
    "Client Background",
    "Client Financial Snapshot",
    "Client Financial Needs",
    "Client Investment Preferences and Behavioral Considerations",
    "Taxes, Exclusions, and Exemptions",
    "Other Special Requirements",
    "Capital Deployment Timeline",
    "Portfolio Policy",
    "Investment Vehicle Selection Highlights",
    "Risk Management Framework",
    "Policy Evaluation Metrics",
    "Fee and Governance Notes",
    "Disclaimer and Acknowledgment",
    "Tool Execution Log",
]


@dataclass
class AdvisorConfig:
    """Runtime configuration for the advisor agent."""

    gemini_api_key: str
    openai_api_key: str = ""
    stage_models: Dict[str, Dict[str, Any]] = field(default_factory=dict)

    cashflow_api_url: str = "http://localhost:8001"
    cashflow_api_key: str = ""

    neo_api_url: str = "http://localhost:8000"
    neo_api_key: str = ""
    neo_default_risk_profile: str = "RP3"
    neo_default_weight_type: str = "dynamic"

    request_timeout_seconds: int = 180
    llm_timeout_ms: int = 90000
    max_tool_iterations: int = 6
    max_cashflow_calls: int = 6
    max_neo_calls: int = 6

    @classmethod
    def from_env(cls) -> "AdvisorConfig":
        """Build configuration from environment variables."""
        # Single source of truth for keys/settings: repo root .env.
        repo_root = Path(__file__).resolve().parent.parent
        root_env_path = repo_root / ".env"
        root_evn_path = repo_root / ".evn"
        root_env: Dict[str, str] = {}
        source_env_path = root_env_path if root_env_path.exists() else root_evn_path
        if source_env_path.exists():
            parsed = dotenv_values(source_env_path)
            root_env = {str(k): str(v or "") for k, v in parsed.items()}

        def _env(name: str) -> str:
            return (os.getenv(name, "").strip() or root_env.get(name, "").strip())

        gemini_key = (
            _env("GOOGLE_GENAI_API_KEY")
            or _env("GEMINI_API_KEY")
        )
        openai_key = _env("OPENAI_API_KEY")

        advisor_default_model = _env("ADVISOR_GEMINI_MODEL") or "models/gemini-3-pro-preview"
        advisor_legacy_fallbacks: List[Tuple[str, str]] = []
        legacy_fallback_raw = _env("ADVISOR_GEMINI_FALLBACK_MODELS")
        if legacy_fallback_raw:
            advisor_legacy_fallbacks = [("gemini", m.strip()) for m in legacy_fallback_raw.split(",") if m.strip()]

        def _stage_model_config(
            stage_name: str,
            provider_key: str,
            model_key: str,
            fallback_key: str,
            legacy_model_key: str = "",
            default_provider: str = "gemini",
            default_model: str = "",
            legacy_fallbacks: Optional[List[Tuple[str, str]]] = None,
        ) -> Dict[str, Any]:
            provider = _env(provider_key).lower() or default_provider
            model = _env(model_key)
            if not model and legacy_model_key:
                model = _env(legacy_model_key)
            if not model:
                model = default_model
            fallback_raw = _env(fallback_key)
            fallbacks = parse_fallback_chain(fallback_raw) if fallback_raw else (legacy_fallbacks or [])
            chain = dedupe_model_chain((provider, model), fallbacks)
            if not chain:
                raise ValueError(f"No model chain configured for {stage_name}")
            return {
                "primary_provider": chain[0][0],
                "primary_model": chain[0][1],
                "fallbacks": chain[1:],
                "chain": chain,
            }

        stage_models = {
            "client_profile_tool_loop": _stage_model_config(
                stage_name="client_profile_tool_loop",
                provider_key="CLIENT_PROFILE_TOOL_LOOP_PROVIDER",
                model_key="CLIENT_PROFILE_TOOL_LOOP_MODEL",
                fallback_key="CLIENT_PROFILE_TOOL_LOOP_FALLBACKS",
                legacy_model_key="ADVISOR_GEMINI_MODEL",
                default_model=advisor_default_model,
                legacy_fallbacks=advisor_legacy_fallbacks,
            ),
            "client_profile_synthesis": _stage_model_config(
                stage_name="client_profile_synthesis",
                provider_key="CLIENT_PROFILE_SYNTHESIS_PROVIDER",
                model_key="CLIENT_PROFILE_SYNTHESIS_MODEL",
                fallback_key="CLIENT_PROFILE_SYNTHESIS_FALLBACKS",
                legacy_model_key="ADVISOR_GEMINI_MODEL",
                default_model=advisor_default_model,
                legacy_fallbacks=advisor_legacy_fallbacks,
            ),
            "solution_tool_loop": _stage_model_config(
                stage_name="solution_tool_loop",
                provider_key="SOLUTION_TOOL_LOOP_PROVIDER",
                model_key="SOLUTION_TOOL_LOOP_MODEL",
                fallback_key="SOLUTION_TOOL_LOOP_FALLBACKS",
                legacy_model_key="ADVISOR_GEMINI_MODEL",
                default_model=advisor_default_model,
                legacy_fallbacks=advisor_legacy_fallbacks,
            ),
            "solution_synthesis": _stage_model_config(
                stage_name="solution_synthesis",
                provider_key="SOLUTION_SYNTHESIS_PROVIDER",
                model_key="SOLUTION_SYNTHESIS_MODEL",
                fallback_key="SOLUTION_SYNTHESIS_FALLBACKS",
                legacy_model_key="ADVISOR_GEMINI_MODEL",
                default_model=advisor_default_model,
                legacy_fallbacks=advisor_legacy_fallbacks,
            ),
            "policy_ui": _stage_model_config(
                stage_name="policy_ui",
                provider_key="POLICY_UI_PROVIDER",
                model_key="POLICY_UI_MODEL",
                fallback_key="POLICY_UI_FALLBACKS",
                legacy_model_key="ADVISOR_UI_GEMINI_MODEL",
                default_model=_env("ADVISOR_UI_GEMINI_MODEL") or advisor_default_model,
                legacy_fallbacks=advisor_legacy_fallbacks,
            ),
        }

        neo_api_url = (
            _env("NEOENGINE_API_URL")
            or _env("PYTHON_NEO_ENGINE_URL")
            or "http://localhost:8000"
        )
        explicit_neo_api_key = (
            _env("NEOENGINE_API_KEY")
            or _env("NEO_ENGINE_API_KEY")
        )
        neo_api_secret = (
            _env("NEO_API_SECRET")
            or _env("API_SECRET")
        )
        # Prefer HMAC-derived key when a shared secret is available so advisor and
        # Neo remain aligned even if a stale explicit key exists in env.
        if neo_api_secret:
            neo_api_key = hmac.new(
                neo_api_secret.encode("utf-8"), b"api_key", hashlib.sha256
            ).hexdigest()
        elif explicit_neo_api_key:
            neo_api_key = explicit_neo_api_key
        else:
            neo_api_key = ""
        cashflow_api_url = (
            _env("CASHFLOW_API_URL")
            or _env("CASHFLOW_MODEL_URL")
            or "http://localhost:8001"
        )

        return cls(
            gemini_api_key=gemini_key,
            openai_api_key=openai_key,
            stage_models=stage_models,
            cashflow_api_url=cashflow_api_url.rstrip("/"),
            cashflow_api_key=_env("CASHFLOW_API_KEY"),
            neo_api_url=neo_api_url.rstrip("/"),
            neo_api_key=neo_api_key,
            neo_default_risk_profile=_env("NEOENGINE_DEFAULT_RISK_PROFILE") or "RP3",
            neo_default_weight_type=_env("NEOENGINE_DEFAULT_WEIGHT_TYPE") or "dynamic",
            request_timeout_seconds=int(_env("ADVISOR_REQUEST_TIMEOUT_SECONDS") or "180"),
            llm_timeout_ms=int(_env("ADVISOR_LLM_TIMEOUT_MS") or _env("ADVISOR_GEMINI_TIMEOUT_MS") or "90000"),
            max_tool_iterations=int(_env("ADVISOR_MAX_TOOL_ITERATIONS") or "6"),
            max_cashflow_calls=int(_env("ADVISOR_MAX_CASHFLOW_CALLS") or "6"),
            max_neo_calls=int(_env("ADVISOR_MAX_NEO_CALLS") or "6"),
        )


@dataclass
class AgentState:
    """State persisted during a single advisor run."""

    latest_cashflow_full: Optional[Dict[str, Any]] = None

    latest_neo_full: Optional[Dict[str, Any]] = None
    latest_neo_allocation: Optional[Dict[str, float]] = None

    cashflow_call_count: int = 0
    neo_call_count: int = 0

    tool_audit: List[Dict[str, Any]] = field(default_factory=list)
    tool_call_sequence: int = 0
    tool_call_order: List[str] = field(default_factory=list)
    latest_tool_call_id: Optional[str] = None
    raw_tool_outputs_by_call: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    tool_summaries_by_call: Dict[str, Dict[str, Any]] = field(default_factory=dict)


class AdvisorAgent:
    """Financial advisor agent that coordinates tool calls via configured LLM providers."""

    def __init__(self, config: AdvisorConfig, prompts_dir: Path):
        self.config = config
        self.prompts_dir = prompts_dir
        self._validate_provider_keys()
        # Temporary prompt logging to inspect exact Gemini request contexts.
        self._prompt_log_enabled = os.getenv("ADVISOR_TEMP_LOG_PROMPTS", "true").strip().lower() not in {
            "0",
            "false",
            "no",
            "off",
        }
        self._prompt_log_path = Path(
            os.getenv(
                "ADVISOR_TEMP_PROMPT_LOG_PATH",
                str(Path(__file__).resolve().parent / "logs" / "gemini_prompt_debug.ndjson"),
            )
        )

    def _validate_provider_keys(self) -> None:
        """Validate API-key availability for configured stage providers."""
        providers: set[str] = set()
        for row in self.config.stage_models.values():
            for provider_name, _ in row.get("chain", []):
                providers.add(str(provider_name or "").strip().lower())
        if "gemini" in providers and not self.config.gemini_api_key:
            raise ValueError(
                "Gemini stage configured but Gemini API key is missing "
                "(set GOOGLE_GENAI_API_KEY or GEMINI_API_KEY)"
            )
        if "openai" in providers and not self.config.openai_api_key:
            raise ValueError(
                "OpenAI stage configured but OPENAI_API_KEY is missing"
            )

    def generate_step1_policy_json(
        self,
        client_payload: Dict[str, Any],
        advisor_request: str = "",
    ) -> Dict[str, Any]:
        """Run the full tool-enabled advisor workflow and return Step-1 policy JSON."""
        self._validate_client_payload(client_payload)

        loop_result = self._run_tool_loop(
            client_payload=client_payload,
            advisor_request=advisor_request,
        )
        state = loop_result["state"]

        portfolio, flat_securities, neo_snapshot = self._extract_portfolio_context_from_state(
            state=state,
            client_payload=client_payload,
        )
        context = {
            "client_payload": client_payload,
            "advisor_request": advisor_request,
            "tool_memory": self._build_tool_memory_context(state),
            "tool_audit": state.tool_audit,
            "finalize_signal": loop_result.get("finalize_signal"),
            "neo_snapshot": neo_snapshot,
            "currency": portfolio.get("currency", "USD"),
            "total_transfer": portfolio.get("total_value"),
            "securities": flat_securities,
        }

        prompt_template = self._read_prompt("core_policy_prompt.txt")
        user_prompt = (
            f"{prompt_template}\n\n"
            "Use this JSON context as source-of-truth:\n"
            f"{json.dumps(context, indent=2, ensure_ascii=True)}"
        )

        response, model_used, provider_used = self._generate_with_fallback(
            stage_name="solution_synthesis",
            messages=[LLMMessage(role="user", content=user_prompt)],
            system_instruction=(
                "You are a senior financial planner. Produce one JSON object only."
            ),
            use_tools=False,
            temperature=0.2,
        )

        raw_text = response.text.strip()

        step1_policy = self._parse_json_object(raw_text)
        self._validate_step1_policy_schema(step1_policy)

        return {
            "success": True,
            "model_used": model_used,
            "provider_used": provider_used,
            "step1_policy": step1_policy,
            "context": context,
            "portfolio": portfolio,
            "flat_securities": flat_securities,
            "tool_loop_model_used": loop_result.get("model_used", "unknown"),
            "tool_loop_provider_used": loop_result.get("provider_used", "unknown"),
            "finalize_signal": loop_result.get("finalize_signal"),
        }

    def normalize_ui_policy_json(
        self,
        payload: Dict[str, Any],
        securities: List[Dict[str, Any]],
        portfolio: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Public wrapper to normalize UI payload into frontend final-policy contract."""
        return self._normalize_final_policy_json(payload, securities, portfolio)

    def _run_tool_loop(
        self,
        client_payload: Dict[str, Any],
        advisor_request: str,
    ) -> Dict[str, Any]:
        """Run the ReAct-style tool loop using agent_system instructions."""
        state = AgentState()
        conversation: List[LLMMessage] = [
            LLMMessage(
                role="user",
                content=self._build_initial_prompt(client_payload, advisor_request),
            )
        ]
        finalize_signal: Optional[Dict[str, Any]] = None
        model_used = "unknown"
        provider_used = "unknown"

        for iteration in range(1, self.config.max_tool_iterations + 1):
            response, model_used, provider_used = self._generate_with_fallback(
                stage_name=self._tool_loop_stage_name(),
                messages=conversation,
                system_instruction=self._read_prompt("agent_system.txt"),
                use_tools=True,
                temperature=0.2,
            )
            if response.messages:
                conversation.extend(response.messages)

            response_texts = [response.text] if response.text else []
            function_calls = response.tool_calls
            self._log_debug(
                f"Tool loop iteration={iteration} function_calls={len(function_calls)}"
            )

            if function_calls:
                for function_call in function_calls:
                    function_name = str(function_call.name or "").strip()
                    canonical_name = self._canonical_tool_name(function_name)
                    result, call_id = self._execute_tool_call(
                        function_name=function_name,
                        raw_args=function_call.arguments,
                        client_payload=client_payload,
                        state=state,
                        iteration=iteration,
                    )
                    self._log_debug(
                        "Tool call executed "
                        f"iteration={iteration} call_id={call_id} name={function_name} "
                        f"success={bool(result.get('success', False))}"
                    )
                    function_payload = self._build_function_response_payload(
                        function_name=canonical_name,
                        call_id=call_id,
                        state=state,
                    )
                    conversation.append(
                        LLMMessage(
                            role="tool",
                            name=canonical_name,
                            tool_call_id=function_call.id or call_id,
                            content=json.dumps(function_payload, ensure_ascii=True),
                        )
                    )
                continue

            finalize_signal = self._extract_finalize_signal(response_texts)
            if finalize_signal is not None:
                if not self._has_post_optimize_cashflow_validation(state):
                    self._log_debug(
                        "Finalize blocked: required optimizePortfolio call/validation conditions not met."
                    )
                    if iteration < self.config.max_tool_iterations:
                        has_successful_optimize = any(
                            str(call.get("tool", "")).strip() == "optimizePortfolio"
                            and bool(call.get("success", False))
                            for call in state.tool_audit
                        )
                        reminder_text = (
                            "Constraint reminder: before finalizing, run one successful runCashflowModel "
                            "validation."
                        )
                        if has_successful_optimize:
                            reminder_text = (
                                "Constraint reminder: optimizePortfolio has already run. "
                                "Before finalizing, run one successful runCashflowModel "
                                "validation using post-optimize assumptions/allocation."
                            )
                        conversation.append(
                            LLMMessage(
                                role="user",
                                content=reminder_text,
                            )
                        )
                        finalize_signal = None
                        continue
                self._log_debug(
                    "Finalize signal detected "
                    f"iteration={iteration} action={finalize_signal.get('action')}"
                )
                break

        if finalize_signal is None:
            finalize_signal = {
                "action": "finalize",
                "analysis": "No explicit finalize signal before iteration cap; proceeding with strongest available synthesis from validated evidence.",
                "reason": "iteration_cap",
            }
            self._log_debug(
                "Tool loop reached iteration cap without explicit finalize; using fallback finalize signal."
            )

        return {
            "state": state,
            "finalize_signal": finalize_signal,
            "model_used": model_used,
            "provider_used": provider_used,
        }

    def _extract_finalize_signal(self, texts: List[str]) -> Optional[Dict[str, Any]]:
        """Extract the model's finalize action payload from text parts."""
        for text in texts:
            parsed = self._try_parse_json_object(text)
            if not isinstance(parsed, dict):
                continue
            if str(parsed.get("action", "")).strip().lower() == "finalize":
                return parsed
        return None

    def _has_post_optimize_cashflow_validation(self, state: AgentState) -> bool:
        """Return True when finalize is allowed under optimize->cashflow validation gate."""
        has_any_successful_cashflow = any(
            str(call.get("tool", "")).strip() == "runCashflowModel"
            and bool(call.get("success", False))
            for call in state.tool_audit
        )
        # Always require at least one successful cashflow validation before finalize.
        if not has_any_successful_cashflow:
            return False

        last_optimize_success_idx = -1
        for idx, call in enumerate(state.tool_audit):
            if (
                str(call.get("tool", "")).strip() == "optimizePortfolio"
                and bool(call.get("success", False))
            ):
                last_optimize_success_idx = idx

        if last_optimize_success_idx < 0:
            return True

        for idx in range(last_optimize_success_idx + 1, len(state.tool_audit)):
            call = state.tool_audit[idx]
            if (
                str(call.get("tool", "")).strip() == "runCashflowModel"
                and bool(call.get("success", False))
            ):
                return True
        return False

    def _try_parse_json_object(self, raw_text: str) -> Optional[Dict[str, Any]]:
        """Best-effort JSON object parsing that never raises."""
        text = str(raw_text or "").strip()
        if not text:
            return None
        try:
            parsed = json.loads(text)
            if isinstance(parsed, dict):
                return parsed
        except json.JSONDecodeError:
            pass

        start = text.find("{")
        end = text.rfind("}")
        if start >= 0 and end > start:
            candidate = text[start : end + 1]
            try:
                parsed = json.loads(candidate)
                if isinstance(parsed, dict):
                    return parsed
            except json.JSONDecodeError:
                return None
        return None

    def _extract_portfolio_context_from_state(
        self,
        state: AgentState,
        client_payload: Dict[str, Any],
    ) -> Tuple[Dict[str, Any], List[Dict[str, Any]], Dict[str, Any]]:
        """Build normalized portfolio + security context from latest Neo outputs when available."""
        neo_full = state.latest_neo_full if isinstance(state.latest_neo_full, dict) else {}
        securities = neo_full.get("securities") if isinstance(neo_full, dict) else None

        flat_securities: List[Dict[str, Any]] = []
        total_investment = neo_full.get("total_investment") if isinstance(neo_full, dict) else None
        if isinstance(securities, list):
            for idx, sec in enumerate(securities):
                if not isinstance(sec, dict):
                    continue
                security_name = str(sec.get("security_name", "") or "").strip() or str(
                    sec.get("isin", "") or ""
                ).strip()
                if not security_name:
                    continue
                weight = sec.get("weight")
                allocation_pct = float(weight) if isinstance(weight, (int, float)) else 0.0
                if allocation_pct <= 1.0:
                    allocation_pct *= 100.0
                allocation_pct = max(0.0, min(100.0, allocation_pct))

                raw_amount = sec.get("amount")
                if isinstance(raw_amount, (int, float)):
                    allocation_amount = max(0.0, float(raw_amount))
                elif isinstance(total_investment, (int, float)) and float(total_investment) > 0:
                    allocation_amount = (allocation_pct / 100.0) * float(total_investment)
                else:
                    allocation_amount = 0.0

                style = str(sec.get("security_type", "") or "").strip().lower()
                management_style = "active" if style == "active" else "passive"
                sec_id = str(sec.get("isin", "") or "").strip() or f"sec_{idx + 1}"

                flat_securities.append(
                    {
                        "id": sec_id,
                        "name": security_name,
                        "allocation_pct": round(allocation_pct, 2),
                        "allocation_amount": round(allocation_amount, 2),
                        "management_style": management_style,
                        "asset_class": str(sec.get("asset_class", "") or "").strip(),
                    }
                )

        if not flat_securities:
            total_from_payload = self._estimate_total_investment(client_payload)
            portfolio_fallback = {
                "currency": "USD",
                "total_value": total_from_payload if total_from_payload > 0 else None,
            }
            return portfolio_fallback, [], {"source": "no_neo_output"}

        normalized_total = None
        if isinstance(total_investment, (int, float)) and float(total_investment) > 0:
            normalized_total = round(float(total_investment), 2)
        elif flat_securities:
            normalized_total = round(
                sum(float(sec.get("allocation_amount", 0.0) or 0.0) for sec in flat_securities),
                2,
            )

        portfolio = {
            "currency": "USD",
            "total_value": normalized_total if normalized_total and normalized_total > 0 else None,
        }
        neo_snapshot = {
            "source": "neo",
            "portfolio_expected_return_pct": neo_full.get("portfolio_expected_return_pct"),
            "portfolio_expected_volatility_pct": neo_full.get("portfolio_expected_volatility_pct"),
        }
        return portfolio, flat_securities, neo_snapshot

    def _validate_step1_policy_schema(self, payload: Dict[str, Any]) -> None:
        """Validate the required Step-1 policy schema fields."""
        missing = [field for field in REQUIRED_STEP1_POLICY_FIELDS if field not in payload]
        if missing:
            raise ValueError(
                f"Step-1 policy JSON missing required fields: {', '.join(missing)}"
            )
        forbidden_fields = [field for field in STEP1_FORBIDDEN_UI_FIELDS if field in payload]
        if forbidden_fields:
            raise ValueError(
                f"Step-1 policy JSON must not contain UI fields: {', '.join(forbidden_fields)}"
            )

        sections = payload.get("sections")
        if not isinstance(sections, list) or not sections:
            raise ValueError("Step-1 policy JSON requires a non-empty sections array")
        section_titles: List[str] = []
        for idx, section in enumerate(sections):
            if not isinstance(section, dict):
                raise ValueError(f"sections[{idx}] must be an object")
            title = str(section.get("title", "") or "").strip()
            if not title:
                raise ValueError(f"sections[{idx}].title is required")
            if not str(section.get("content", "") or "").strip():
                raise ValueError(f"sections[{idx}].content is required")
            section_titles.append(title)

        if len(section_titles) != len(REQUIRED_STEP1_SECTION_TITLES):
            raise ValueError(
                "Step-1 policy JSON must contain exactly 14 sections in required order"
            )
        if section_titles != REQUIRED_STEP1_SECTION_TITLES:
            raise ValueError(
                "Step-1 policy JSON sections are not in the required order/title contract"
            )

        portfolio = payload.get("portfolio")
        if not isinstance(portfolio, dict):
            raise ValueError("Step-1 policy JSON requires portfolio object")
        recommended = portfolio.get("recommended_securities")
        if not isinstance(recommended, list):
            raise ValueError("Step-1 policy JSON requires portfolio.recommended_securities array")

        execution = payload.get("execution")
        if not isinstance(execution, dict):
            raise ValueError("Step-1 policy JSON requires execution object")
        for execution_field in ["remedy_name", "funding_source", "capital_deployment_timeline"]:
            if not str(execution.get(execution_field, "") or "").strip():
                raise ValueError(f"execution.{execution_field} is required")

    def _log_debug(self, message: str) -> None:
        """Lightweight internal logging helper."""
        print(f"[advisor-agent] {message}")

    def check_tool_access(self) -> Dict[str, Dict[str, Any]]:
        """Validate that both tool services are reachable."""
        cashflow_health = self._probe_health(
            f"{self.config.cashflow_api_url}/health",
            headers=self._build_cashflow_headers(),
        )
        neo_health = self._probe_health(
            f"{self.config.neo_api_url}/health",
            headers=self._build_neo_headers(),
        )

        # Neo optimize endpoint is authenticated in this stack.
        neo_health["api_key_configured"] = bool(self.config.neo_api_key)
        if not neo_health["api_key_configured"]:
            neo_health["ok"] = False
            neo_health["error"] = "NEOENGINE_API_KEY is not configured"

        return {
            "cashflow": cashflow_health,
            "neo_engine": neo_health,
        }

    def _probe_health(self, url: str, headers: Dict[str, str]) -> Dict[str, Any]:
        """Probe a service health endpoint and return a normalized status payload."""
        try:
            response = requests.get(
                url,
                headers=headers,
                timeout=min(15, self.config.request_timeout_seconds),
            )
            ok = response.status_code == 200
            payload: Dict[str, Any] = {"ok": ok, "status_code": response.status_code}

            try:
                payload["response"] = response.json()
            except ValueError:
                payload["response"] = response.text[:300]
            return payload
        except Exception as exc:  # pylint: disable=broad-except
            return {
                "ok": False,
                "status_code": None,
                "error": str(exc),
            }

    def _generate_with_fallback(
        self,
        stage_name: str,
        messages: List[LLMMessage],
        system_instruction: str,
        use_tools: bool,
        temperature: float,
    ) -> Tuple[Any, str, str]:
        """Generate model output using stage-configured provider/model fallback chain."""
        stage_config = self.config.stage_models.get(stage_name, {})
        model_candidates = stage_config.get("chain", [])
        if not model_candidates:
            raise RuntimeError(f"LLM generation failed: no model candidates configured for stage {stage_name}")

        last_error: Optional[Exception] = None

        for provider_name, model_name in model_candidates:
            try:
                self._append_prompt_log(
                    {
                        "stage": stage_name,
                        "timestamp": datetime.now(timezone.utc).isoformat(),
                        "provider": provider_name,
                        "model": model_name,
                        "system_instruction": system_instruction,
                        "use_tools": use_tools,
                        "temperature": temperature,
                        "contents": self._serialize_messages(messages),
                    }
                )
                adapter = LLMClientFactory.create(
                    provider=provider_name,
                    google_api_key=self.config.gemini_api_key,
                    openai_api_key=self.config.openai_api_key,
                    timeout_ms=self.config.llm_timeout_ms,
                )
                request = LLMGenerateRequest(
                    messages=messages,
                    system_instruction=system_instruction,
                    temperature=temperature,
                    tools=self._tool_declaration() if use_tools else [],
                )
                response = adapter.generate(request=request, model=model_name)
                return response, model_name, provider_name
            except Exception as exc:  # pylint: disable=broad-except
                last_error = exc
                message = str(exc)

                # Retry same model briefly when rate-limited.
                if "429" in message or "RESOURCE_EXHAUSTED" in message:
                    time.sleep(4)
                    continue

                # Move to fallback model if the requested model is unavailable.
                if "404" in message or "NOT_FOUND" in message:
                    continue

                # Fail fast for unexpected errors.
                break

        raise RuntimeError(f"LLM generation failed: {last_error}")

    def _append_prompt_log(self, payload: Dict[str, Any]) -> None:
        """Append prompt-debug payload as NDJSON; never raise to caller."""
        if not self._prompt_log_enabled:
            return
        try:
            self._prompt_log_path.parent.mkdir(parents=True, exist_ok=True)
            with self._prompt_log_path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(payload, ensure_ascii=True, default=str) + "\n")
        except OSError:
            # Temporary diagnostics should never break advisor execution.
            pass

    def _serialize_messages(self, messages: List[LLMMessage]) -> List[Dict[str, Any]]:
        """Serialize normalized request messages into JSON-safe dicts for debug logs."""
        serialized: List[Dict[str, Any]] = []
        for message in messages:
            row: Dict[str, Any] = {
                "role": str(message.role or ""),
                "content": str(message.content or ""),
            }
            if message.name:
                row["name"] = message.name
            if message.tool_call_id:
                row["tool_call_id"] = message.tool_call_id
            if message.tool_calls:
                row["tool_calls"] = [
                    {
                        "id": call.id,
                        "name": call.name,
                        "arguments": self._safe_jsonable(call.arguments),
                    }
                    for call in message.tool_calls
                ]
            serialized.append(row)
        return serialized

    def _safe_jsonable(self, value: Any) -> Any:
        """Convert potentially custom SDK values to JSON-safe structures."""
        if value is None or isinstance(value, (str, int, float, bool)):
            return value
        if isinstance(value, list):
            return [self._safe_jsonable(v) for v in value]
        if isinstance(value, tuple):
            return [self._safe_jsonable(v) for v in value]
        if isinstance(value, dict):
            return {str(k): self._safe_jsonable(v) for k, v in value.items()}
        if hasattr(value, "items"):
            try:
                return {str(k): self._safe_jsonable(v) for k, v in value.items()}
            except Exception:  # pylint: disable=broad-except
                return str(value)
        if hasattr(value, "__dict__"):
            try:
                return {
                    str(k): self._safe_jsonable(v)
                    for k, v in vars(value).items()
                    if not str(k).startswith("_")
                }
            except Exception:  # pylint: disable=broad-except
                return str(value)
        return str(value)

    def _next_tool_call_id(self, state: AgentState) -> str:
        """Return the next stable tool-call identifier."""
        state.tool_call_sequence += 1
        return f"t{state.tool_call_sequence}"

    def _build_function_response_payload(
        self,
        function_name: str,
        call_id: str,
        state: AgentState,
    ) -> Dict[str, Any]:
        """Return function response payload with compaction metadata."""
        payload: Dict[str, Any] = {
            "call_id": call_id,
            "tool_name": function_name,
            "source_call_id": call_id,
            "summary": state.tool_summaries_by_call.get(call_id, {}),
        }

        if call_id == state.latest_tool_call_id:
            payload["is_compacted"] = False
            payload["result"] = state.raw_tool_outputs_by_call.get(call_id, {})
        else:
            payload["is_compacted"] = True

        return payload

    def _build_tool_memory_context(self, state: AgentState) -> Dict[str, Any]:
        """Build compact tool memory for final policy generation."""
        summaries = [
            state.tool_summaries_by_call[call_id]
            for call_id in state.tool_call_order
            if call_id in state.tool_summaries_by_call
        ]
        latest_call_id = state.latest_tool_call_id
        latest_raw_call = None
        if latest_call_id:
            latest_raw_call = {
                "call_id": latest_call_id,
                "raw_result": state.raw_tool_outputs_by_call.get(latest_call_id),
                "summary": state.tool_summaries_by_call.get(latest_call_id),
            }

        return {
            "summary_schema": [
                "tool_name",
                "key_inputs",
                "key_metrics",
                "decision_relevance",
                "source_call_id",
            ],
            "tool_summaries": summaries,
            "latest_raw_call": latest_raw_call,
        }

    def _build_tool_summary(
        self,
        function_name: str,
        args: Dict[str, Any],
        result: Dict[str, Any],
        call_id: str,
    ) -> Dict[str, Any]:
        """Build deterministic compact summary for a tool result."""
        success = bool(result.get("success", False))
        key_inputs = self._summarize_tool_inputs(function_name, args)

        if function_name == "runCashflowModel":
            key_metrics = self._extract_cashflow_metrics(result)
            if not success:
                decision_relevance = "Cashflow simulation failed; fix error before strategy refinement."
            else:
                shortfall = key_metrics.get("goal_shortfall")
                if isinstance(shortfall, (int, float)):
                    if shortfall > 0:
                        decision_relevance = (
                            "Projected shortfall remains; adjust return target, contributions, or assumptions."
                        )
                    elif shortfall < 0:
                        decision_relevance = (
                            "Projection exceeds goal; confirm robustness with stress and scenario validation."
                        )
                    else:
                        decision_relevance = (
                            "Projection meets goal boundary; validate with risk and assumption checks."
                        )
                else:
                    decision_relevance = (
                        "Cashflow projection updated; use extracted metrics to evaluate goal feasibility."
                    )
        elif function_name == "optimizePortfolio":
            key_metrics = self._extract_neo_metrics(result)
            if not success:
                decision_relevance = "Portfolio optimization failed; resolve constraints or inputs."
            else:
                decision_relevance = (
                    "Candidate portfolio generated; validate impact with a follow-up cashflow simulation."
                )
        else:
            key_metrics = {}
            decision_relevance = "Tool result captured for traceability."

        return {
            "tool_name": function_name,
            "key_inputs": key_inputs,
            "key_metrics": key_metrics,
            "decision_relevance": decision_relevance,
            "source_call_id": call_id,
        }

    def _summarize_tool_inputs(self, function_name: str, args: Dict[str, Any]) -> Dict[str, Any]:
        """Return compact tool-input view for context memory."""
        if function_name == "runCashflowModel":
            payload_override = args.get("payload_override")
            payload_keys: List[str] = []
            if isinstance(payload_override, dict):
                payload_keys = sorted(str(k) for k in payload_override.keys())
            return {
                "simulation_mode": args.get("simulation_mode"),
                "num_simulations": args.get("num_simulations"),
                "seed": args.get("seed"),
                "use_latest_neo_allocation": args.get("use_latest_neo_allocation"),
                "bank_balance_override": args.get("bank_balance_override"),
                "investment_balance_override": args.get("investment_balance_override"),
                "payload_override_keys": payload_keys,
            }
        if function_name == "optimizePortfolio":
            return {
                "target_volatility": args.get("target_volatility"),
                "active_risk_percentage": args.get("active_risk_percentage"),
                "total_investment": args.get("total_investment"),
            }
        return dict(args)

    def _extract_cashflow_metrics(self, tool_result: Dict[str, Any]) -> Dict[str, Any]:
        """Extract stable cashflow metrics from tool response payload."""
        full_result = tool_result.get("full_result")
        if not isinstance(full_result, dict):
            return {
                "goal_shortfall": None,
                "goal_success_probability": None,
                "projected_terminal_value": None,
            }

        goal_shortfall = self._find_first_numeric_value(
            full_result,
            ["shortfall", "shortfall_median", "goal_shortfall"],
        )
        goal_success_probability = self._find_first_numeric_value(
            full_result,
            ["success_probability", "goal_achievement_rate", "achievement_rate"],
        )
        projected_terminal_value = self._find_first_numeric_value(
            full_result,
            [
                "projected_median",
                "projected_value",
                "terminal_wealth_median",
                "terminal_value",
                "ending_balance",
            ],
        )

        return {
            "goal_shortfall": goal_shortfall,
            "goal_success_probability": goal_success_probability,
            "projected_terminal_value": projected_terminal_value,
        }

    def _extract_neo_metrics(self, tool_result: Dict[str, Any]) -> Dict[str, Any]:
        """Extract stable Neo optimization metrics from tool response payload."""
        full_result = tool_result.get("full_result")
        if not isinstance(full_result, dict):
            return {
                "portfolio_expected_return": None,
                "portfolio_expected_volatility": None,
                "num_securities": 0,
                "top_allocations": [],
            }

        securities = full_result.get("securities")
        top_allocations: List[Dict[str, Any]] = []
        if isinstance(securities, list):
            ranked = [
                sec for sec in securities
                if isinstance(sec, dict) and isinstance(sec.get("weight"), (int, float))
            ]
            ranked.sort(key=lambda sec: float(sec.get("weight", 0.0)), reverse=True)
            for sec in ranked[:5]:
                top_allocations.append(
                    {
                        "security_id": sec.get("isin"),
                        "security_name": sec.get("security_name"),
                        "allocation_pct": float(sec.get("weight", 0.0)) * 100.0,
                    }
                )

        return {
            "portfolio_expected_return": full_result.get("portfolio_expected_return_pct"),
            "portfolio_expected_volatility": full_result.get("portfolio_expected_volatility_pct"),
            "num_securities": len(securities) if isinstance(securities, list) else 0,
            "top_allocations": top_allocations,
        }

    def _find_first_numeric_value(self, payload: Any, key_candidates: List[str]) -> Optional[float]:
        """Depth-first search for the first numeric value with one of the candidate keys."""
        if isinstance(payload, dict):
            for key in key_candidates:
                value = payload.get(key)
                if isinstance(value, (int, float)):
                    return float(value)
            for value in payload.values():
                found = self._find_first_numeric_value(value, key_candidates)
                if found is not None:
                    return found
            return None

        if isinstance(payload, list):
            for item in payload:
                found = self._find_first_numeric_value(item, key_candidates)
                if found is not None:
                    return found
            return None

        return None

    def _canonical_tool_name(self, function_name: str) -> str:
        """Map legacy and prompt-level tool names to canonical internal names."""
        normalized = str(function_name or "").strip()
        mapping = {
            "runCashflowModel": "runCashflowModel",
            "run_cashflow_model": "runCashflowModel",
            "optimizePortfolio": "optimizePortfolio",
            "run_neo_engine": "optimizePortfolio",
        }
        return mapping.get(normalized, normalized)

    def _execute_tool_call(
        self,
        function_name: str,
        raw_args: Any,
        client_payload: Dict[str, Any],
        state: AgentState,
        iteration: int,
    ) -> Tuple[Dict[str, Any], str]:
        """Dispatch and execute a single tool call."""
        canonical_name = self._canonical_tool_name(function_name)
        args = self._normalize_args(raw_args)

        if canonical_name == "runCashflowModel":
            if state.cashflow_call_count >= self.config.max_cashflow_calls:
                result = {
                    "success": False,
                    "error": (
                        "Cashflow tool call limit reached "
                        f"({self.config.max_cashflow_calls})."
                    ),
                }
            else:
                state.cashflow_call_count += 1
                result = self._tool_run_cashflow_model(args, client_payload, state)
        elif canonical_name == "optimizePortfolio":
            if "total_investment" not in args:
                estimated = self._estimate_total_investment(client_payload)
                if estimated > 0:
                    args["total_investment"] = float(estimated)
            if state.neo_call_count >= self.config.max_neo_calls:
                result = {
                    "success": False,
                    "error": (
                        "Neo tool call limit reached "
                        f"({self.config.max_neo_calls})."
                    ),
                }
            else:
                state.neo_call_count += 1
                result = self._tool_run_neo_engine(args, state)
        else:
            result = {"success": False, "error": f"Unknown tool: {function_name}"}

        call_id = self._next_tool_call_id(state)
        state.latest_tool_call_id = call_id
        state.tool_call_order.append(call_id)
        state.raw_tool_outputs_by_call[call_id] = copy.deepcopy(result)

        summary = self._build_tool_summary(
            function_name=canonical_name,
            args=args,
            result=result,
            call_id=call_id,
        )
        state.tool_summaries_by_call[call_id] = summary

        state.tool_audit.append(
            {
                "iteration": iteration,
                "call_id": call_id,
                "tool": canonical_name,
                "args": args,
                "success": bool(result.get("success", False)),
                "summary": summary,
                "source_call_id": call_id,
            }
        )
        return result, call_id

    def _tool_run_cashflow_model(
        self,
        args: Dict[str, Any],
        client_payload: Dict[str, Any],
        state: AgentState,
    ) -> Dict[str, Any]:
        """Execute numeric cashflow simulation tool call."""
        payload = copy.deepcopy(self._resolve_cashflow_payload(client_payload))

        # Allows the model to control all account types and any nested inputs.
        payload_override = args.get("payload_override")
        if isinstance(payload_override, dict):
            payload = self._deep_merge(payload, payload_override)

        mode = str(args.get("simulation_mode") or "deterministic")
        num_simulations = int(args.get("num_simulations") or 500)
        seed = args.get("seed")
        return_individual_runs = args.get("return_individual_runs")
        num_individual_runs = args.get("num_individual_runs")

        payload.setdefault("simulation_config", {})
        payload["simulation_config"]["mode"] = mode
        payload["simulation_config"]["num_simulations"] = num_simulations
        if seed is not None:
            payload["simulation_config"]["seed"] = int(seed)
        if return_individual_runs is not None:
            payload["simulation_config"]["return_individual_runs"] = bool(return_individual_runs)
        if num_individual_runs is not None:
            payload["simulation_config"]["num_individual_runs"] = int(num_individual_runs)

        use_latest_neo_allocation = bool(args.get("use_latest_neo_allocation", False))
        if use_latest_neo_allocation and state.latest_neo_allocation:
            payload["asset_allocation"] = state.latest_neo_allocation

        bank_balance_override = args.get("bank_balance_override")
        investment_balance_override = args.get("investment_balance_override")
        if bank_balance_override is not None:
            payload.setdefault("accounts", {}).setdefault("bank", {})["balance"] = float(
                bank_balance_override
            )
        if investment_balance_override is not None:
            payload.setdefault("accounts", {}).setdefault("brokerage", {})[
                "balance"
            ] = float(investment_balance_override)

        url = f"{self.config.cashflow_api_url}/cashflow/api/v1/simulate"

        response = requests.post(
            url,
            json=payload,
            headers=self._build_cashflow_headers(),
            timeout=self.config.request_timeout_seconds,
        )

        if response.status_code != 200:
            return {
                "success": False,
                "error": "Cashflow API call failed",
                "status_code": response.status_code,
                "details": response.text[:600],
            }

        full_result = response.json()
        state.latest_cashflow_full = full_result

        return {
            "success": True,
            "full_result": full_result,
        }

    def _tool_run_neo_engine(
        self,
        args: Dict[str, Any],
        state: AgentState,
    ) -> Dict[str, Any]:
        """Execute Neo engine optimization tool call.

        Only target_volatility and active_risk_percentage are exposed to the model.
        risk_profile and weight_type stay internal defaults.
        """
        target_volatility = args.get("target_volatility")
        active_risk_percentage = args.get("active_risk_percentage")
        total_investment = args.get("total_investment")

        if target_volatility is None:
            return {"success": False, "error": "target_volatility is required"}
        # Default to fully passive when client active risk preference is not provided.
        if active_risk_percentage is None:
            active_risk_percentage = 0.0
        try:
            active_risk_percentage = float(active_risk_percentage)
        except (TypeError, ValueError):
            return {"success": False, "error": "active_risk_percentage must be numeric"}
        if active_risk_percentage > 1.0:
            active_risk_percentage = active_risk_percentage / 100.0
        active_risk_percentage = max(0.0, min(1.0, active_risk_percentage))

        neo_payload: Dict[str, Any] = {
            "risk_profile": self.config.neo_default_risk_profile,
            "weight_type": self.config.neo_default_weight_type,
            "target_volatility": float(target_volatility),
            "active_risk_percentage": active_risk_percentage,
        }
        if isinstance(total_investment, (int, float)) and float(total_investment) > 0:
            neo_payload["investment_amount"] = float(total_investment)

        url = f"{self.config.neo_api_url}/neo/api/v1/optimize"
        try:
            response = requests.post(
                url,
                json=neo_payload,
                headers=self._build_neo_headers(),
                timeout=self.config.request_timeout_seconds,
            )
        except requests.RequestException as exc:
            return {
                "success": False,
                "error": "Neo engine API call failed",
                "details": str(exc),
            }

        if response.status_code != 200:
            return {
                "success": False,
                "error": "Neo engine API call failed",
                "status_code": response.status_code,
                "details": response.text[:600],
            }

        raw_result = response.json()
        securities_raw = raw_result.get("securities")
        normalized_passive: List[Dict[str, Any]] = []
        if isinstance(securities_raw, list):
            for sec in securities_raw:
                if not isinstance(sec, dict):
                    continue
                sec_type = str(sec.get("security_type", "") or "").strip().lower()
                if sec_type and sec_type != "passive":
                    continue
                weight = sec.get("weight")
                if not isinstance(weight, (int, float)):
                    continue
                ticker = str(sec.get("isin", "") or "").strip()
                if not ticker:
                    continue
                normalized_passive.append(
                    {
                        "isin": ticker,
                        "ticker": ticker,
                        "asset_class": str(sec.get("asset_class", "") or "").strip(),
                        "security_type": "passive",
                        "weight": float(weight),
                        "amount": (
                            float(sec.get("amount"))
                            if isinstance(sec.get("amount"), (int, float))
                            else 0.0
                        ),
                    }
                )
        # If upstream response has no explicit passive flags, preserve a minimal
        # securities view rather than dropping allocation context entirely.
        if not normalized_passive and isinstance(securities_raw, list):
            for sec in securities_raw:
                if not isinstance(sec, dict):
                    continue
                weight = sec.get("weight")
                if not isinstance(weight, (int, float)):
                    continue
                ticker = str(sec.get("isin", "") or "").strip()
                if not ticker:
                    continue
                normalized_passive.append(
                    {
                        "isin": ticker,
                        "ticker": ticker,
                        "asset_class": str(sec.get("asset_class", "") or "").strip(),
                        "security_type": str(sec.get("security_type", "") or "").strip().lower() or "passive",
                        "weight": float(weight),
                        "amount": (
                            float(sec.get("amount"))
                            if isinstance(sec.get("amount"), (int, float))
                            else 0.0
                        ),
                    }
                )

        compact_result = {
            "success": bool(raw_result.get("success", True)),
            "portfolio_expected_return_pct": raw_result.get("portfolio_expected_return_pct"),
            "portfolio_expected_volatility_pct": raw_result.get("portfolio_expected_volatility_pct"),
            "total_investment": raw_result.get("total_investment"),
            "securities": normalized_passive,
        }
        state.latest_neo_full = compact_result

        selected_weights = (
            raw_result.get("layers", {})
            .get("layer1", {})
            .get("selected_weights", {})
        )
        if isinstance(selected_weights, dict) and selected_weights:
            state.latest_neo_allocation = {
                str(k): float(v)
                for k, v in selected_weights.items()
                if isinstance(v, (int, float))
            }

        return {
            "success": True,
            "full_result": compact_result,
        }

    def _tool_declaration(self) -> List[ToolSchema]:
        """Provider-neutral tool declaration for advisor workflow."""
        return [
            ToolSchema(
                name="runCashflowModel",
                description=(
                    "Run numeric cashflow simulation. Returns quantitative projections only; "
                    "the AI must do interpretation and gap reasoning."
                ),
                parameters={
                    "simulation_mode": {
                        "type": "string",
                        "enum": ["deterministic", "monte_carlo"],
                        "description": "Simulation mode. Use deterministic first, then monte_carlo.",
                    },
                    "num_simulations": {
                        "type": "integer",
                        "description": "Number of simulations for monte_carlo mode.",
                    },
                    "seed": {
                        "type": "integer",
                        "description": "Optional random seed for simulation reproducibility.",
                    },
                    "return_individual_runs": {
                        "type": "boolean",
                        "description": "If true, request individual run trajectories in monte_carlo mode.",
                    },
                    "num_individual_runs": {
                        "type": "integer",
                        "description": "Number of individual runs to return when enabled.",
                    },
                    "use_latest_neo_allocation": {
                        "type": "boolean",
                        "description": "If true, rerun cashflow using the latest Neo allocation.",
                    },
                    "payload_override": {
                        "type": "object",
                        "description": (
                            "Deep-merge override for the cashflow params payload. "
                            "Use this to modify any account type or nested field "
                            "(bank, brokerage, 401k, ira, housing, debt, insurance, goals, etc.)."
                        ),
                    },
                    "bank_balance_override": {
                        "type": "number",
                        "description": "Optional bank balance override for scenario testing.",
                    },
                    "investment_balance_override": {
                        "type": "number",
                        "description": "Optional brokerage balance override for scenario testing.",
                    },
                },
            ),
            ToolSchema(
                name="optimizePortfolio",
                description=(
                    "Run Neo engine optimization. Exposed inputs are target_volatility and "
                    "optional Layer 2 active_risk_percentage (defaults to 0.0 if omitted)."
                ),
                parameters={
                    "target_volatility": {
                        "type": "number",
                        "description": "Target volatility as decimal between 0.05 and 0.20.",
                    },
                    "active_risk_percentage": {
                        "type": "number",
                        "description": (
                            "Layer 2 active risk split as decimal between 0.0 and 1.0 "
                            "(or 0-100 percent). If omitted, advisor defaults to 0.0."
                        ),
                    },
                },
                required=["target_volatility"],
            ),
        ]

    def _tool_loop_stage_name(self) -> str:
        """Stage key for tool-loop generation."""
        return "solution_tool_loop"

    def _build_initial_prompt(self, client_payload: Dict[str, Any], advisor_request: str) -> str:
        """Create initial prompt for the agent loop."""
        request_text = advisor_request.strip() or "No additional request constraints provided."
        return (
            "Analyze the following Stage-1 client profile package and generate a financial planning policy.\n\n"
            "Objectives:\n"
            "1) Use the provided client_financial_json, narrative understanding, and diagnosed gaps as source-of-truth.\n"
            "2) Validate and refine financial gap understanding with cashflow simulation.\n"
            "3) Use Neo engine for investment-policy recommendation.\n"
            "4) Ensure recommendations explain why they address the gaps.\n\n"
            "Additional request from advisor/user:\n"
            f"{request_text}\n\n"
            "Stage-1 profile package JSON:\n"
            f"{json.dumps(client_payload, indent=2, ensure_ascii=True)}"
        )

    def _parse_json_object(self, raw_text: str) -> Dict[str, Any]:
        """Parse a JSON object from plain model text."""
        text = raw_text.strip()
        if not text:
            raise ValueError("Advisor returned empty JSON output")

        try:
            parsed = json.loads(text)
            if isinstance(parsed, dict):
                return parsed
        except json.JSONDecodeError:
            pass

        start = text.find("{")
        end = text.rfind("}")
        if start >= 0 and end > start:
            candidate = text[start : end + 1]
            try:
                parsed = json.loads(candidate)
                if isinstance(parsed, dict):
                    return parsed
            except json.JSONDecodeError:
                pass

        raise ValueError("Advisor returned invalid JSON output")

    def _normalize_final_policy_json(
        self,
        payload: Dict[str, Any],
        securities: List[Dict[str, Any]],
        portfolio: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Normalize and enforce single-source final policy JSON contract."""
        def _extract_amount_from_text(text: str) -> float:
            raw = str(text or "")
            if not raw:
                return 0.0

            # Match forms like "$7,000,000", "USD 7,000,000", "7,000,000 USD"
            direct_matches = re.findall(
                r"(?i)(?:usd|us\\$|\\$)\\s*([0-9]{1,3}(?:,[0-9]{3})*(?:\\.[0-9]+)?|[0-9]+(?:\\.[0-9]+)?)|([0-9]{1,3}(?:,[0-9]{3})*(?:\\.[0-9]+)?|[0-9]+(?:\\.[0-9]+)?)\\s*(?:usd|us\\$)",
                raw,
            )
            if direct_matches:
                value_raw = direct_matches[0][0] or direct_matches[0][1]
                try:
                    return max(0.0, float(value_raw.replace(",", "")))
                except ValueError:
                    pass

            # Match forms like "7 million", "10.5m"
            million_match = re.search(r"(?i)\\b([0-9]+(?:\\.[0-9]+)?)\\s*(million|m)\\b", raw)
            if million_match:
                try:
                    return max(0.0, float(million_match.group(1)) * 1_000_000.0)
                except ValueError:
                    pass
            return 0.0

        def _sum_security_amounts(rows: List[Dict[str, Any]]) -> float:
            total = 0.0
            for row in rows:
                if not isinstance(row, dict):
                    continue
                amount = row.get("allocation_amount")
                if isinstance(amount, (int, float)):
                    total += max(0.0, float(amount))
            return round(total, 2)

        menu_raw = payload.get("menu")
        menu = menu_raw if isinstance(menu_raw, dict) else {}
        menu_title = str(menu.get("title", "") or "").strip() or "Recommended Policy"
        menu_summary = str(menu.get("summary", "") or "").strip() or "Policy generated from consultation context and Neo optimization."

        detail_raw = payload.get("detail")
        detail = detail_raw if isinstance(detail_raw, dict) else {}
        sections_raw = detail.get("sections")
        sections: List[Dict[str, str]] = []
        if isinstance(sections_raw, list):
            for idx, section in enumerate(sections_raw):
                if not isinstance(section, dict):
                    continue
                sec_title = str(section.get("title", "") or "").strip()
                sec_content = str(section.get("content", "") or "").strip()
                if not sec_title or not sec_content:
                    continue
                sections.append(
                    {
                        "id": str(section.get("id", "") or f"s{idx + 1}"),
                        "title": sec_title,
                        "content": sec_content,
                    }
                )
        normalized_titles = [s["title"].strip().lower() for s in sections]
        missing_titles = [
            title
            for title in REQUIRED_STEP1_SECTION_TITLES
            if title.strip().lower() not in normalized_titles
        ]
        if missing_titles:
            raise ValueError(f"Final policy JSON missing required sections: {', '.join(missing_titles)}")

        execution_raw = payload.get("execution")
        execution = execution_raw if isinstance(execution_raw, dict) else {}
        currency = str(portfolio.get("currency", "USD") or "USD").upper()
        total_transfer_model_raw = execution.get("total_transfer")
        total_transfer_portfolio_raw = portfolio.get("total_value")

        deployment_text = ""
        section9_index: Optional[int] = None
        for i, section in enumerate(sections):
            section_title = section["title"].strip().lower()
            if section_title == "capital deployment timeline":
                deployment_text = section["content"]
            if section_title == "investment vehicle selection highlights":
                section9_index = i

        total_transfer = 0.0
        if isinstance(total_transfer_model_raw, (int, float)) and float(total_transfer_model_raw) > 0:
            total_transfer = float(total_transfer_model_raw)
        elif isinstance(total_transfer_portfolio_raw, (int, float)) and float(total_transfer_portfolio_raw) > 0:
            total_transfer = float(total_transfer_portfolio_raw)
        else:
            securities_sum = _sum_security_amounts(securities)
            if securities_sum > 0:
                total_transfer = securities_sum
            else:
                total_transfer = _extract_amount_from_text(deployment_text)
        total_transfer = round(max(0.0, float(total_transfer)), 2)

        normalized_securities: List[Dict[str, Any]] = []
        for idx, sec in enumerate(securities):
            if not isinstance(sec, dict):
                continue
            name = str(sec.get("name", "") or "").strip()
            if not name:
                continue
            allocation_pct = float(sec.get("allocation_pct", 0.0) or 0.0)
            allocation_pct = max(0.0, allocation_pct)
            raw_amount = sec.get("allocation_amount")
            amount = float(raw_amount) if isinstance(raw_amount, (int, float)) else 0.0
            if total_transfer > 0 and allocation_pct > 0:
                amount = (allocation_pct / 100.0) * total_transfer
            management_style_raw = str(sec.get("management_style", "") or "").strip().lower()
            management_style = "active" if management_style_raw == "active" else "passive"
            normalized_securities.append(
                {
                    "id": str(sec.get("id", "") or f"sec_{idx + 1}"),
                    "name": name,
                    "allocation_pct": round(allocation_pct, 2),
                    "allocation_amount": round(max(0.0, amount), 2),
                    "management_style": management_style,
                    "asset_class": str(sec.get("asset_class", "") or "").strip() or None,
                }
            )

        if total_transfer > 0 and normalized_securities:
            # Align rounded per-security amounts to exact portfolio capital.
            amount_sum = round(
                sum(float(row.get("allocation_amount", 0.0) or 0.0) for row in normalized_securities),
                2,
            )
            delta = round(total_transfer - amount_sum, 2)
            if abs(delta) >= 0.01:
                anchor_idx = max(
                    range(len(normalized_securities)),
                    key=lambda i: float(normalized_securities[i].get("allocation_pct", 0.0) or 0.0),
                )
                adjusted = round(
                    max(
                        0.0,
                        float(normalized_securities[anchor_idx].get("allocation_amount", 0.0) or 0.0) + delta,
                    ),
                    2,
                )
                normalized_securities[anchor_idx]["allocation_amount"] = adjusted

        # Canonical Section 9 payload from backend portfolio rows to enforce consistency.
        section9_rows = [
            {
                "security_name": row["name"],
                "asset_class": row["asset_class"] or "",
                "allocation_pct": row["allocation_pct"],
                "allocation_amount": row["allocation_amount"],
                "management_style": row["management_style"],
                "security_id": row["id"],
            }
            for row in sorted(normalized_securities, key=lambda s: float(s["allocation_pct"]), reverse=True)
        ]
        section9_content = json.dumps({"recommended_securities": section9_rows}, ensure_ascii=True)
        if section9_index is not None:
            sections[section9_index]["content"] = section9_content

        return {
            "proposal_count": 1,
            "proposal_index": 1,
            "menu": {
                "title": menu_title,
                "summary": menu_summary,
            },
            "detail": {
                "title": str(detail.get("title", "") or "").strip() or menu_title,
                "sections": sections,
                "portfolio": {
                    "currency": currency,
                    "total_value": total_transfer if total_transfer > 0 else None,
                    "securities": normalized_securities,
                },
            },
            "execution": {
                "remedy_name": str(execution.get("remedy_name", "") or "").strip() or menu_title,
                "funding_source": "JPMorgan Chase Bank, N.A. — Account ending in XXX",
                "total_transfer": total_transfer,
                "currency": currency,
            },
        }

    def _estimate_total_investment(self, client_payload: Dict[str, Any]) -> float:
        """Estimate investable total from account balance-like fields."""
        financial_payload = self._resolve_cashflow_payload(client_payload)
        accounts = financial_payload.get("accounts", {})
        total = 0.0

        def walk(value: Any, key_name: str = "") -> None:
            nonlocal total
            if isinstance(value, dict):
                for k, v in value.items():
                    walk(v, str(k))
                return
            if isinstance(value, list):
                for v in value:
                    walk(v, key_name)
                return
            if isinstance(value, (int, float)):
                key = key_name.lower()
                if any(token in key for token in ["balance", "amount", "value", "assets"]):
                    total += max(0.0, float(value))

        if isinstance(accounts, dict):
            walk(accounts)
        if total > 0:
            return round(total, 2)

        # Voice-consultation mode may omit structured accounts; infer investable
        # capital from transcript cues like "7 million in bank deposit".
        transcript = financial_payload.get("consultation_transcript")
        if not isinstance(transcript, dict):
            transcript = client_payload.get("consultation_transcript")
        turns = transcript.get("turns") if isinstance(transcript, dict) else None
        if not isinstance(turns, list):
            return 0.0

        client_text = " ".join(
            str(turn.get("text", "") or "")
            for turn in turns
            if isinstance(turn, dict) and str(turn.get("speaker", "")).strip().lower() == "client"
        ).strip()
        if not client_text:
            client_text = " ".join(
                str(turn.get("text", "") or "") for turn in turns if isinstance(turn, dict)
            ).strip()
        if not client_text:
            return 0.0

        amount_pattern = re.compile(
            r"(?i)(?:usd|us\\$|\\$)?\\s*([0-9]{1,3}(?:,[0-9]{3})*(?:\\.[0-9]+)?|[0-9]+(?:\\.[0-9]+)?)\\s*(billion|bn|million|m|thousand|k)?"
        )
        deposit_tokens = ("deposit", "bank", "cash", "saving", "investable", "investment", "account")
        goal_tokens = ("house", "home", "goal", "target", "worth", "purchase", "buy")
        year_tokens = ("year", "years")

        best_value = 0.0
        best_score = -10_000

        for match in amount_pattern.finditer(client_text):
            raw_number = str(match.group(1) or "").replace(",", "")
            if not raw_number:
                continue
            try:
                value = float(raw_number)
            except ValueError:
                continue
            unit = str(match.group(2) or "").strip().lower()
            if unit in {"billion", "bn"}:
                value *= 1_000_000_000.0
            elif unit in {"million", "m"}:
                value *= 1_000_000.0
            elif unit in {"thousand", "k"}:
                value *= 1_000.0
            if value <= 0:
                continue

            start = max(0, match.start() - 48)
            end = min(len(client_text), match.end() + 48)
            context = client_text[start:end].lower()

            score = 0
            if any(tok in context for tok in deposit_tokens):
                score += 6
            if any(tok in context for tok in goal_tokens):
                score -= 4
            if any(tok in context for tok in year_tokens):
                score -= 2

            # Filter obvious non-capital magnitudes (e.g., age) unless context strongly implies money.
            if value < 50_000 and score < 6:
                continue

            if score > best_score or (score == best_score and value > best_value):
                best_score = score
                best_value = value

        return round(best_value, 2) if best_value > 0 else 0.0

    def _read_prompt(self, filename: str) -> str:
        """Load prompt text from prompts directory."""
        path = self.prompts_dir / filename
        if not path.exists():
            raise FileNotFoundError(f"Prompt file not found: {path}")
        return path.read_text(encoding="utf-8")

    def _resolve_cashflow_payload(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """Resolve the cashflow-ready payload from direct or Stage-1 package input."""
        if not isinstance(payload, dict):
            return {}

        if isinstance(payload.get("client_financial_json"), dict):
            return payload.get("client_financial_json", {})

        return payload

    def _validate_cashflow_payload_shape(self, payload: Dict[str, Any]) -> None:
        """Validate shape required for cashflow simulation."""
        required_top_fields = ["client_profile", "income", "expenses"]
        missing = [field for field in required_top_fields if field not in payload]
        if missing:
            raise ValueError(f"Missing required fields: {', '.join(missing)}")

        client_profile = payload.get("client_profile", {})
        if not isinstance(client_profile, dict):
            raise ValueError("client_profile must be an object")
        if "age" not in client_profile or "retirement_age" not in client_profile:
            raise ValueError("client_profile.age and client_profile.retirement_age are required")

        income = payload.get("income", {})
        if not isinstance(income, dict) or "salary" not in income:
            raise ValueError("income.salary is required")

        expenses = payload.get("expenses", {})
        if not isinstance(expenses, dict) or "base_spending" not in expenses:
            raise ValueError("expenses.base_spending is required")

    def _validate_client_payload(self, payload: Dict[str, Any]) -> None:
        """Validate payload shape required for policy generation."""
        if not isinstance(payload, dict):
            raise ValueError("Request payload must be a JSON object")

        resolved_payload = self._resolve_cashflow_payload(payload)
        if resolved_payload is not payload:
            self._validate_cashflow_payload_shape(resolved_payload)
            return

        # Voice-consultation runs may provide transcript context only.
        # In that mode we avoid forcing synthetic profile/income/expense data.
        consultation_transcript = payload.get("consultation_transcript")
        if isinstance(consultation_transcript, dict):
            turns = consultation_transcript.get("turns")
            if isinstance(turns, list) and any(isinstance(t, dict) for t in turns):
                return

        self._validate_cashflow_payload_shape(payload)

    def _normalize_args(self, args: Any) -> Dict[str, Any]:
        """Normalize Gemini function args into a plain dictionary."""
        if args is None:
            return {}
        if isinstance(args, dict):
            return args
        if isinstance(args, str):
            try:
                parsed = json.loads(args)
                if isinstance(parsed, dict):
                    return parsed
                return {}
            except json.JSONDecodeError:
                return {}

        if hasattr(args, "items"):
            return {str(k): v for k, v in args.items()}

        return {}

    def _build_cashflow_headers(self) -> Dict[str, str]:
        """Build headers for cashflow API requests."""
        headers = {"Content-Type": "application/json"}
        if self.config.cashflow_api_key:
            headers["X-Api-Key"] = self.config.cashflow_api_key
        return headers

    def _build_neo_headers(self) -> Dict[str, str]:
        """Build headers for Neo engine API requests."""
        headers = {"Content-Type": "application/json"}
        if self.config.neo_api_key:
            headers["X-Api-Key"] = self.config.neo_api_key
        return headers

    def _deep_merge(self, base: Dict[str, Any], override: Dict[str, Any]) -> Dict[str, Any]:
        """Recursively deep-merge dictionaries."""
        merged = copy.deepcopy(base)
        for key, value in override.items():
            if (
                key in merged
                and isinstance(merged[key], dict)
                and isinstance(value, dict)
            ):
                merged[key] = self._deep_merge(merged[key], value)
            else:
                merged[key] = copy.deepcopy(value)
        return merged
