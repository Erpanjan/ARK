"""Client profile agent that focuses on understanding needs/gaps via cashflow analysis."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any, Dict, List

_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))
_SOLUTION_AGENT_DIR = _REPO_ROOT / "solution-agent-service"
if str(_SOLUTION_AGENT_DIR) not in sys.path:
    sys.path.insert(0, str(_SOLUTION_AGENT_DIR))

from advisor_agent import AdvisorAgent, AdvisorConfig
from shared.llm import LLMMessage, ToolSchema


class ClientProfileAgent(AdvisorAgent):
    """Cashflow-first agent for client understanding and gap identification."""

    def analyze_client_profile(
        self,
        client_payload: Dict[str, Any],
        advisor_request: str = "",
    ) -> Dict[str, Any]:
        """Run single-stage conversation-driven profile analysis with cashflow tool support."""
        self._validate_client_payload(client_payload)
        starter_financial_json = self._normalize_financial_json_for_cashflow({})

        diagnosis_input = {
            "conversation_context": client_payload,
            "client_financial_json": starter_financial_json,
        }

        loop_result = self._run_tool_loop(
            client_payload=diagnosis_input,
            advisor_request=advisor_request,
        )
        state = loop_result["state"]

        context = {
            "conversation_context": client_payload,
            "client_financial_json": starter_financial_json,
            "advisor_request": advisor_request,
            "tool_memory": self._build_tool_memory_context(state),
            "tool_audit": state.tool_audit,
            "finalize_signal": loop_result.get("finalize_signal"),
        }

        prompt_template = self._read_prompt("core_profile_prompt.txt")
        user_prompt = (
            f"{prompt_template}\n\n"
            "Use this JSON context as source-of-truth:\n"
            f"{json.dumps(context, indent=2, ensure_ascii=True)}"
        )

        response, model_used, provider_used = self._generate_with_fallback(
            stage_name="client_profile_synthesis",
            messages=[LLMMessage(role="user", content=user_prompt)],
            system_instruction=(
                "You are a client profile analysis agent. Produce one JSON object only."
            ),
            use_tools=False,
            temperature=0.2,
        )

        raw_text = response.text.strip()

        profile_analysis = self._parse_json_object(raw_text)
        model_financial_json = profile_analysis.get("client_financial_json", {})
        if not isinstance(model_financial_json, dict):
            model_financial_json = {}
        profile_analysis["client_financial_json"] = self._normalize_financial_json_for_cashflow(
            model_financial_json
        )
        if not str(profile_analysis.get("client_understanding_narrative", "") or "").strip():
            profile_analysis["client_understanding_narrative"] = str(
                profile_analysis.get("client_understanding_summary", "") or ""
            ).strip()
        self._validate_profile_analysis(profile_analysis)

        return {
            "success": True,
            "model_used": model_used,
            "provider_used": provider_used,
            "profile_analysis": profile_analysis,
            "context": context,
            "tool_loop_model_used": loop_result.get("model_used", "unknown"),
            "tool_loop_provider_used": loop_result.get("provider_used", "unknown"),
            "finalize_signal": loop_result.get("finalize_signal"),
        }

    def _tool_declaration(self) -> List[ToolSchema]:
        """Cashflow-only tool declaration for client profile analysis."""
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
            )
        ]

    def _tool_loop_stage_name(self) -> str:
        """Stage key for profile-agent tool loop."""
        return "client_profile_tool_loop"

    def _build_initial_prompt(self, client_payload: Dict[str, Any], advisor_request: str) -> str:
        """Create initial prompt for profile-understanding loop."""
        request_text = advisor_request.strip() or "No additional request constraints provided."
        conversation_context = {}
        financial_json = client_payload
        if isinstance(client_payload.get("conversation_context"), dict):
            conversation_context = client_payload.get("conversation_context", {})
        if isinstance(client_payload.get("client_financial_json"), dict):
            financial_json = client_payload.get("client_financial_json", {})
        return (
            "Analyze the following conversation context and client financial JSON to identify financial needs/gaps.\n\n"
            "Objectives:\n"
            "1) Build clear client understanding from conversation-derived financial context.\n"
            "2) Use cashflow modeling (deterministic + probabilistic) for gap diagnosis.\n"
            "3) Identify gaps by category: investment related, insurance related, spending related, liability related.\n"
            "4) Produce concise, actionable diagnostic output (not policy construction).\n\n"
            "Additional request from advisor/user:\n"
            f"{request_text}\n\n"
            "Conversation context JSON:\n"
            f"{json.dumps(conversation_context, indent=2, ensure_ascii=True)}\n\n"
            "Client financial JSON scaffold (for field alignment; update based on conversation evidence):\n"
            f"{json.dumps(financial_json, indent=2, ensure_ascii=True)}"
        )

    def _validate_profile_analysis(self, payload: Dict[str, Any]) -> None:
        """Validate profile-analysis output schema."""
        required_top = [
            "client_financial_json",
            "client_understanding_narrative",
            "identified_needs",
            "gaps_by_category",
            "scenario_findings",
            "key_assumptions_and_uncertainties",
            "tool_execution_log",
        ]
        missing = [field for field in required_top if field not in payload]
        if missing:
            raise ValueError(
                f"Client profile analysis JSON missing required fields: {', '.join(missing)}"
            )

        financial_json = payload.get("client_financial_json")
        self._validate_financial_json_payload(financial_json)

        narrative = str(payload.get("client_understanding_narrative", "") or "").strip()
        if not narrative:
            raise ValueError("Client profile analysis requires client_understanding_narrative")

        if not isinstance(payload.get("identified_needs"), list):
            raise ValueError("Client profile analysis requires identified_needs array")

        gaps = payload.get("gaps_by_category")
        if not isinstance(gaps, dict):
            raise ValueError("Client profile analysis requires gaps_by_category object")

        for key in [
            "investment related",
            "insurance related",
            "spending related",
            "liability related",
        ]:
            if key not in gaps:
                raise ValueError(f"gaps_by_category.{key} is required")
            value = gaps.get(key)
            if isinstance(value, str):
                if value != "None":
                    raise ValueError(
                        f"gaps_by_category.{key} string value must be exactly 'None'"
                    )
                continue
            if not isinstance(value, list):
                raise ValueError(
                    f"gaps_by_category.{key} must be an array or the string 'None'"
                )
            for idx, row in enumerate(value):
                if not isinstance(row, dict):
                    raise ValueError(
                        f"gaps_by_category.{key}[{idx}] must be an object with gap/discussion"
                    )
                gap_text = str(row.get("gap", "") or "").strip()
                discussion = str(row.get("discussion", "") or "").strip()
                if not gap_text:
                    raise ValueError(f"gaps_by_category.{key}[{idx}].gap is required")
                if not discussion:
                    raise ValueError(
                        f"gaps_by_category.{key}[{idx}].discussion is required"
                    )

    def _normalize_financial_json_for_cashflow(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """Normalize model-produced financial JSON to the canonical cashflow payload shape."""
        normalized = dict(payload) if isinstance(payload, dict) else {}

        client_profile = normalized.get("client_profile")
        if not isinstance(client_profile, dict):
            client_profile = {}
        client_profile.setdefault("age", 35)
        client_profile.setdefault("retirement_age", 65)
        client_profile.setdefault("life_expectancy", 90)
        client_profile.setdefault("dependents", 0)
        client_profile.setdefault("dependents_detail", [])
        normalized["client_profile"] = client_profile

        income = normalized.get("income")
        if not isinstance(income, dict):
            income = {}
        income.setdefault("salary", 0.0)
        income.setdefault("bonus", 0.0)
        income.setdefault("spouse_income", 0.0)
        income.setdefault("yearly_increase", 3.0)
        income.setdefault("net_monthly_take_home_min", 0.0)
        income.setdefault("net_monthly_take_home_max", 0.0)
        normalized["income"] = income

        expenses = normalized.get("expenses")
        if not isinstance(expenses, dict):
            expenses = {}
        expenses.setdefault("base_spending", 0.0)
        expenses.setdefault("yearly_increase", 3.0)
        housing = expenses.get("housing")
        if not isinstance(housing, dict):
            housing = {}
        housing.setdefault("mortgage_balance", 0.0)
        housing.setdefault("monthly_principal_interest", 0.0)
        housing.setdefault("monthly_property_tax_and_homeowners_insurance", 0.0)
        expenses["housing"] = housing
        normalized["expenses"] = expenses

        accounts = normalized.get("accounts")
        if not isinstance(accounts, dict):
            accounts = {}
        bank = accounts.get("bank")
        if not isinstance(bank, dict):
            bank = {}
        bank.setdefault("balance", 0.0)
        accounts["bank"] = bank
        brokerage = accounts.get("brokerage")
        if not isinstance(brokerage, dict):
            brokerage = {}
        brokerage.setdefault("balance", 0.0)
        accounts["brokerage"] = brokerage
        k401 = accounts.get("401k")
        if not isinstance(k401, dict):
            k401 = {}
        k401.setdefault("pretax_balance", 0.0)
        k401.setdefault("contrib_percent", 10.0)
        k401.setdefault("company_match_percent", 4.0)
        accounts["401k"] = k401
        ira = accounts.get("ira")
        if not isinstance(ira, dict):
            ira = {}
        ira.setdefault("balance", 0.0)
        accounts["ira"] = ira
        a529 = accounts.get("529")
        if not isinstance(a529, dict):
            a529 = {}
        a529.setdefault("balance", 0.0)
        accounts["529"] = a529
        normalized["accounts"] = accounts

        liabilities = normalized.get("liabilities")
        if not isinstance(liabilities, dict):
            liabilities = {}
        liabilities.setdefault("mortgage_balance", 0.0)
        normalized["liabilities"] = liabilities

        preferences = normalized.get("preferences")
        if not isinstance(preferences, dict):
            preferences = {}
        preferences.setdefault("maintain_emergency_reserve_months", 6.0)
        normalized["preferences"] = preferences

        goals = normalized.get("goals")
        if not isinstance(goals, list):
            goals = []
        normalized["goals"] = goals

        asset_allocation = normalized.get("asset_allocation")
        if not isinstance(asset_allocation, dict):
            asset_allocation = {}
        asset_allocation.setdefault("taxable_brokerage_current", {})
        asset_allocation.setdefault("401k_current", {})
        normalized["asset_allocation"] = asset_allocation

        return normalized

    def _validate_financial_json_payload(self, payload: Any) -> None:
        """Validate that derived financial JSON is cashflow-simulation ready."""
        if not isinstance(payload, dict):
            raise ValueError("client_financial_json must be an object")

        required_top_fields = ["client_profile", "income", "expenses"]
        missing = [field for field in required_top_fields if field not in payload]
        if missing:
            raise ValueError(
                f"client_financial_json missing required fields: {', '.join(missing)}"
            )

        client_profile = payload.get("client_profile", {})
        if not isinstance(client_profile, dict):
            raise ValueError("client_financial_json.client_profile must be an object")
        if "age" not in client_profile or "retirement_age" not in client_profile:
            raise ValueError(
                "client_financial_json.client_profile.age and "
                "client_financial_json.client_profile.retirement_age are required"
            )

        income = payload.get("income", {})
        if not isinstance(income, dict) or "salary" not in income:
            raise ValueError("client_financial_json.income.salary is required")

        expenses = payload.get("expenses", {})
        if not isinstance(expenses, dict) or "base_spending" not in expenses:
            raise ValueError("client_financial_json.expenses.base_spending is required")


def build_client_profile_agent(config: AdvisorConfig) -> ClientProfileAgent:
    """Build client profile agent using the dedicated prompt directory."""
    prompts_dir = Path(__file__).resolve().parent / "prompts"
    return ClientProfileAgent(config=config, prompts_dir=prompts_dir)
