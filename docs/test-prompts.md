# tau-assistant Test Prompts

Use these prompts to validate current tau-assistant capabilities (workflow execution, recovery, skills, routines, web ranking, session recall, subagents, and dialectic profile).

## How To Use

- Run prompts in order for a full acceptance pass.
- For each prompt, record pass/fail and 1-2 notes.
- Prefer a clean test workspace (`.tau` folder) for deterministic checks.

## Core Prompt Checklist

1. Profile roundtrip
Prompt:
Set profile name/goals/preferences/boundaries, then read the profile back.
Expected:
- Saved values are returned exactly.

2. Dialectic profile default
Prompt:
Read the dialectic profile and list all dimension keys.
Expected:
- Includes speed_vs_quality, autonomy_vs_control, brevity_vs_depth, innovation_vs_stability, risk_acceptance_vs_safety.

3. Dialectic manual update
Prompt:
Update `speed_vs_quality` to quality-leaning with high confidence and provide evidence lines.
Expected:
- Score/confidence are updated.
- Evidence is persisted.

4. Dialectic inference
Prompt:
Infer dialectic profile from evidence text emphasizing concise and safe execution.
Expected:
- Profile updates successfully.
- Brevity and safety dimensions move in expected direction.

5. Planner and dependency ordering
Prompt:
Validate a 6-step plan with dependencies across design, implement, test, and release.
Expected:
- Topological order is valid.
- No cycle/dependency errors.

6. Workflow run in dry mode
Prompt:
Run a workflow in `dry_run` mode with two dependent steps.
Expected:
- Steps complete with checkpoints/outcomes.
- Handoff summary is generated.

7. Workflow run in execute mode
Prompt:
Run a workflow in `execute` mode with `connector_action` posting to chat.
Expected:
- Run status is `completed`.
- Connector action succeeds.

8. Policy approval block
Prompt:
Run execute mode under `balanced` policy with a medium-risk action and no risky approval.
Expected:
- Run stops on failure.
- Error indicates approval required.

9. Recovery and resume
Prompt:
Run a workflow where step 2 fails, then rerun with `resume=true` and corrected step 2.
Expected:
- First run stops on failure.
- Resumed run completes without duplicating step 1 completion.

10. Workflow state inspection
Prompt:
Get status for a completed workflow and list workflow states.
Expected:
- Status reports completion and latest step outcomes.
- Workflow appears in state listing.

11. Session search
Prompt:
Search sessions for “python packaging release” and return top matches.
Expected:
- Relevant session ranks first or near top.
- Snippets and scores are present.

12. Session recall summary
Prompt:
Recall a session by id prefix with focus query “packaging”.
Expected:
- Summary contains focus line and key points.

13. Memory add/search
Prompt:
Add a memory with confidence and tags; search with related query.
Expected:
- Added entry returns metadata.
- Search returns the new entry.

14. Workflow handoff memory integration
Prompt:
Run a workflow and verify handoff is also written to memory.
Expected:
- `handoff_memory_write` exists with source `assistant_workflow_handoff`.

15. Skill management CRUD
Prompt:
Create, read, list, and delete a skill.
Expected:
- All actions succeed and path/content are correct.

16. Manual workflow-to-skill promotion
Prompt:
Run workflow with `promote_to_skill=true`.
Expected:
- Skill promotion object is returned.
- Skill file exists.

17. Auto skill learning create
Prompt:
Run workflow with `auto_learn_skill=true` and enough completed steps where target skill does not exist.
Expected:
- Auto-learning triggers in `created` mode.

18. Auto skill learning improve
Prompt:
Run a second similar workflow with same skill name and auto-learn enabled.
Expected:
- Auto-learning triggers in `improved` mode.
- Skill contains `## Continuous Improvements`.

19. Auto skill learning skip guard
Prompt:
Run auto-learn with only one completed step and min threshold 2.
Expected:
- Auto-learning is skipped with `not_enough_completed_steps`.

20. Web trust normalization and ranking
Prompt:
Rank supplied web results for “python packaging best practices”.
Expected:
- URLs are normalized (tracking params removed).
- Trust fields and ranking reasons are present.

21. Meeting prep cross-connector routine
Prompt:
Run meeting prep with one event, chat channel, and email digest recipient.
Expected:
- Prep note created.
- Chat message sent.
- Email digest sent.

22. Routine manage and due delivery
Prompt:
Create chat-delivery routine, run due routines, then list routines.
Expected:
- Delivery succeeds.
- `last_run` is updated.

23. Routine delivery failure handling
Prompt:
Create email-delivery routine without recipient and run due routines.
Expected:
- Failure recorded.
- Routine `last_run` remains unset.

24. Subagent single delegation
Prompt:
Run one delegated subagent task (e.g., persona `explore`) and return result.
Expected:
- Subagent returns text output successfully.

25. Subagent parallel workstreams
Prompt:
Run two delegated tasks in parallel and aggregate results.
Expected:
- Both tasks complete.
- Completed/failed counters are accurate.

26. Checkpoint + insights report
Prompt:
Create named checkpoint, then generate insights.
Expected:
- Checkpoint file exists.
- Insights summary counts are non-zero where expected.

## Fast Smoke Run Order

1. Planner + execute workflow + resume recovery.
2. Memory + handoff + skill promotion.
3. Auto-skill learning (create then improve).
4. Web ranking + session search/recall.
5. Routine manage + due delivery + failure guard.
6. Subagent single + parallel.
7. Checkpoint + insights.

## Optional Scoring Template

- Total prompts: 26
- Passed:
- Failed:
- Blocked:
- Notes:
  -
