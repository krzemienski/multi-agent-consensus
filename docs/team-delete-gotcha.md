# The TeamDelete Gotcha

## Problem

When implementing multi-agent orchestration with Claude Code's native Teams API, there is a critical timing issue: **teammates must call the `shutdown_response` tool explicitly to terminate.**

Plain text acknowledgment does not count.

## What Happens

If an agent responds "Understood, shutting down" in natural language, it does not actually terminate. The system waits. Your orchestration hangs.

This was discovered on the first multi-agent run — two of three agents shut down cleanly, the third had acknowledged the shutdown in prose and stayed alive indefinitely.

## The Wrong Way

```
Orchestrator: "Please shut down"
Agent: "Understood, shutting down now."  ← Still alive! Just said words.
Orchestrator: TeamDelete()  ← Fails: agent still running
```

## The Correct Pattern

```python
# 1. Orchestrator sends shutdown request
SendMessage(type="shutdown_request", recipient="alpha", content="Task complete")

# 2. Agent MUST call the tool — not just acknowledge in text
# In the agent's response:
SendMessage(type="shutdown_response", request_id="abc-123", approve=True)
# ↑ This is the actual shutdown. It's a tool call, not a text response.

# 3. Only after all agents have called shutdown_response:
TeamDelete()
```

## The Fix

Make the shutdown tool call a **mandatory part of each agent's task completion protocol**. Not a polite request — a required terminal action, enforced in the agent's system prompt.

Add to every agent's system prompt:
```
When you receive a shutdown_request, you MUST respond by calling the
shutdown_response tool with approve=True. Do NOT just acknowledge in text.
Text acknowledgment does not terminate your process.
```

## Why This Matters

- Orphaned agents consume compute resources
- TeamDelete fails if agents are still running
- The orchestrator hangs waiting for shutdown confirmation
- In a 3-agent consensus pipeline, one orphaned agent blocks the entire cleanup

## Detection

If your pipeline seems to hang after all work is complete, check for agents that acknowledged shutdown in text but never called the shutdown_response tool. The team config file at `~/.claude/teams/{team-name}/config.json` shows member status.
