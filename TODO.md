# vibe-relay TODO

Items to tackle in future iterations.

## Pipeline Improvements

- **Plan review step**: Add a validation step that checks the planner's output against the original project prompt. Catch spec deviations (like wrong tech stack) before research/implementation begins.

- **Planner should fan out independent workstreams**: Currently the planner chains all workstreams linearly (A → B → C → D → E → F). Many workstreams could run in parallel (e.g., Campaign Builder and Analytics both depend on Audience Management but not on each other). The planner prompt should encourage a DAG shape, not just a chain — fan out where possible, only serialize where there's a real dependency. This reduces wall-clock time significantly on large projects.

- **Bootstrapping should harness the repo first**: The planner's first workstream should always create foundational docs and tooling before any feature work begins:
  - `DESIGN.md` / `ARCHITECTURE.md` — so every downstream agent understands the system design and conventions
  - `CLAUDE.md` — repo-level instructions that all agents inherit automatically
  - Claude Code skills (slash commands) for standardized workflows: running tests, committing/pushing, merging, writing frontend tests, writing backend tests, etc.
  - This eliminates agents reinventing these workflows every run, reduces merge conflicts from inconsistent git usage, and dramatically improves first-pass success rates since every agent follows the same playbook.

- **Agent prompt management in UI**: Ability to view and edit the system prompt for each agent role (planner, researcher, synthesizer, coder, tester, reviewer) directly from the UI. Currently requires editing markdown files on disk.

- **Parent tasks block on children**: A task should not be movable to Done until all its children are Done. This simplifies dependency orchestration — instead of needing `cascade_deps_from` or manually wiring edges to every impl task, you just make downstream workstreams depend on the parent milestone. The parent won't complete until its children do, so the dependency naturally holds. Eliminates the need for complex fan-out dependency mapping.

- **Rename pipeline steps**: Current: Plan → Research → Synthesize → Implement → Test → Review → Done. Proposed: **Scope → Plan → Research → Spec → Implement → Test → Review → Done**. Each name maps to what the step actually does:
  - **Scope**: Takes a user request, defines the boundaries, breaks into workstreams (current planner)
  - **Plan**: Takes a workstream, figures out what needs to be learned, creates research tasks (new — currently part of planner)
  - **Research**: Investigates a specific question (unchanged)
  - **Spec**: Reads research findings, writes impl tasks with acceptance criteria (current synthesizer)
  - **Implement → Test → Review → Done**: unchanged
  - Rename agents/prompts accordingly (planner.md → scoper.md, synthesizer.md → spec.md, add planner.md for the new Plan step)

## Reliability

- **Detect stuck agents**: Agents that exit 0 but never call `complete_task` or `move_task` get re-dispatched endlessly (saw "Implement token refresh" run 11 times). Need a max-retry limit and/or detection that an agent completed without advancing the task, then surface it in the UI as needing human intervention.

- **Manual takeover mode**: Let users pause a running agent and take manual control of the task. Provide a Claude Code input and a terminal embedded in the UI, both connected to the task's worktree. User can fix issues, run commands, then hand control back to the agent (resume) or complete the task themselves.

- **Merge conflict handling**: Agents that can't push due to merge conflicts silently fail and get re-dispatched forever (saw 11 retries on "token refresh" task). Agents should rebase from the base branch before starting work, and if conflicts arise during push, attempt to resolve them or fail the task with a clear error instead of exiting 0.

## Observability

- **Agent effectiveness metrics**: Emit OTEL metrics (or equivalent) to measure agent/job performance. Examples: time-per-step, pass/fail rates by agent role, retry counts, tokens consumed per task, how often test/review sends work back to implement, test pass rate on first attempt, avg tasks created per spec agent. Need a way to answer "which step is the bottleneck?" and "are agents getting better or worse over time?"

- **Track task rejections/bouncebacks**: When a task gets sent back from Test → Implement or Review → Implement, record it as a distinct event (which step rejected it, why, how many times). Currently a bounce-back looks identical to a fresh run. This feeds into the effectiveness metrics (first-pass success rate) and helps identify whether the problem is weak specs, weak coders, or overly strict reviewers.

## UI Features

- **In-app AI assistant**: Embed a conversational agent in the UI so you can ask "what's the current status?" or tell it to make changes mid-flight (cancel tasks, reprioritize, adjust scope) without touching the CLI.

- **Live agent log streaming**: Click on a running task and see the agent's output in real-time. Stream Claude CLI stdout/stderr to the UI via WebSocket so you can watch what agents are doing as they work.

- **Fix board flickering**: The kanban board flickers during re-renders. Likely caused by react-query refetches on every WebSocket event bumping `eventVersion`. Investigate debouncing or optimistic UI updates.
