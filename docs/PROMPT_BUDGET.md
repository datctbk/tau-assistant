# TAU Assistant Prompt Budget

Concrete budget for a tiny-core architecture with extension-driven capabilities.

## Goals

- Keep prompt assembly predictable and low-latency.
- Prevent context bloat from memory/tool over-injection.
- Preserve room for model output quality.

## Default Budget (Per Turn)

Target input range: `1,400-3,300` tokens.

1. System core: `250-450`
2. Active task + latest user message: `120-300`
3. Recent conversation window: `400-900`
4. Memory injection (compressed): `250-600`
5. Tool exposure (dynamic subset): `300-900`
6. Safety/policy add-ons: `80-220`
7. Reserved output budget: `800-1,500` (do not consume in input)

## Hard Caps

1. Max input tokens: `4,000`
2. Memory block cap: `600`
3. Tool block cap: `900`
4. Max fully-described tools: `6`
5. Max listed tools total: `12`

If over budget, trim in this exact order:
1. Oldest conversation chunks
2. Memory detail lines
3. Tool schema detail (keep only name + one-line description)
4. Non-critical policy prose

## Operating Modes

1. `light` (simple Q&A): `1,200-1,800` input
2. `standard` (coding/tasks): `1,800-2,800` input
3. `heavy` (workflow/planning): `2,800-4,000` input

## Memory Injection Policy

Default inject only compressed memory:
1. Top 3 user preferences
2. Top 3 project facts
3. Top 2 session recall summaries

Never inject full memory indexes by default. Load full topic content only on explicit need.

## Tool Exposure Policy

Always include core tools:
- filesystem read/write/search
- shell execution
- memory add/search

Conditionally include extension tools:
- workflow tools only for plan/execute intent
- routine tools only for scheduling intent
- subagent tools only for delegation intent
- web ranking only for web result processing intent

## Prompt Assembly Flow

1. Build compact `system_core`.
2. Add current user intent and task objective.
3. Add compressed recent context (most recent first).
4. Add compressed memory context (ranked).
5. Add dynamic tool block (top 6 full + up to 6 compact).
6. Enforce cap and trim by policy.
7. Dispatch to model.

## Starter Config

Use these defaults first, tune after telemetry:

```text
MAX_INPUT_TOKENS=3200
SYSTEM_BUDGET=350
TASK_BUDGET=220
RECENT_CONTEXT_BUDGET=800
MEMORY_BUDGET=500
TOOLS_BUDGET=700
POLICY_BUDGET=160
OUTPUT_RESERVE=1000
MAX_TOOLS_TOTAL=12
MAX_TOOLS_FULL_SCHEMA=6
```

## Quality Checks

Before sending prompt:
1. Confirm input <= max cap.
2. Confirm output reserve remains available.
3. Confirm no duplicate memory lines.
4. Confirm only relevant tools are exposed.
5. Confirm recent context includes latest user instruction.

## Telemetry To Track

1. Input token count by section
2. Output token count
3. Latency by mode (`light|standard|heavy`)
4. Tool-call success rate
5. Retry rate due to missing context

Use telemetry weekly to rebalance section budgets.
