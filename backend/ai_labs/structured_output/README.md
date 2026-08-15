# Structured output — CopilotInsight strategy exploration

**LEARNING ONLY** — never imported by `app/`, no network, no DB.

## Question

The course taught `ProviderStrategy` vs `ToolStrategy` for structured output.
How does that map onto the pinned stack, and what should ICE use per provider?

## Key finding (pinned stack: langchain 1.3.15 / core 1.5.5)

`ProviderStrategy`/`ToolStrategy` objects do **not** exist in `langchain.agents`
on this stack. The equivalent control is
`model.with_structured_output(schema, method=...)` where:

- `method="json_schema"` ≈ **ProviderStrategy** — provider-native
  `response_format`/JSON-schema feature.
- `method="function_calling"` ≈ **ToolStrategy** — wraps the schema in a
  synthetic tool call the model must fill.

`create_agent` also accepts `response_format=<schema>` directly.

## Verified offline (script `structured_output_demo.py`)

| Provider | Chat class | .profile signals | Recommended method |
|---|---|---|---|
| openai | ChatOpenAI | tool_calling=True, structured_output=True | `json_schema` |
| anthropic | ChatAnthropic | no .profile | `function_calling` |
| groq | ChatGroq | tool_calling=True, structured_output=None | test `json_schema`, fallback `function_calling` |
| openrouter | ChatOpenAI (custom base_url) | no .profile (depends on upstream model) | `function_calling` |

Course caveat carried forward: `function_calling` combined with **real tools**
in one agent can be unreliable on some models — verify against the chosen
model before trusting it.

## ICE recommendation

`CopilotInsight` stays **optional and learning-only** in AI-1;
`/assistant/chat` is not coupled to structured output. When it is adopted,
prefer `json_schema` for OpenAI and `function_calling` elsewhere, and test the
specific model + provider before enabling.
