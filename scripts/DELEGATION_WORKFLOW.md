# Delegation Workflow (Trivial-first)

Use this for repeatable junior→senior execution.

## Command

```bash
scripts/delegate_trivial_task.sh --task "<task summary>" --checks "<project check command>"
```

Example:

```bash
scripts/delegate_trivial_task.sh \
  --task "Refactor settings form validation" \
  --checks "npm test && npm run build"
```

## Autocommit example

```bash
scripts/delegate_trivial_task.sh \
  --task "clean up navbar spacing" \
  --checks "npm run build" \
  --run-checks \
  --autocommit \
  --commit-type "refactor"
```

Autocommit message template:
- Subject: `<type>: <task>`
- Body includes:
  - `Reviewed and corrected by gpt-5.3-codex.`
  - `Co-authored-by: Junior Programmer (ollama-coder)`

## What it creates

`.openclaw/delegation/<timestamp>/`
- `01_junior_prompt.md`
- `02_senior_review_prompt.md`
- `03_validation.sh`
- `RUN.md`

## Policy
- Junior pass: local `ollama-coder`
- Senior review pass: remote `gpt-5.3-codex`
- Commit only after senior corrections and validation checks
