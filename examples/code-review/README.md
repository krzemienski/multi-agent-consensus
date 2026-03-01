# General Code Review Example

This example demonstrates using the consensus framework for general-purpose code review, where three agents independently review code changes before they can be merged.

## Use Case

Use this when reviewing pull requests, feature branches, or any significant code change where:
- Multiple system layers must agree on data contracts
- Complex state management is involved
- The change affects user-visible behavior

## Configuration

```bash
consensus run --target ./my-project --config examples/code-review/config.yaml
```

## What Each Agent Checks

- **Lead**: Cross-component consistency, API contracts, architectural coherence
- **Alpha**: Line-by-line correctness, logic errors, state management
- **Bravo**: Functional behavior, edge cases, runtime verification

## Expected Flow

1. **Explore**: Agents map the codebase and understand the change context
2. **Audit**: Deep review against correctness, contracts, and edge cases
3. **Verify**: Final check that everything works end-to-end

The `fix` phase is optional for pure reviews — remove it from the config if you only want validation without automated fixes.
