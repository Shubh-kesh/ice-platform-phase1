"""LEARNING ONLY — never imported by app/, no network, no DB.

Structured-output exploration for the ICE Copilot's CopilotInsight model.

The course taught ProviderStrategy (provider-native structured output) vs
ToolStrategy (synthetic tool call). On the PINNED stack (langchain 1.3.15 /
langchain-core 1.5.5) those map to `with_structured_output(method=...)`:

  ProviderStrategy  -> method="json_schema"     (provider-native response_format)
  ToolStrategy      -> method="function_calling" (synthetic tool-call wrapper)

This demo is deterministic and offline: it builds each provider's chat model
(no network), inspects what the stack can TELL us about structured-output
support, and shows the schemas/config. It never invokes a provider.

Run:  python3 structured_output_demo.py
"""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from langchain.chat_models import init_chat_model
from langchain_openai import ChatOpenAI


class CopilotInsight(BaseModel):
    """A tool-grounded project insight the ICE Copilot may emit (optional)."""

    summary: str = Field(description="One or two sentences, grounded in tool results.")
    severity: Literal["info", "ok", "watch", "attention", "critical"] | None = Field(
        default=None, description="Optional severity label for the insight card."
    )
    findings: list[str] = Field(default_factory=list, description="Tool-backed points.")
    recommended_actions: list[str] = Field(
        default_factory=list, description="Suggested next steps (read-only)."
    )


def _build(provider: str, model: str) -> object:
    if provider == "openrouter":
        return ChatOpenAI(model=model, temperature=0, api_key="sk-dummy",
                          base_url="https://openrouter.ai/api/v1")
    return init_chat_model(f"{provider}:{model}", temperature=0, api_key="sk-dummy")


def main() -> None:
    print("=" * 74)
    print("CopilotInsight structured-output schema")
    print("=" * 74)
    schema = CopilotInsight.model_json_schema()
    print("  model:", schema["title"], "| fields:", ", ".join(schema["properties"]))
    print()

    providers = [
        ("openai", "gpt-5-mini"),
        ("anthropic", "claude-3-5-haiku-20241022"),
        ("groq", "llama-3.3-70b-versatile"),
        ("openrouter", "nvidia/nemotron-3-super-120b-a12b:free"),
    ]

    print("=" * 74)
    print("Provider capability profile (offline .profile / stack signals)")
    print("=" * 74)
    for provider, model in providers:
        chat = _build(provider, model)
        profile = getattr(chat, "profile", None)
        support = "UNKNOWN (no .profile)"
        if isinstance(profile, dict):
            support = (
                f"tool_calling={profile.get('tool_calling')} "
                f"structured_output={profile.get('structured_output')} "
                f"reasoning={profile.get('reasoning_output')}"
            )
        print(f"  {provider:10s} {type(chat).__name__:14s} {support}")
        with_structured = getattr(chat, "with_structured_output", None)
        if with_structured is not None:
            for method in ("json_schema", "function_calling"):
                try:
                    runnable = with_structured(CopilotInsight, method=method)
                    print(f"      with_structured_output(method='{method}') -> {type(runnable).__name__}")
                except Exception as exc:  # pragma: no cover
                    print(f"      method='{method}' -> FAIL {type(exc).__name__}: {str(exc)[:70]}")
    print()

    print("=" * 74)
    print("Strategy mapping (course vocabulary -> pinned stack)")
    print("=" * 74)
    print("  ProviderStrategy ~ with_structured_output(method='json_schema')")
    print("    - uses the provider's NATIVE response_format/json-schema feature")
    print("    - best where the provider advertises structured_output=True")
    print("    - OpenAI supports it (profile structured_output=True).")
    print("  ToolStrategy     ~ with_structured_output(method='function_calling')")
    print("    - wraps the schema in a SYNTHETIC tool call the model must fill")
    print("    - works on providers/models without a native JSON schema feature")
    print("    - the COURSE warning: combining function_calling with REAL tools in")
    print("      one agent can be unreliable on some models - test before trusting.")
    print()

    print("=" * 74)
    print("Multi-provider recommendation (documented, offline)")
    print("=" * 74)
    print("  openai     : json_schema preferred (profile confirms support).")
    print("  anthropic  : no .profile; prefer function_calling (Anthropic has no")
    print("               native json-schema response_format in this integration).")
    print("  groq       : tool_calling=True but no advertised structured_output;")
    print("               test json_schema, fall back to function_calling.")
    print("  openrouter : ChatOpenAI with custom base_url -> .profile is None; the")
    print("               support depends on the upstream model, so prefer the")
    print("               robust function_calling unless the model is known-good.")
    print()
    print("  ICE product note: CopilotInsight stays OPTIONAL and LEARNING-ONLY in")
    print("  AI-1. /assistant/chat is not coupled to structured output, so this")
    print("  choice does not affect the shipping chat surface.")


if __name__ == "__main__":
    main()
