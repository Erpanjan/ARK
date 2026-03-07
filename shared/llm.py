"""Provider-agnostic LLM abstraction for Gemini and OpenAI."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence, Tuple

from google import genai
from google.genai import types as gemini_types

try:
    from openai import OpenAI
except ImportError:  # pragma: no cover - optional until selected provider is OpenAI
    OpenAI = None  # type: ignore[assignment]


@dataclass
class ToolCall:
    """Normalized tool call emitted by an assistant response."""

    id: str
    name: str
    arguments: Dict[str, Any] = field(default_factory=dict)


@dataclass
class ToolSchema:
    """Provider-neutral tool function schema."""

    name: str
    description: str
    parameters: Dict[str, Any] = field(default_factory=dict)
    required: List[str] = field(default_factory=list)


@dataclass
class LLMMessage:
    """Provider-neutral chat message."""

    role: str
    content: str = ""
    tool_calls: List[ToolCall] = field(default_factory=list)
    tool_call_id: Optional[str] = None
    name: Optional[str] = None


@dataclass
class LLMGenerateRequest:
    """Normalized generation request."""

    messages: List[LLMMessage]
    system_instruction: str = ""
    temperature: float = 0.2
    tools: List[ToolSchema] = field(default_factory=list)


@dataclass
class LLMGenerateResult:
    """Normalized generation response."""

    provider: str
    model: str
    text: str
    messages: List[LLMMessage]
    tool_calls: List[ToolCall]
    raw: Any = None


class LLMAdapter:
    """Adapter interface."""

    provider: str

    def generate(self, request: LLMGenerateRequest, model: str) -> LLMGenerateResult:
        raise NotImplementedError


class GeminiAdapter(LLMAdapter):
    """Google Gemini adapter."""

    provider = "gemini"

    def __init__(self, api_key: str, timeout_ms: int = 90000):
        self.client = genai.Client(
            api_key=api_key,
            http_options=gemini_types.HttpOptions(timeout=timeout_ms),
        )

    def _to_gemini_tools(self, tools: Sequence[ToolSchema]) -> List[gemini_types.Tool]:
        if not tools:
            return []

        mapped: List[gemini_types.FunctionDeclaration] = []
        for tool in tools:
            params: Dict[str, Any] = {
                "type": "OBJECT",
                "properties": tool.parameters or {},
            }
            if tool.required:
                params["required"] = list(tool.required)
            mapped.append(
                gemini_types.FunctionDeclaration(
                    name=tool.name,
                    description=tool.description,
                    parameters=params,
                )
            )
        return [gemini_types.Tool(function_declarations=mapped)]

    def _to_gemini_messages(self, messages: Sequence[LLMMessage]) -> List[gemini_types.Content]:
        rows: List[gemini_types.Content] = []
        for message in messages:
            role = str(message.role or "").strip().lower()
            if role == "assistant":
                parts: List[gemini_types.Part] = []
                if message.content:
                    parts.append(gemini_types.Part(text=message.content))
                for tool_call in message.tool_calls:
                    parts.append(
                        gemini_types.Part(
                            function_call=gemini_types.FunctionCall(
                                name=tool_call.name,
                                args=tool_call.arguments,
                            )
                        )
                    )
                if not parts:
                    continue
                rows.append(gemini_types.Content(role="model", parts=parts))
                continue

            if role == "tool":
                payload: Dict[str, Any] = {}
                if message.content:
                    try:
                        parsed = json.loads(message.content)
                        if isinstance(parsed, dict):
                            payload = parsed
                    except json.JSONDecodeError:
                        payload = {"text": message.content}
                rows.append(
                    gemini_types.Content(
                        role="user",
                        parts=[
                            gemini_types.Part(
                                function_response=gemini_types.FunctionResponse(
                                    name=str(message.name or "tool"),
                                    response=payload,
                                )
                            )
                        ],
                    )
                )
                continue

            # Gemini supports user/model role; default all non-assistant/tool to user.
            rows.append(
                gemini_types.Content(role="user", parts=[gemini_types.Part(text=message.content or "")])
            )
        return rows

    def generate(self, request: LLMGenerateRequest, model: str) -> LLMGenerateResult:
        cfg: Dict[str, Any] = {
            "system_instruction": request.system_instruction,
            "temperature": request.temperature,
        }
        if request.tools:
            cfg["tools"] = self._to_gemini_tools(request.tools)

        response = self.client.models.generate_content(
            model=model,
            contents=self._to_gemini_messages(request.messages),
            config=gemini_types.GenerateContentConfig(**cfg),
        )

        text_parts: List[str] = []
        tool_calls: List[ToolCall] = []
        out_messages: List[LLMMessage] = []

        candidates = getattr(response, "candidates", None) or []
        for candidate in candidates:
            content = getattr(candidate, "content", None)
            if content is None:
                continue

            assistant_content: List[str] = []
            assistant_calls: List[ToolCall] = []
            for part in getattr(content, "parts", None) or []:
                text = getattr(part, "text", None)
                if text:
                    text_parts.append(str(text))
                    assistant_content.append(str(text))

                fc = getattr(part, "function_call", None)
                if fc is not None:
                    fc_id = str(getattr(fc, "id", "") or "")
                    if not fc_id:
                        fc_id = f"call_{len(tool_calls)+1}"
                    args = getattr(fc, "args", None)
                    if isinstance(args, dict):
                        parsed_args = args
                    else:
                        try:
                            parsed_args = dict(args or {})
                        except Exception:  # pylint: disable=broad-except
                            parsed_args = {}
                    call = ToolCall(
                        id=fc_id,
                        name=str(getattr(fc, "name", "") or ""),
                        arguments=parsed_args,
                    )
                    tool_calls.append(call)
                    assistant_calls.append(call)

            if assistant_content or assistant_calls:
                out_messages.append(
                    LLMMessage(
                        role="assistant",
                        content="\n".join(assistant_content).strip(),
                        tool_calls=assistant_calls,
                    )
                )

        joined_text = "\n".join([segment for segment in text_parts if segment]).strip()
        if not joined_text and getattr(response, "text", None):
            joined_text = str(response.text).strip()

        return LLMGenerateResult(
            provider=self.provider,
            model=model,
            text=joined_text,
            messages=out_messages,
            tool_calls=tool_calls,
            raw=response,
        )


class OpenAIAdapter(LLMAdapter):
    """OpenAI Chat Completions adapter."""

    provider = "openai"

    def __init__(self, api_key: str, timeout_s: int = 90):
        if OpenAI is None:
            raise RuntimeError("openai package is not installed")
        self.client = OpenAI(api_key=api_key, timeout=timeout_s)

    def _to_openai_tools(self, tools: Sequence[ToolSchema]) -> List[Dict[str, Any]]:
        rows: List[Dict[str, Any]] = []
        for tool in tools:
            schema = {
                "type": "object",
                "properties": tool.parameters or {},
            }
            if tool.required:
                schema["required"] = list(tool.required)
            rows.append(
                {
                    "type": "function",
                    "function": {
                        "name": tool.name,
                        "description": tool.description,
                        "parameters": schema,
                    },
                }
            )
        return rows

    def _to_openai_messages(self, messages: Sequence[LLMMessage], system_instruction: str) -> List[Dict[str, Any]]:
        rows: List[Dict[str, Any]] = []
        if system_instruction:
            rows.append({"role": "system", "content": system_instruction})

        for message in messages:
            role = str(message.role or "").strip().lower()
            if role == "assistant":
                row: Dict[str, Any] = {"role": "assistant", "content": message.content or ""}
                if message.tool_calls:
                    row["tool_calls"] = [
                        {
                            "id": call.id,
                            "type": "function",
                            "function": {
                                "name": call.name,
                                "arguments": json.dumps(call.arguments, ensure_ascii=True),
                            },
                        }
                        for call in message.tool_calls
                    ]
                rows.append(row)
                continue

            if role == "tool":
                rows.append(
                    {
                        "role": "tool",
                        "tool_call_id": str(message.tool_call_id or "tool_call_missing"),
                        "name": str(message.name or "tool"),
                        "content": message.content or "{}",
                    }
                )
                continue

            rows.append({"role": "user", "content": message.content or ""})
        return rows

    def generate(self, request: LLMGenerateRequest, model: str) -> LLMGenerateResult:
        params: Dict[str, Any] = {
            "model": model,
            "messages": self._to_openai_messages(request.messages, request.system_instruction),
            "temperature": request.temperature,
        }
        if request.tools:
            params["tools"] = self._to_openai_tools(request.tools)
            params["tool_choice"] = "auto"

        response = self.client.chat.completions.create(**params)

        text_parts: List[str] = []
        all_calls: List[ToolCall] = []
        out_messages: List[LLMMessage] = []

        for idx, choice in enumerate(response.choices or []):
            message = choice.message
            assistant_text = str(message.content or "").strip()
            if assistant_text:
                text_parts.append(assistant_text)

            calls: List[ToolCall] = []
            for tool_call in (message.tool_calls or []):
                fn = getattr(tool_call, "function", None)
                if fn is None:
                    continue
                raw_args = getattr(fn, "arguments", "") or ""
                parsed_args: Dict[str, Any] = {}
                if isinstance(raw_args, str) and raw_args.strip():
                    try:
                        loaded = json.loads(raw_args)
                        if isinstance(loaded, dict):
                            parsed_args = loaded
                    except json.JSONDecodeError:
                        parsed_args = {}
                call = ToolCall(
                    id=str(getattr(tool_call, "id", "") or f"call_{idx + 1}_{len(calls)+1}"),
                    name=str(getattr(fn, "name", "") or ""),
                    arguments=parsed_args,
                )
                calls.append(call)
                all_calls.append(call)

            if assistant_text or calls:
                out_messages.append(
                    LLMMessage(role="assistant", content=assistant_text, tool_calls=calls)
                )

        return LLMGenerateResult(
            provider=self.provider,
            model=model,
            text="\n".join([segment for segment in text_parts if segment]).strip(),
            messages=out_messages,
            tool_calls=all_calls,
            raw=response,
        )


class LLMClientFactory:
    """Factory for provider adapters."""

    @staticmethod
    def create(
        provider: str,
        google_api_key: str,
        openai_api_key: str,
        timeout_ms: int = 90000,
    ) -> LLMAdapter:
        normalized = str(provider or "").strip().lower()
        if normalized == "gemini":
            if not google_api_key:
                raise ValueError("Gemini API key missing (set GOOGLE_GENAI_API_KEY or GEMINI_API_KEY)")
            return GeminiAdapter(api_key=google_api_key, timeout_ms=timeout_ms)
        if normalized == "openai":
            if not openai_api_key:
                raise ValueError("OpenAI API key missing (set OPENAI_API_KEY)")
            timeout_s = max(1, int(timeout_ms / 1000))
            return OpenAIAdapter(api_key=openai_api_key, timeout_s=timeout_s)
        raise ValueError(f"Unsupported LLM provider: {provider}")


def parse_fallback_chain(raw: str) -> List[Tuple[str, str]]:
    """Parse fallback list in `provider:model` CSV format."""
    rows: List[Tuple[str, str]] = []
    for token in str(raw or "").split(","):
        item = token.strip()
        if not item:
            continue
        if ":" not in item:
            raise ValueError(
                f"Invalid fallback entry '{item}'. Expected format provider:model"
            )
        provider, model = item.split(":", 1)
        provider = provider.strip().lower()
        model = model.strip()
        if not provider or not model:
            raise ValueError(
                f"Invalid fallback entry '{item}'. Expected format provider:model"
            )
        rows.append((provider, model))
    return rows


def dedupe_model_chain(primary: Tuple[str, str], fallbacks: Sequence[Tuple[str, str]]) -> List[Tuple[str, str]]:
    """Build ordered unique model chain."""
    chain: List[Tuple[str, str]] = []
    for candidate in [primary, *fallbacks]:
        provider = str(candidate[0] or "").strip().lower()
        model = str(candidate[1] or "").strip()
        if not provider or not model:
            continue
        row = (provider, model)
        if row not in chain:
            chain.append(row)
    return chain
