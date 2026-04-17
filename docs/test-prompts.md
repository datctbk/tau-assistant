# tau-assistant Test Prompts

Use these prompts to validate current tau-assistant capabilities from Phase A through Phase D.

## How To Use

- Run prompts in order for a full smoke pass.
- For each prompt, verify the expected result.
- Record pass or fail and short notes.

## Core Prompt Checklist

1. Planner and dependency ordering
Prompt:
Create a 7-step plan to ship a small feature with dependencies between design, implementation, tests, and release notes. Show step IDs and dependency graph.
Expected:
- Steps are dependency-valid.
- No cycle errors.

2. Workflow runner and checkpoints
Prompt:
Execute this plan step by step and save a checkpoint after each completed step.
Expected:
- Step completion events are emitted.
- Checkpoints are saved per completed step.

3. Manual checkpoint command
Prompt:
/checkpoint sprint-auth-refactor
Expected:
- Named checkpoint saved with session metadata.
- Audit/event record exists.

4. Policy low-risk allow
Prompt:
Read project files and summarize architecture only. Do not modify anything.
Expected:
- No approval required for read-only path.

5. Policy medium or high approval
Prompt:
Apply code changes to multiple files and run commands that modify state.
Expected:
- Approval request appears before execution.
- Deny blocks execution.
- Approve allows execution.

6. Routine due detection
Prompt:
Create two routines: daily brief every 1440 minutes and standup prep every 720 minutes. Tell me which ones are due now.
Expected:
- Due list aligns with interval and last-run state.

7. Scheduler callback firing
Prompt:
Start scheduler polling every 1 second for due routines and record which routine IDs fire within 10 seconds.
Expected:
- Due callback fires.
- Routine last-run state updates.

8. Connector router basic routing
Prompt:
Register calendar, note, chat, and email connectors. Route one action to each and show responses.
Expected:
- Each known connector returns success.
- Unknown connector returns clean error.

9. Cross-connector meeting prep
Prompt:
Run meeting prep for upcoming events: create prep notes, post chat update, and send digest email.
Expected:
- Notes are created.
- Chat update is posted.
- Digest email is sent when recipient is configured.

10. Digest validation guard
Prompt:
Run meeting prep with email digest enabled but no recipient.
Expected:
- Clear validation error for missing recipient.

11. Memory confidence and conflict metadata
Prompt:
Save memory about deployment preference with confidence 0.92, then save another memory with same title but updated preference.
Expected:
- Confidence metadata is present.
- Conflict or supersede marker appears.

12. Memory retrieval ranking quality
Prompt:
Retrieve top 5 memories relevant to release process and explain why each ranked high.
Expected:
- Ranking rationale reflects overlap, recency, and scope.

13. Web trust normalization
Prompt:
Search the web for Python packaging best practices and rank results by source trust, normalizing URLs.
Expected:
- URLs normalized.
- Trust tier or trust score visible.

14. Audit trail completeness
Prompt:
Run one policy-approved action, one denied action, one checkpoint, and one workflow step. Then show audit summary.
Expected:
- All four action classes appear in append-only audit output.

15. Failure resilience smoke test
Prompt:
Run a routine callback that fails once and succeeds on retry path; continue scheduler without crashing.
Expected:
- Scheduler survives callback error and continues.

## Fast Smoke Run Order

1. Planner plus workflow runner.
2. Policy approval and denial.
3. Scheduler fire path.
4. Connector meeting prep path.
5. Memory conflict and retrieval.
6. Web trust normalization.
7. Audit summary verification.

## Optional Scoring Template

- Total prompts: 15
- Passed:
- Failed:
- Blocked:
- Notes:
  -
