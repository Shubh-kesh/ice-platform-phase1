# TodoListMiddleware — planning for complex reviews

**LEARNING ONLY** — no network, no DB.

## Hypothesis

For a complex multi-domain review, planning the work with a todo list can
improve coverage. TodoListMiddleware adds a `write_todos` planning tool.

## Setup

`todo_middleware_demo.py` runs the same complex-review question with and
without the middleware (deterministic fake model) and reports mechanics.

Scoring rubric (for a live comparison):
health +1 · schedule +1 · budget +1 (role permitting) · inventory +1 ·
procurement +1 (role permitting) · recommendations grounded in data +1 (max 6).

## Observations

The middleware adds the planning tool; the agent's behavior with a real model
depends on whether it decides to plan. Todo planning is NOT authorization — all
ICE tools still self-authorize.

## Conclusion

OPTIONAL feature (`ICE_AI_TODO_ENABLED=false` default). Enable for complex
review mode if a live comparison shows better rubric scores at acceptable cost.
