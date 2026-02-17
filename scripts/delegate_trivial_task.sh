#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<USAGE
Usage:
  scripts/delegate_trivial_task.sh --task "<short task>" [--checks "<cmd>"] [--run-checks]

Purpose:
  Create a repeatable two-pass delegation bundle:
  1) Junior draft (local ollama-coder)
  2) Senior review (remote gpt-5.3-codex)

Outputs:
  .openclaw/delegation/<timestamp>/
    01_junior_prompt.md
    02_senior_review_prompt.md
    03_validation.sh
    RUN.md
USAGE
}

TASK=""
CHECKS=""
RUN_CHECKS=0

while [[ $# -gt 0 ]]; do
  case "$1" in
    --task)
      TASK="${2:-}"
      shift 2
      ;;
    --checks)
      CHECKS="${2:-}"
      shift 2
      ;;
    --run-checks)
      RUN_CHECKS=1
      shift
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "Unknown arg: $1" >&2
      usage
      exit 1
      ;;
  esac
done

if [[ -z "$TASK" ]]; then
  echo "Error: --task is required" >&2
  usage
  exit 1
fi

if ! git rev-parse --is-inside-work-tree >/dev/null 2>&1; then
  echo "Error: run inside a git repo" >&2
  exit 1
fi

ROOT="$(git rev-parse --show-toplevel)"
cd "$ROOT"

TS="$(date +%Y%m%d-%H%M%S)"
OUTDIR="$ROOT/.openclaw/delegation/$TS"
mkdir -p "$OUTDIR"

BRANCH="$(git branch --show-current || true)"
STATUS="$(git status --short || true)"

cat > "$OUTDIR/01_junior_prompt.md" <<PROMPT
# Junior Programmer Pass (Local Ollama)

Task:
$TASK

Constraints:
- Handle only trivial/low-risk coding work.
- Keep changes small and localized.
- No architecture/security boundary changes.

Expected output:
1) Implement code changes.
2) Provide concise handoff:
   - Files changed
   - Why changed
   - Risks/assumptions

Repo context:
- Branch: ${BRANCH}
- Current status:
\
${STATUS:-"(clean)"}
PROMPT

cat > "$OUTDIR/02_senior_review_prompt.md" <<PROMPT
# Senior Review Pass (Remote gpt-5.3-codex)

Review the junior draft and improve before commit.

Checklist:
- Correctness and edge cases
- Simplicity/readability
- Maintainability
- Project style consistency
- Remove risky assumptions

Required outcome:
- Final patch is senior-reviewed and improved (not raw junior output).
- Ready for validation and commit.
PROMPT

cat > "$OUTDIR/03_validation.sh" <<SH
#!/usr/bin/env bash
set -euo pipefail
cd "$ROOT"

# Optional project checks:
${CHECKS:-echo "No --checks command supplied. Run your project checks manually."}
SH
chmod +x "$OUTDIR/03_validation.sh"

cat > "$OUTDIR/RUN.md" <<RUN
# Delegation Runbook

1) Junior pass (local ollama-coder)
- Use prompt file: \
  \
  $OUTDIR/01_junior_prompt.md

2) Senior pass (remote gpt-5.3-codex)
- Use prompt file: \
  \
  $OUTDIR/02_senior_review_prompt.md

3) Validation
\
$OUTDIR/03_validation.sh

4) Commit
- Include note in commit body: "Reviewed and corrected by gpt-5.3-codex"
RUN

if [[ "$RUN_CHECKS" -eq 1 ]]; then
  "$OUTDIR/03_validation.sh"
fi

echo "Created delegation bundle: $OUTDIR"
echo "Next: follow $OUTDIR/RUN.md"
