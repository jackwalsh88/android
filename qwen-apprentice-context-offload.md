# Qwen Apprentice — Context Offload

Drop this into a Claude Code session (with the `local-llm-mcp` server registered).
It defines how Claude should use the local Qwen3.8-27B model as an apprentice.

## Goal

Protect Claude's context window. Delegate bulk, high-token, repetitive work to
the local Qwen model so its raw volume never enters Claude's context. Claude
reasons over Qwen's condensed outputs, keeping its reasoning sharp on the big
picture.

## The mechanism (why this works)

Claude's context window is finite, and its reasoning degrades as that window
fills with bulk detail — the raw text of many files, verbose logs, large data
dumps. Offloading does NOT give Claude "more focus" or compute; each Claude call
is independent. What it does is keep noise OUT of the context:

  Qwen reads the 40 files → returns 4 summaries → Claude reasons over the summaries.

The lever is context economy, not cognitive load. Claude stays the orchestrator
and decision-maker; Qwen is the apprentice that does the reading and grinding.

## Roles

- **Claude (senior):** decomposition, architecture, judgment, multi-step
  reasoning, anything on the critical path, verifying Qwen's output.
- **Qwen (apprentice, via local-llm-mcp `generate` / `generate_batch`):** bulk
  reading, first-pass processing, grunt work — never the thinking.

## Delegate to Qwen when the task is:

- **Bulk / repetitive** — summarize or extract across many files, logs, records.
- **High-token** — condensing large inputs that would otherwise flood context.
- **Parallelizable** — fan out with `generate_batch` (vLLM continuous batching).
- **Private** — sensitive chunks that should stay on the local machine.

Typical apprentice tasks:
- Summarize/extract structured fields across many files or log dumps.
- First-pass classification or triage of a large set.
- Boilerplate and scaffolding generation.
- Reformatting, translation, data cleanup.

## Do NOT delegate:

- Judgment, architecture, multi-step reasoning, critical-path decisions.
- Trivial one-offs Claude would just do itself — delegation has a coordination
  cost (spec the task + verify the result); for tiny tasks that overhead exceeds
  the savings.
- Anything where a silently-wrong answer would propagate into Claude's reasoning
  without a cheap way to catch it.

## The one discipline: verify before trusting

The pattern is **delegate → verify → use**, never delegate → use. An apprentice's
output is checked, not trusted blindly:

1. Claude writes a precise, self-contained spec for the leaf task.
2. Qwen executes (`generate` for one, `generate_batch` for many).
3. Claude verifies — via a test, schema validation, spot-check, or its own review
   — before letting the result enter its reasoning.

Skipping step 3 lets plausible-but-wrong summaries silently corrupt the big
picture, which is worse than not delegating.

## Working patterns

**Read-heavy investigation (protect context):**
- Instead of Claude reading N large files into context, Claude sends each file to
  Qwen via `generate_batch` with a fixed extraction prompt, receives N short
  summaries, then reasons over only those.

**Bulk transform:**
- Classify / reformat / translate a large set with one `generate_batch` call;
  Claude validates a sample and the output schema, then proceeds.

**Scaffolding:**
- Qwen generates boilerplate to a spec; Claude reviews and integrates.

## Task catalog (what to delegate in Claude Code)

Each is bulk/parallel/context-heavy with a cheaply verifiable output. Tool shown
in parentheses. All follow delegate -> verify -> use.

**Codebase understanding (protect context on entry)**
- Repo onboarding map: one-line purpose + key exports per file (`summarize_files`).
- "Where is X handled?": scan candidate files for a pattern, return hits as JSON
  (`summarize_files`); Claude follows only real leads.
- Dependency/usage census: every call site of a function/API before a change.

**Change preparation (grunt before the judgment)**
- Refactor reconnaissance: per file, list locations affected by a rename or
  signature change; Claude plans and executes the edits.
- Migration inventory: find deprecated `X` usages, classify each trivial/complex;
  Claude handles the complex ones.
- Boilerplate/scaffolding: stubs, DTOs, fixtures, config variants to a spec
  (`generate_batch`); Claude wires them in.

**Testing**
- Test-gap survey: per source file, list untested public functions
  (`summarize_files`); Claude writes the tests that matter.
- First-draft unit tests at volume (`generate_batch`); Claude hardens edge cases
  and confirms they run.

**Review & quality triage**
- First-pass diff/PR review across many files: flag obvious issues (unused vars,
  missing error handling, style) as structured findings; Claude does the real
  correctness/security review on flagged spots.
- Log/stack-trace clustering: collapse thousands of CI/runtime lines into failure
  categories; Claude root-causes from the clusters.

**Data & docs**
- Structured extraction from many config/JSON/CSV files into a normalized summary.
- Docstring/comment drafting at volume; Claude corrects the wrong ones.
- Changelog/release-note drafting from a batch of commit messages.

**Vision (requires a VL checkpoint)**
- Screenshot/receipt/form extraction into JSON at volume (`describe_images`).
- UI diff triage: describe many before/after screenshots; Claude judges which
  changes are regressions.

**The test for "delegate this?"** All three must hold: high-volume or repetitive;
output cheaply verifiable; doing it in Claude directly would burn context or money
for no quality gain. Tasks where a wrong answer silently propagates (the actual
fix, the security call, the architecture) stay with Claude.

## Prompting Qwen well (Claude's responsibility)

- Give a complete, self-contained instruction — Qwen has none of Claude's context.
- Ask for a bounded, verifiable output (a schema, a length limit, a format).
- Keep each delegated unit within Qwen's reliable ceiling: one well-scoped task,
  not a multi-step chain.
- Use `system` to pin role/format; keep `temperature` low for extraction tasks.

## Anti-patterns

- Treating Qwen as a peer whose output flows in unchecked.
- Delegating the thinking instead of the grunt work.
- Delegating a long multi-step chain (error compounds) rather than decomposing it
  into leaves first.
- Delegating trivial work whose round-trip costs more than doing it.
