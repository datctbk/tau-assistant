# tau-assistant

Personal assistant layer for [tau](https://github.com/datctbk/tau), designed to stay outside tau core.

## Design

- Keep `tau` core minimal (agent loop, tools, providers, sessions, extension API).
- Ship assistant behavior as an extension package:
  - profile management
  - workflow planning and execution
  - cross-connector routines
- Optional standalone CLI for long-running assistant routines.

## Install as Tau Extension

From repository root:

```bash
tau extensions install git:github.com/datctbk/tau-assistant
```

For local development:

```bash
tau extensions install ./tau-assistant
```

## Use via Tau CLI

After loading the extension, these tools are available:

- `assistant_profile_get`
- `assistant_profile_set`
- `assistant_dialectic_profile_get`
- `assistant_dialectic_profile_update`
- `assistant_dialectic_profile_infer`
- `assistant_plan_validate`
- `assistant_workflow_run`
- `assistant_meeting_prep`
- `assistant_subagent_run`
- `assistant_subagent_parallel`
- `assistant_routine_manage`
- `assistant_routine_run_due`
- `assistant_session_search`
- `assistant_session_recall`
- `assistant_web_rank`
- `assistant_workflow_status`
- `assistant_workflow_list`
- `assistant_memory_add`
- `assistant_memory_search`
- `assistant_skill_manage`
- `assistant_checkpoint_create`
- `assistant_insights`
- `assistant_reset_state`

Slash commands:

- `/assistant`
- `/assistant-profile`

## What It Adds

- Assistant profile + dialectic profile management
- Workflow execution and status tracking
- Parallel sub-agent orchestration helpers
- Session recall/memory helpers for assistant flows
- Routine scheduling hooks for recurring work

## Optional Standalone CLI

Run directly:

```bash
python3 tau-assistant/assistant_cli.py --help
```

Examples:

```bash
python3 tau-assistant/assistant_cli.py workflow \
  --objective "prepare release" \
  --steps-json '[{"id":"s1","title":"draft notes"},{"id":"s2","title":"cut release","depends_on":["s1"]}]'
```

```bash
python3 tau-assistant/assistant_cli.py meeting-prep \
  --events-json '[{"id":"evt-1","title":"Weekly Planning","start":"2026-04-16T09:00:00+00:00","attendees":["alice","bob"]}]' \
  --chat-channel team-ops
```

```bash
python3 tau-assistant/assistant_cli.py scheduler \
  --routines-json '[{"id":"r1","title":"daily brief","interval_minutes":60}]' \
  --duration-seconds 15
```
