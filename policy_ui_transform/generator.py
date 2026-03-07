"""LLM-based conversion from Step-1 policy JSON to UI policy JSON."""

from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from shared.llm import LLMClientFactory, LLMGenerateRequest, LLMMessage, dedupe_model_chain


class PolicyUiGenerator:
    """Dedicated step for generating UI payload JSON from Step-1 policy JSON."""

    def __init__(
        self,
        google_api_key: str,
        openai_api_key: str,
        provider: str,
        model: str,
        fallbacks: Optional[List[tuple[str, str]]],
        llm_timeout_ms: int,
        prompts_dir: Path,
    ):
        self.google_api_key = google_api_key
        self.openai_api_key = openai_api_key
        self.chain = dedupe_model_chain((provider, model), fallbacks or [])
        if not self.chain:
            raise ValueError("Policy UI model chain is empty")
        providers = {str(provider_name or "").strip().lower() for provider_name, _ in self.chain}
        if "gemini" in providers and not self.google_api_key:
            raise ValueError("Policy UI stage requires Gemini API key")
        if "openai" in providers and not self.openai_api_key:
            raise ValueError("Policy UI stage requires OPENAI_API_KEY")
        self.llm_timeout_ms = llm_timeout_ms
        self.prompts_dir = prompts_dir
        # Temporary prompt logging to inspect exact request contexts.
        self._prompt_log_enabled = os.getenv("ADVISOR_TEMP_LOG_PROMPTS", "true").strip().lower() not in {
            "0",
            "false",
            "no",
            "off",
        }
        default_log_path = (
            self.prompts_dir.parent.parent / "solution-agent-service" / "logs" / "gemini_prompt_debug.ndjson"
        )
        self._prompt_log_path = Path(
            os.getenv("ADVISOR_TEMP_PROMPT_LOG_PATH", str(default_log_path))
        )

    def generate_ui_policy_json(
        self,
        step1_policy: Optional[Dict[str, Any]] = None,
        supporting_context: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Run conversion from Step-1 policy JSON to UI JSON payload."""
        if not isinstance(step1_policy, dict):
            raise ValueError("step1_policy is required")
        last_error: Optional[Exception] = None
        try:
            system_prompt = self._read_prompt("system_prompt.txt")
            user_payload = {
                "step1_policy": step1_policy,
                "supporting_context": supporting_context or {},
            }
            user_prompt = (
                "Convert the provided Step-1 financial planning policy into UI JSON.\n"
                "Use step1_policy as source-of-truth. Use supporting_context only when needed.\n\n"
                f"{json.dumps(user_payload, indent=2, ensure_ascii=True)}"
            )
            for provider_name, model_name in self.chain:
                try:
                    adapter = LLMClientFactory.create(
                        provider=provider_name,
                        google_api_key=self.google_api_key,
                        openai_api_key=self.openai_api_key,
                        timeout_ms=self.llm_timeout_ms,
                    )
                    self._append_prompt_log(
                        {
                            "stage": "ui_transform_generate_content",
                            "timestamp": datetime.now(timezone.utc).isoformat(),
                            "provider": provider_name,
                            "model": model_name,
                            "system_instruction": system_prompt,
                            "temperature": 0.2,
                            "contents": [{"role": "user", "content": user_prompt}],
                        }
                    )
                    response = adapter.generate(
                        request=LLMGenerateRequest(
                            messages=[LLMMessage(role="user", content=user_prompt)],
                            system_instruction=system_prompt,
                            temperature=0.2,
                        ),
                        model=model_name,
                    )
                    payload = self._parse_json_object(response.text.strip())
                    payload = self._normalize_menu_preview_summary(payload)
                    return {
                        "success": True,
                        "model_used": model_name,
                        "provider_used": provider_name,
                        "ui_policy": payload,
                        "ui_generation": {
                            "fallback_used": (provider_name, model_name) != self.chain[0],
                            "source": provider_name,
                        },
                    }
                except Exception as exc:  # pylint: disable=broad-except
                    last_error = exc
                    message = str(exc)
                    if "429" in message or "RESOURCE_EXHAUSTED" in message:
                        continue
                    if "404" in message or "NOT_FOUND" in message:
                        continue
                    break
        except Exception as exc:  # pylint: disable=broad-except
            last_error = exc
        return self._build_reference_ui_fallback(str(last_error))

    def _read_prompt(self, filename: str) -> str:
        path = self.prompts_dir / filename
        if not path.exists():
            raise FileNotFoundError(f"Prompt file not found: {path}")
        return path.read_text(encoding="utf-8")

    def _parse_json_object(self, raw_text: str) -> Dict[str, Any]:
        text = str(raw_text or "").strip()
        if not text:
            raise ValueError("UI generation returned empty JSON output")

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

        raise ValueError("UI generation returned invalid JSON output")

    def _append_prompt_log(self, payload: Dict[str, Any]) -> None:
        """Append prompt-debug payload as NDJSON; never raise to caller."""
        if not self._prompt_log_enabled:
            return
        try:
            self._prompt_log_path.parent.mkdir(parents=True, exist_ok=True)
            with self._prompt_log_path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(payload, ensure_ascii=True, default=str) + "\n")
        except OSError:
            # Temporary diagnostics should never break policy generation.
            pass

    def _normalize_menu_preview_summary(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """Constrain menu summary to concise preview form for menu-card rendering."""
        if not isinstance(payload, dict):
            return payload

        menu = payload.get("menu")
        if not isinstance(menu, dict):
            return payload

        summary = str(menu.get("summary", "") or "").strip()
        if not summary:
            return payload

        compact = " ".join(summary.split())
        sentences = [s.strip() for s in compact.replace("!", ".").replace("?", ".").split(".") if s.strip()]

        picked: list[str] = []
        for sentence in sentences:
            # De-prioritize dense numeric explanation in preview copy.
            digit_count = sum(ch.isdigit() for ch in sentence)
            if digit_count > 6 and len(sentences) > 1:
                continue
            picked.append(sentence)
            if len(picked) == 3:
                break

        if not picked:
            picked = sentences[:2] if sentences else [compact]

        concise = ". ".join(picked).strip()
        if concise and not concise.endswith("."):
            concise += "."

        if len(concise) > 260:
            concise = concise[:259].rstrip() + "…"

        menu["summary"] = concise
        payload["menu"] = menu
        return payload

    def _build_reference_ui_fallback(self, failure_reason: str) -> Dict[str, Any]:
        """Return a deterministic UI payload when UI transformation fails."""
        reference_securities = [
            {
                "id": "VOO",
                "name": "VOO",
                "allocation_pct": 44.34,
                "allocation_amount": 299295.00,
                "management_style": "passive",
                "asset_class": "US Equity",
            },
            {
                "id": "BTC",
                "name": "BTC",
                "allocation_pct": 25.78,
                "allocation_amount": 174015.00,
                "management_style": "passive",
                "asset_class": "Bitcoin",
            },
            {
                "id": "EWJ",
                "name": "EWJ",
                "allocation_pct": 16.38,
                "allocation_amount": 110565.00,
                "management_style": "passive",
                "asset_class": "Japan Equity",
            },
            {
                "id": "IEMU",
                "name": "IEMU",
                "allocation_pct": 11.49,
                "allocation_amount": 77557.50,
                "management_style": "passive",
                "asset_class": "Dev. Europe ex UK Equity",
            },
            {
                "id": "BIL",
                "name": "BIL",
                "allocation_pct": 2.00,
                "allocation_amount": 13500.00,
                "management_style": "passive",
                "asset_class": "Cash",
            },
        ]
        section9_content = json.dumps(
            {
                "recommended_securities": [
                    {
                        "security_name": row["name"],
                        "asset_class": row["asset_class"],
                        "allocation_pct": row["allocation_pct"],
                        "allocation_amount": row["allocation_amount"],
                        "management_style": row["management_style"],
                        "security_id": row["id"],
                    }
                    for row in reference_securities
                ]
            },
            ensure_ascii=True,
        )
        sections: List[Dict[str, str]] = [
            {
                "id": "client-background",
                "title": "Client Background",
                "content": (
                    "Michael Carter, age 36, and Emily Carter, age 34, live in Austin, Texas with their "
                    "one-year-old son Noah. Michael works as a Senior Operations Manager with stable long-term "
                    "income, while Emily works part-time as a pediatric nurse to preserve childcare flexibility. "
                    "The household priorities are retirement security, education funding, emergency reserves, and "
                    "stronger portfolio discipline."
                ),
            },
            {
                "id": "client-financial-snapshot",
                "title": "Client Financial Snapshot",
                "content": (
                    "Gross household income is approximately USD 242,000 per year, with estimated monthly "
                    "take-home pay of USD 12,300 to USD 13,100. Total investable assets are USD 675,000 across "
                    "USD 78,000 in cash, USD 275,000 in taxable brokerage invested in US equity, and "
                    "USD 322,000 in Michael's 401(k) invested in US Treasury exposure. Liabilities include a "
                    "USD 472,000 mortgage at 3.375% fixed and Emily's student loan payment of USD 280 per month."
                ),
            },
            {
                "id": "client-financial-needs",
                "title": "Client Financial Needs",
                "content": (
                    "The household needs a coordinated strategy for retirement readiness by age 62, future college "
                    "funding for Noah, and preservation of a six- to nine-month emergency reserve. The plan also "
                    "needs to reduce concentration risk, improve tax efficiency between taxable and tax-deferred "
                    "accounts, and create enough structural savings margin to support long-term goals."
                ),
            },
            {
                "id": "client-investment-preferences",
                "title": "Client Investment Preferences and Behavioral Considerations",
                "content": (
                    "Michael and Emily prefer disciplined diversification over concentrated exposures and want a "
                    "household-level allocation framework that reduces reactive decisions. They value tax efficiency, "
                    "want to avoid over-concentration in the brokerage account, and need an implementable structure "
                    "that keeps retirement, liquidity, and education funding aligned."
                ),
            },
            {
                "id": "taxes-exclusions",
                "title": "Taxes, Exclusions, and Exemptions",
                "content": (
                    "Because the family resides in Texas, there is no state income tax, so planning emphasis falls "
                    "on federal tax efficiency and account-location discipline. Higher-growth assets should be used "
                    "more intentionally across tax-deferred and taxable accounts, while no special exclusions or "
                    "religious investment restrictions were identified in the reference policy."
                ),
            },
            {
                "id": "special-requirements",
                "title": "Other Special Requirements",
                "content": (
                    "The policy must preserve current lifestyle continuity, maintain liquid emergency reserves, and "
                    "avoid treating the low-rate mortgage as an immediate prepayment priority. The implementation "
                    "approach should be practical for a young family and flexible enough to revisit education-cost "
                    "targets when better data becomes available."
                ),
            },
            {
                "id": "capital-deployment",
                "title": "Capital Deployment Timeline",
                "content": (
                    "Total plan capital is USD 675,000. Implementation assumes immediate reallocation of existing "
                    "balances, with USD 322,000 repositioned inside the 401(k) for retirement and USD 353,000 "
                    "allocated across brokerage and cash holdings for education support, liquidity, and household "
                    "portfolio discipline."
                ),
            },
            {
                "id": "portfolio-policy",
                "title": "Portfolio Policy",
                "content": (
                    "The policy replaces the current barbell structure of 100% Treasury in the 401(k) and 100% US "
                    "equity in taxable assets with a globally diversified, risk-optimized portfolio. The target mix "
                    "is designed to improve retirement readiness, preserve a dedicated liquidity sleeve, and create a "
                    "single household allocation standard rather than disconnected account-level decisions."
                ),
            },
            {
                "id": "investment-vehicle-selection",
                "title": "Investment Vehicle Selection Highlights",
                "content": section9_content,
            },
            {
                "id": "risk-management",
                "title": "Risk Management Framework",
                "content": (
                    "Risk management is centered on diversification, emergency-liquidity preservation, and regular "
                    "rebalancing if asset-class drift exceeds target bands. The reference diagnosis also highlights "
                    "an insurance review need, because survivorship and income-protection coverage were not verified "
                    "despite a young dependent, mortgage obligations, and reliance on Michael's income."
                ),
            },
            {
                "id": "policy-evaluation",
                "title": "Policy Evaluation Metrics",
                "content": (
                    "The reference policy targets improved retirement feasibility, better tax efficiency, and a more "
                    "stable household allocation process. The underlying example notes that the baseline plan failed "
                    "without allocation changes, while optimized allocations materially improved outcomes but still "
                    "left sensitivity to the family's savings rate and spending discipline."
                ),
            },
            {
                "id": "fee-governance",
                "title": "Fee and Governance Notes",
                "content": (
                    "Governance is handled at the household level, with quarterly review and rebalancing when major "
                    "drift occurs. The reference plan assumes standard advisory-fee treatment and emphasizes a "
                    "repeatable review cadence rather than ad hoc portfolio changes."
                ),
            },
            {
                "id": "disclaimer",
                "title": "Disclaimer and Acknowledgment",
                "content": (
                    "This fallback policy is a reference rendering derived from the Michael & Emily example set and "
                    "is being used because the live UI transformation step failed. It remains subject to investment "
                    "risk, incomplete client-specific data, and future updates to assumptions such as education-cost "
                    "targets and insurance coverage."
                ),
            },
            {
                "id": "tool-log",
                "title": "Tool Execution Log",
                "content": (
                    "Reference case summary: baseline deterministic cashflow failed under the original allocation, "
                    "allocation optimization improved deterministic outcomes, and a Monte Carlo stress view still "
                    "showed material dependence on stronger savings discipline. This UI payload was served via the "
                    "reference fallback because Gemini UI transformation failed."
                ),
            },
        ]

        fallback_payload = {
            "menu": {
                "title": "Carter Family Strategic Wealth Policy",
                "summary": (
                    "Reference fallback policy for retirement readiness, education planning, and household allocation "
                    "discipline. This view is shown because the live UI transformation step was unavailable."
                ),
            },
            "detail": {
                "title": "Carter Family Strategic Wealth Policy",
                "sections": sections,
            },
            "execution": {
                "remedy_name": "Carter Family Strategic Wealth Policy",
                "funding_source": "JPMorgan Chase Bank, N.A. — Account ending in XXX",
                "total_transfer": 675000.0,
            },
        }
        self._append_prompt_log(
            {
                "stage": "ui_transform_reference_fallback",
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "model": self.gemini_model,
                "failure_reason": failure_reason,
                "source_documents": [
                    "examples & discussions/Michael & Emily.md",
                    "examples & discussions/Michael & Emily.client-profile-agent-output.md",
                    "examples & discussions/Michael & Emily.step1-policy.md",
                ],
            }
        )
        return {
            "success": True,
            "model_used": "reference-fallback",
            "ui_policy": fallback_payload,
            "normalization_securities": reference_securities,
            "normalization_portfolio": {
                "currency": "USD",
                "total_value": 675000.0,
            },
            "financial_diagnoses": [
                {
                    "id": "fallback-investment-1",
                    "category": "investment related",
                    "title": "Extreme Asset Allocation Polarization",
                    "description": (
                        "The reference diagnosis flags a barbell portfolio structure: the 401(k) is concentrated in "
                        "US Treasuries while the taxable brokerage is concentrated in US equity. That mismatch drags "
                        "retirement growth, creates concentration risk, and weakens overall household allocation "
                        "discipline."
                    ),
                },
                {
                    "id": "fallback-insurance-1",
                    "category": "insurance related",
                    "title": "Unverified Income Protection",
                    "description": (
                        "The household depends heavily on Michael's earnings while supporting a young child and a "
                        "large mortgage. The reference materials do not confirm life or disability coverage, so "
                        "income-protection risk remains a material open issue."
                    ),
                },
                {
                    "id": "fallback-spending-1",
                    "category": "spending related",
                    "title": "Critical Cash Flow Tightness",
                    "description": (
                        "The reference case shows annual spending nearly consuming minimum take-home pay, leaving "
                        "little room for error or incremental savings. Even after improving the portfolio, long-term "
                        "goal success remains sensitive to stronger savings discipline."
                    ),
                },
                {
                    "id": "fallback-liability-1",
                    "category": "liability related",
                    "title": "Housing Cost Ratio Strain",
                    "description": (
                        "The mortgage, property tax, and insurance burden materially reduce monthly flexibility. The "
                        "debt is not high-cost, but the fixed housing load constrains liquidity and limits how easily "
                        "the family can increase goal-directed savings."
                    ),
                },
            ],
            "ui_generation": {
                "fallback_used": True,
                "source": "reference-fallback",
                "fallback_reason": failure_reason,
                "fallback_label": "Reference fallback content",
                "fallback_message": (
                    "The live UI transformation step failed, so the app is showing a deterministic reference policy "
                    "built from the Michael & Emily example set."
                ),
                "source_documents": [
                    "examples & discussions/Michael & Emily.md",
                    "examples & discussions/Michael & Emily.client-profile-agent-output.md",
                    "examples & discussions/Michael & Emily.step1-policy.md",
                ],
            },
        }
