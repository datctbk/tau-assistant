# TAU Presentation Deck

Use this as your speaking script.  
Format: 8 core slides + live demo + backup Q&A notes.

## Slide 1 - Title
**TAU: Tiny Core, Powerful Extensions**

- Mission: keep core minimal, move advanced capabilities to extensions.
- Tagline: stable foundation, fast innovation.

**Speaker notes**
- "TAU is designed with a simple philosophy: tiny core for reliability, extensions for capability growth."
- "This helps us scale features without bloating the runtime."

## Slide 2 - Problem
**Why This Architecture**

- Many assistants become too heavy over time.
- Large base systems increase maintenance cost and token overhead.
- Hard to evolve quickly without regressions.

**Speaker notes**
- "We wanted a system that remains understandable and operable as it grows."
- "The architecture itself is our first safety and performance optimization."

## Slide 3 - Core Design
**Core vs Extension Boundary**

- TAU Core: session loop, tool runtime, safety contracts.
- Extensions: memory, assistant workflows, web ranking, routines, subagents.
- Failure isolation: extension issues should not break core operation.

**Speaker notes**
- "Core handles execution guarantees; extensions provide domain behavior."
- "This gives us clean ownership and easier troubleshooting."

## Slide 4 - What We Built
**tau-assistant Capabilities**

- User profile + dialectic profile modeling.
- Workflow planning, execution, recovery, handoff summaries.
- Skill manager + workflow-to-skill promotion + auto-improvement loop.
- Routine scheduler-to-delivery integration.
- Session search + summary recall.
- Subagent delegation and parallel workstreams.

**Speaker notes**
- "We moved from a simple chat assistant to an operational assistant platform."
- "Each feature is modular and testable."

## Slide 5 - Memory Strategy
**Persistent Memory with Discipline**

- Uses `tau-memory` for structured memory types: `user`, `feedback`, `project`, `reference`.
- Assistant memory tools for task-oriented retrieval and writes.
- Strict rule: write memory only after successful tool outcomes.

**Speaker notes**
- "This avoids false memory states from failed actions."
- "Memory is useful, but only if it is trustworthy."

## Slide 6 - Reliability and Safety
**Production Readiness Features**

- Policy profiles: `dev`, `balanced`, `strict`.
- Workflow resume/recovery + checkpoints.
- Insights and audit/event logs.
- Reset capability: `assistant_reset_state` with safe `dry_run`.

**Speaker notes**
- "We prioritize operational safety, not just model intelligence."
- "Reset and audit are critical for demos, testing, and incident handling."

## Slide 7 - Live Demo
**End-to-End Scenario (3-5 minutes)**

- Prompt: "Create my daily morning brief workflow."
- Show: workflow run -> handoff summary -> optional skill promotion.
- Configure routine delivery and run due routines.
- Show memory/search recall of generated outputs.

**Speaker notes**
- "This demonstrates planning, execution, persistence, and delivery in one loop."
- "Audience sees real assistant operations, not just one-off chat."

## Slide 8 - Roadmap and Priorities
**What’s Next**

- P0: harden evaluation gating and regression protections.
- P1: improve ranking quality and behavior consistency.
- P2: deeper user modeling and adaptive behavior tuning.

**Speaker notes**
- "We optimize for reliability first, quality second, complexity last."
- "The roadmap preserves the tiny-core philosophy."

---

## Demo Script (Command-Oriented)

1. Set context:
- "I will show TAU creating and operating a morning brief assistant flow."

2. Run assistant workflow:
- Use `assistant_workflow_run` with short 2-3 dependency steps.

3. Promote workflow to skill:
- Set `promote_to_skill=true`.

4. Create routine:
- Use `assistant_routine_manage(action=create, ...)`.

5. Trigger delivery:
- Use `assistant_routine_run_due`.

6. Show persistence:
- Use `assistant_memory_search` and `assistant_session_search`.

7. Optional reset demo:
- `assistant_reset_state(dry_run=true)` then explain safe apply mode.

## Likely Q&A Answers

**Q: Why not put everything in core?**  
A: Core bloat slows iteration and increases blast radius. Extension boundary preserves stability.

**Q: How do you prevent memory hallucination?**  
A: Memory writes are restricted to post-success actions, with structured types and explicit traceability.

**Q: How do you handle failure in workflows?**  
A: Step-level checkpoints, resumable workflow state, and policy-driven failure behavior.

**Q: Is this only for coding?**  
A: No. The architecture is generic; coding is one domain where reliable execution and memory matter a lot.

## One-Line Closing

"TAU is a reliable assistant platform: tiny core for trust, extensions for capability."
