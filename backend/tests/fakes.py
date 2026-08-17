"""
Deterministic fake chat model for ICE Copilot tests.

Scripts the model's reply sequence so agent-level tests never touch a live
provider (no OpenAI key, no network). Implementations needed by the harness:
`bind_tools` (create_agent binds the tool schemas), `_generate` (one-shot
answers), and `_stream` (word-by-word chunks so streaming tests are real).
"""
from __future__ import annotations

from typing import Any, Iterator

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, AIMessageChunk
from langchain_core.outputs import ChatGeneration, ChatGenerationChunk, ChatResult


class FakeChatModel(BaseChatModel):
    """A chat model that replays a scripted list of AIMessages.

    `responses` is consumed in order; an empty list yields a final "Done."
    reply. AIMessages carrying `tool_calls` drive the agent into the ICE tools
    exactly like a real model would, without any provider dependency. Optional
    `usage` metadata is attached to the final chunk so metrics extraction can
    be tested.
    """

    responses: list[AIMessage] = []
    usage: dict[str, int] = {}
    # Records every input message list the model was called with (the full
    # messages, not just types) — used by memory tests to prove history
    # propagation across turns/threads.
    calls: list[list[Any]] = []

    def _record(self, messages: list[Any]) -> None:
        self.calls.append(list(messages))

    def _generate(
        self,
        messages: list[Any],
        stop: list[str] | None = None,
        run_manager: Any = None,
        **kwargs: Any,
    ) -> ChatResult:
        self._record(messages)
        message = self.responses.pop(0) if self.responses else AIMessage(content="Done.")
        return ChatResult(generations=[ChatGeneration(message=message)])

    def _stream(
        self,
        messages: list[Any],
        stop: list[str] | None = None,
        run_manager: Any = None,
        **kwargs: Any,
    ) -> Iterator[ChatGenerationChunk]:
        self._record(messages)
        message = self.responses.pop(0) if self.responses else AIMessage(content="Done.")
        if getattr(message, "tool_calls", None):
            # Tool-call turns deliver the whole request in one chunk (content
            # is empty; the tool call is the signal the model chose a tool).
            yield ChatGenerationChunk(
                message=AIMessageChunk(content="", tool_calls=message.tool_calls, id=message.id)
            )
            return
        words = str(message.content).split(" ")
        for index, word in enumerate(words):
            last = index == len(words) - 1
            chunk = AIMessageChunk(content=word + ("" if last else " "), id=message.id)
            if last and self.usage:
                chunk = AIMessageChunk(
                    content=word, id=message.id, usage_metadata=dict(self.usage)
                )
            yield ChatGenerationChunk(message=chunk)

    def bind_tools(self, tools: Any, **kwargs: Any) -> "FakeChatModel":
        # The harness binds tool schemas to the model; a fake accepts and
        # ignores them (the scripted responses already carry any tool_calls).
        return self

    @property
    def _llm_type(self) -> str:
        return "fake"
