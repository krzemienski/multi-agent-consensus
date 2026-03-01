# Streaming Audit Example

This example demonstrates how the consensus framework caught a P2 bug in ILS iOS's streaming chat implementation — a bug that a single-agent review explicitly approved.

## The Bug

In `ChatViewModel.swift`, two root causes produced visible text duplication:

1. **Append vs Assignment** (Line 926): `message.text += textBlock.text` appended content that was already accumulated. The assistant event is authoritative — it should be assignment (`=`), not append (`+=`).

2. **Index Reset** (Stream-end handler): `self.lastProcessedMessageIndex = 0` replayed the entire SSE message buffer on the next observation cycle.

Result: "Four" rendered as "Four.Four." during streaming.

## How Consensus Caught It

- **Alpha** (code specialist): Read the implementation line by line. Flagged Line 926: "appends the content delta AND sets the full accumulated text. The assistant event is authoritative; this should be assignment, not append."

- **Bravo** (functional specialist): Ran the app and verified responses rendered incorrectly during streaming. Confirmed the fix by verifying "Four." and "Six." rendered correctly.

- **Lead** (architecture specialist): Cross-checked that both SDK and CLI execution paths used the same corrected handler. Verified `lastProcessedMessageIndex` was correctly preserved.

## Running This Example

```bash
consensus run --target ./your-streaming-project --config examples/streaming-audit/config.yaml
```

## Key Lesson

The `+=` operator was right there on line 926. It looked correct because the pattern — accumulate text in a streaming handler — should use append. The bug was that this particular text was already accumulated. You need independent fresh perspectives to see what pattern matching misses.
