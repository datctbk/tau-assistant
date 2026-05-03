# tau-assistant — Design Document

## 1. Purpose

`tau-assistant` is an assistant-behavior layer built as an extension package, not core Tau.

It focuses on:
- personal profile and dialectic modeling
- workflow planning/execution
- routines and operational assistant tasks
- memory/session recall helpers

## 2. Core Design Principle

Keep Tau core minimal and stable.

Assistant-specific behavior lives in `tau-assistant` so it can evolve independently
without coupling to core agent loop internals.

## 3. Architecture

```
Tau Core Runtime
  ├─ Provider + Tools + Session
  └─ ExtensionRegistry
       └─ tau-assistant extension
            ├─ profile tools
            ├─ workflow tools
            ├─ subagent orchestration helpers
            ├─ routine management
            └─ memory/insight helpers
```

Optional:
- standalone CLI for long-running assistant routines outside normal REPL flow

## 4. Capability Areas

1. Profile Management
- assistant profile CRUD
- dialectic profile update/infer

2. Workflow Execution
- objective + steps validation
- execution/status/listing

3. Sub-agent Helpers
- single and parallel subagent execution interfaces

4. Memory & Recall
- assistant-level memory add/search
- session recall/search helpers

5. Operational Routines
- define/manage periodic routines
- run due routines

## 5. Data & State

State is extension-owned and intentionally modular:
- assistant profile state
- workflow metadata
- routine definitions
- assistant memory artifacts

Host session data remains owned by Tau core.

## 6. Non-goals

- Not replacing Tau core policy/runtime controls
- Not forcing assistant behavior on all Tau use cases
- Not becoming a monolithic “all-in-core” feature

## 7. Evolution Path

Near-term:
- stronger workflow observability
- tighter integration with task primitives
- improved connectors and delivery paths

Long-term:
- richer planning memory loops
- optional org/team profiles
