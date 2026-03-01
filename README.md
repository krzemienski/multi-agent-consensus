# Multi-Agent Consensus

**3-agent consensus validation with hard gates for Claude Code.**

A framework where three specialized agents (Lead, Alpha, Bravo) independently validate work at phase gates. All three must vote PASS unanimously for the gate to open — no exceptions.

Built from catching a P2 streaming bug that a single-agent review explicitly approved.

## The Pattern

```
┌─────────┐    ┌──────────────────────────────┐    ┌──────────┐
│  Phase   │───▶│       Gate Checkpoint         │───▶│  Phase   │
│    N     │    │                              │    │   N+1    │
│          │    │  ┌──────┐ ┌───────┐ ┌──────┐│    │          │
│  (work)  │    │  │ Lead │ │ Alpha │ │Bravo ││    │  (work)  │
│          │    │  │      │ │       │ │      ││    │          │
│          │    │  │ PASS │ │ PASS  │ │ PASS ││    │          │
│          │    │  └──────┘ └───────┘ └──────┘│    │          │
│          │    │                              │    │          │
│          │    │  ALL 3 PASS → Gate Opens     │    │          │
│          │    │  ANY FAIL  → Fix Cycle       │    │          │
└─────────┘    └──────────────────────────────┘    └──────────┘
```

**Key properties:**
- **Independent verification**: Each agent starts fresh — no shared findings until vote
- **Hard gates**: 2/3 does not pass. Unanimity or nothing.
- **Re-validation after fixes**: ALL agents re-validate, not just the failing one

## Install

```bash
pip install multi-agent-consensus
```

Requires [Claude Code CLI](https://docs.anthropic.com/en/docs/claude-code) installed and authenticated.

## Quick Start

```bash
# Run the full consensus pipeline
consensus run --target ./my-project --phases "explore,audit,fix,verify"

# Run a single gate check
consensus validate --target ./my-project --phase audit

# View results from the last run
consensus report --target ./my-project

# Display role definitions
consensus roles

# Show current configuration
consensus show-config
```

## The Three Roles

### Lead — Architecture & Consistency Specialist
Validates the whole. Cross-component consistency, pattern compliance, regression detection. Breaks ties when interpretation differs.

**Catches**: Contract mismatches between layers, pattern violations, fixes that break other components.

### Alpha — Code & Logic Specialist
Reads implementation line by line. Incorrect accumulation patterns, off-by-one errors, state machine bugs, API contract violations.

**Catches**: The `+=` vs `=` bug, state index resets, type mismatches at boundaries, missing error handlers.

### Bravo — Systems & Functional Specialist
Exercises the running system. UI behavior under real conditions, edge cases with actual data, regressions in previously working flows.

**Catches**: Runtime-only bugs, visual duplication, edge case failures, performance degradation.

## The Bug That Proved the Pattern

Line 926 of `ChatViewModel.swift`. A P2 streaming text duplication bug that lived in the codebase for three days.

**Root cause 1**: `message.text += textBlock.text` — appends content that's already accumulated. Should be `=` (assignment), not `+=` (append).

**Root cause 2**: `self.lastProcessedMessageIndex = 0` — resets on stream end, replaying the entire message buffer.

**Result**: "Four" rendered as "Four.Four." during streaming.

A single-agent review said it looked fine. Three agents running structured consensus caught both root causes in the first pass.

## Configuration

Create a YAML config file:

```yaml
agents:
  lead:
    model: opus
    timeout_seconds: 300
  alpha:
    model: sonnet
    timeout_seconds: 300
  bravo:
    model: sonnet
    timeout_seconds: 300

pipeline:
  phases:
    - explore
    - audit
    - fix
    - verify
  max_fix_cycles: 3
  parallel_agents: true

gate:
  require_unanimous: true
  require_evidence: true
```

```bash
consensus run --target ./my-project --config my-config.yaml
```

## When to Use This Pattern

**Use consensus when:**
- Complex state management where multiple update mechanisms interact
- Multiple system layers must agree on data contracts
- A bug would be immediately visible to users
- Comprehensive audits across a large surface area
- Sequential pipelines where bugs compound across stages

**Stick with single-agent review when:**
- Change is isolated to one file with simple logic
- Risk of a missed bug is low
- Speed matters more than thoroughness

## How Gates Work

1. **Phase N tasks complete** — all implementation work is done
2. **Lead signals gate check** — identical prompts sent to all three agents
3. **Agents run independently** — no shared state, no visibility into each other's work
4. **Each produces evidence** — build logs, screenshots, code analysis
5. **System checks unanimity** — all three must contain explicit "PASS"
6. **Gate opens or stays closed** — unanimous PASS advances; any FAIL triggers fix cycle

The fix cycle is critical:
1. Failing agent's evidence identifies the issue
2. Fix is implemented
3. **ALL THREE agents re-validate** — not just the one that failed

Re-validating all three catches the failure mode where a fix resolves one issue but introduces a regression.

## Examples

- [`examples/streaming-audit/`](examples/streaming-audit/) — Auditing SSE streaming for the P2 duplication bug
- [`examples/code-review/`](examples/code-review/) — General-purpose code review with consensus gates

## The TeamDelete Gotcha

When using Claude Code's Teams API: teammates must call `shutdown_response` explicitly. Plain text acknowledgment ("Understood, shutting down") does NOT terminate the agent. See [`docs/team-delete-gotcha.md`](docs/team-delete-gotcha.md) for the full writeup.

## Part of the Agentic Development Series

This tool is part of a blog series on building software with AI agents at scale:

1. [Claude iOS Streaming Bridge](https://github.com/krzemienski/claude-ios-streaming-bridge)
2. [Claude SDK Bridge](https://github.com/krzemienski/claude-sdk-bridge)
3. [Auto-Claude Worktrees](https://github.com/krzemienski/auto-claude-worktrees)
4. **Multi-Agent Consensus** (this repo)

## License

MIT
