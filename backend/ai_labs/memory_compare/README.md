# Memory compare — stateless vs InMemorySaver vs summarization

**LEARNING ONLY** — never imported by `app/`, no network, no DB.

## Hypothesis

A checkpointer keyed by `thread_id` is what turns a stateless model into a
multi-turn conversational agent. Summarization replaces the oldest context with
a compressed summary instead of sending everything every time.

## Setup

`memory_compare_demo.py` runs the SAME fake model + scratch tool + user/thread
through three strategies:

- A. **stateless** (`create_agent` without a checkpointer)
- B. **InMemorySaver** + `thread_id`
- C. **InMemorySaver + SummarizationMiddleware** (low trigger)

The fake model records the messages it is given on each call.

## Experiment / metrics

- model-call input message types per call (`call#2` in B shows q1+a1; in A it
  does not).
- whether turn-1 content is visible on turn-2 input.
- C also reports the summary model being called (extra cost).

## Observations

- A: `call#2` = `[SystemMessage, HumanMessage(q2)]` — forgotten.
- B: `call#2` = `[System, Human(q1), AIMessage(a1), Human(q2)]` — remembered.
- C: `call#2` includes the summary instead of the oldest messages.

## Conclusion

Memory is message/context state only; identity/authorization is separate
(ActorContext per request). Summarization trades context fidelity for size and
adds a summarization-model call — only adopt where measurements justify it.
