"""LEARNING ONLY — never imported by app/, no network, no DB.

Two comparisons for passing authenticated identity to an LLM tool:

A. BAD vs GOOD tool schema (identity as a model arg vs hidden ToolRuntime).

B. OLD/internal vs PUBLIC LangChain v1 runtime-context mechanism:

   OLD (internal key)      : build a Runtime(context=actor) and stuff it under
                             config["configurable"][CONFIG_KEY_RUNTIME].
   NEW (public v1 API)     : create_agent(..., context_schema=ActorContext)
                             then agent.astream(input, context=actor).

The public path is the recommended one: it types ToolRuntime.context as
ActorContext and produces NO Pydantic serializer warning ("Expected `none` but
got `ActorContext`") when the tool's injected args are serialized.

Run:  python3 toolruntime_context_demo.py
"""
from __future__ import annotations

import asyncio
import warnings
from typing import Any
from uuid import UUID, uuid4

from langchain.agents import create_agent
from langchain.tools import ToolRuntime, tool
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage
from langchain_core.outputs import ChatResult, ChatGeneration
from pydantic import BaseModel, ConfigDict


class ActorContext(BaseModel):
    model_config = ConfigDict(frozen=True)
    user_id: UUID
    role: str


@tool
def get_budget_bad(project_id: str, user_id: UUID, role: str) -> str:
    """Get the budget (BAD: identity supplied by the model)."""
    return f"budget for {project_id} as {role}"


@tool
async def get_budget_good(project_id: str, runtime: ToolRuntime[ActorContext]) -> str:
    """Get the budget (GOOD: identity comes from the injected runtime context)."""
    actor: ActorContext = runtime.context
    return f"budget for {project_id} as {actor.role}"


class FakeModel(BaseChatModel):
    responses: list[AIMessage]

    def _generate(self, messages: list[Any], stop=None, run_manager=None, **kwargs) -> ChatResult:
        m = self.responses.pop(0) if self.responses else AIMessage(content="Done.")
        return ChatResult(generations=[ChatGeneration(message=m)])

    def bind_tools(self, tools: Any, **kwargs: Any) -> "FakeModel":
        return self

    @property
    def _llm_type(self) -> str:
        return "fake"


def _count_warnings(run) -> list[str]:
    with warnings.catch_warnings(record=True) as rec:
        warnings.simplefilter("always")
        run()
    return [str(w.message)[:70] for w in rec if "Expected" in str(w.message)]


def main() -> None:
    print("=" * 74)
    print("PART A - BAD vs GOOD tool schema")
    print("=" * 74)
    print("BAD  :", get_budget_bad.args)
    print("GOOD :", get_budget_good.args)
    print("  GOOD hides runtime; no identity field is visible to the model.")
    print()

    actor = ActorContext(user_id=uuid4(), role="admin")
    tool_call = AIMessage(
        content="",
        tool_calls=[{"name": "get_budget_old", "args": {"project_id": "PRJ-2026-0001"}, "id": "c1", "type": "tool_call"}],
    )
    final = AIMessage(content="budget report ready")

    print("=" * 74)
    print("PART B - OLD/internal CONFIG_KEY_RUNTIME vs PUBLIC context API")
    print("=" * 74)

    # OLD path: an UNTYPED `runtime: ToolRuntime` param + the internal
    # CONFIG_KEY_RUNTIME key. This is what the earliest ICE production code did
    # and it reproduced the Pydantic serializer warning.
    @tool
    async def get_budget_old(project_id: str, runtime: ToolRuntime) -> str:
        """Get the budget (OLD mechanism, untyped runtime)."""
        return f"budget for {project_id} as {runtime.context.role}"

    def run_old() -> None:
        from langgraph.runtime import CONFIG_KEY_RUNTIME, Runtime

        agent = create_agent(model=FakeModel(responses=[tool_call, final]), tools=[get_budget_old], system_prompt="t")
        config = {"configurable": {CONFIG_KEY_RUNTIME: Runtime(context=actor)}}
        asyncio.run(agent.ainvoke({"messages": [("user", "hi")]}, config=config))

    # NEW path: public context_schema + context= + a TYPED runtime param.
    tool_call_new = AIMessage(
        content="",
        tool_calls=[{"name": "get_budget_good", "args": {"project_id": "PRJ-2026-0001"}, "id": "c1", "type": "tool_call"}],
    )

    def run_public() -> None:
        agent = create_agent(
            model=FakeModel(responses=[tool_call_new, final]),
            tools=[get_budget_good],
            system_prompt="t",
            context_schema=ActorContext,
        )
        asyncio.run(agent.ainvoke({"messages": [("user", "hi")]}, context=actor))

    old_warns = _count_warnings(run_old)
    public_warns = _count_warnings(run_public)
    print("  OLD (internal key, untyped runtime)  serializer warnings:", len(old_warns), old_warns[:1])
    print("  PUBLIC (context_schema + typed runtime) warnings        :", len(public_warns), public_warns[:1])
    print()

    print("Recommendation:")
    print("  Use create_agent(context_schema=ActorContext) and pass context=actor")
    print("  at invocation. Type tool params as `runtime: ToolRuntime[ActorContext]`.")
    print("  This is the supported LangChain v1 public context API and avoids the")
    print("  Pydantic 'Expected `none` but got ActorContext' serializer warning.")
    print("  The CONFIG_KEY_RUNTIME / manual Runtime() path is an internal LangGraph")
    print("  mechanism and is NOT used by production ICE code.")
    print()
    print("Identity remains: HTTP user -> ActorContext -> runtime context ->")
    print("ToolRuntime.context -> tool -> deterministic ICE authorization.")


if __name__ == "__main__":
    main()
