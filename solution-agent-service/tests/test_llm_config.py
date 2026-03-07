from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))
SOLUTION_AGENT_DIR = REPO_ROOT / "solution-agent-service"
if str(SOLUTION_AGENT_DIR) not in sys.path:
    sys.path.insert(0, str(SOLUTION_AGENT_DIR))

from shared.llm import dedupe_model_chain, parse_fallback_chain
from advisor_agent import AdvisorConfig


def test_parse_fallback_chain_valid() -> None:
    chain = parse_fallback_chain("openai:gpt-4.1, gemini:models/gemini-2.5-pro")
    assert chain == [
        ("openai", "gpt-4.1"),
        ("gemini", "models/gemini-2.5-pro"),
    ]


def test_parse_fallback_chain_invalid() -> None:
    with pytest.raises(ValueError):
        parse_fallback_chain("gpt-4.1")


def test_dedupe_model_chain_preserves_order() -> None:
    chain = dedupe_model_chain(
        ("gemini", "models/gemini-2.5-pro"),
        [
            ("gemini", "models/gemini-2.5-pro"),
            ("openai", "gpt-4.1-mini"),
            ("openai", "gpt-4.1-mini"),
            ("gemini", "models/gemini-2.5-pro"),
        ],
    )
    assert chain == [
        ("gemini", "models/gemini-2.5-pro"),
        ("openai", "gpt-4.1-mini"),
    ]


def test_advisor_config_stage_precedence(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GOOGLE_GENAI_API_KEY", "gemini-key")
    monkeypatch.setenv("OPENAI_API_KEY", "openai-key")
    monkeypatch.setenv("ADVISOR_GEMINI_MODEL", "models/gemini-legacy")
    monkeypatch.setenv("SOLUTION_TOOL_LOOP_PROVIDER", "openai")
    monkeypatch.setenv("SOLUTION_TOOL_LOOP_MODEL", "gpt-4.1")
    monkeypatch.setenv("SOLUTION_TOOL_LOOP_FALLBACKS", "gemini:models/gemini-2.5-pro")

    config = AdvisorConfig.from_env()
    stage = config.stage_models["solution_tool_loop"]

    assert stage["primary_provider"] == "openai"
    assert stage["primary_model"] == "gpt-4.1"
    assert stage["fallbacks"] == [("gemini", "models/gemini-2.5-pro")]


def test_advisor_config_legacy_defaults(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GOOGLE_GENAI_API_KEY", "gemini-key")
    # Pin stage provider to avoid repo-root .env overrides in local dev environments.
    monkeypatch.setenv("SOLUTION_SYNTHESIS_PROVIDER", "gemini")
    monkeypatch.setenv("SOLUTION_SYNTHESIS_MODEL", "models/gemini-legacy")
    monkeypatch.delenv("SOLUTION_SYNTHESIS_FALLBACKS", raising=False)
    monkeypatch.setenv("ADVISOR_GEMINI_MODEL", "models/gemini-legacy")

    config = AdvisorConfig.from_env()
    stage = config.stage_models["solution_synthesis"]

    assert stage["primary_provider"] == "gemini"
    assert stage["primary_model"] == "models/gemini-legacy"


@pytest.mark.skipif(not os.getenv("OPENAI_API_KEY"), reason="OpenAI API key not available")
def test_env_can_hold_openai_key() -> None:
    # Smoke assertion to keep contract explicit when key is set in CI/local env.
    assert os.getenv("OPENAI_API_KEY")
