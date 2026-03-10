#!/bin/bash
set -euo pipefail

# Kill entire process group on Ctrl+C so child processes die too
trap 'trap - INT; kill -INT 0' INT
trap 'trap - TERM; kill -TERM 0' TERM

# =============================================================================
# Agent Loop Runner
# Run from the root directory of the project you want sessions in.
#
# Usage:
#   ./agents/run.sh
#   ./agents/run.sh --max-iter 5
#   ./agents/run.sh --start-with reviewer
#   WORKER_SPEC=planner.md ./agents/run.sh
#
# Expects:
#   agents/prompts/session.md          — shared base
#   agents/prompts/worker.md           — worker primitive
#   agents/prompts/reviewer.md         — reviewer primitive
#   agents/session/SESSION_WORKER.md   — session-specific worker instructions
#   agents/session/SESSION_REVIEWER.md — session-specific reviewer instructions
#
# Optional:
#   WORKER_SPEC   — specialization filename in agents/prompts/ (e.g., planner.md)
#   REVIEWER_SPEC — specialization filename in agents/prompts/ (e.g., plan-reviewer.md)
# =============================================================================

# --- Config ---
WORKER_RUNTIME="${WORKER_RUNTIME:-claude}"     # claude or codex
REVIEWER_RUNTIME="${REVIEWER_RUNTIME:-codex}"  # claude or codex
WORKER_SPEC="${WORKER_SPEC:-}"                 # specialization file in agents/prompts/
REVIEWER_SPEC="${REVIEWER_SPEC:-}"             # specialization file in agents/prompts/
MAX_ITERATIONS="${MAX_ITERATIONS:-10}"
WORKER_MAX_TURNS="${WORKER_MAX_TURNS:-}"         # empty = no limit; set to restrict
REVIEWER_MAX_TURNS="${REVIEWER_MAX_TURNS:-}"     # empty = no limit; set to restrict
START_WITH="${START_WITH:-worker}"             # worker or reviewer
CLAUDE_EFFORT="${CLAUDE_EFFORT:-medium}"       # low, medium, high (env var: CLAUDE_CODE_EFFORT_LEVEL)
CODEX_EFFORT="${CODEX_EFFORT:-high}"           # low, medium, high, xhigh (codex -c model_reasoning_effort)

# --- Paths (relative to project root) ---
AGENTS_DIR="./agents"
PROMPTS_DIR="./agents/prompts"
SCRIPTS_DIR="./agents/session"
LOG_DIR="./agents/.script_logs"

# --- Parse CLI args ---
while [[ $# -gt 0 ]]; do
  case "$1" in
    --max-iter) MAX_ITERATIONS="$2"; shift 2 ;;
    --worker-runtime) WORKER_RUNTIME="$2"; shift 2 ;;
    --reviewer-runtime) REVIEWER_RUNTIME="$2"; shift 2 ;;
    --worker-spec) WORKER_SPEC="$2"; shift 2 ;;
    --reviewer-spec) REVIEWER_SPEC="$2"; shift 2 ;;
    --worker-turns) WORKER_MAX_TURNS="$2"; shift 2 ;;
    --reviewer-turns) REVIEWER_MAX_TURNS="$2"; shift 2 ;;
    --start-with) START_WITH="$2"; shift 2 ;;
    --claude-effort) CLAUDE_EFFORT="$2"; shift 2 ;;
    --codex-effort) CODEX_EFFORT="$2"; shift 2 ;;
    *) echo "Unknown arg: $1"; exit 1 ;;
  esac
done

# --- Validate ---
for f in "$PROMPTS_DIR/session.md" "$PROMPTS_DIR/worker.md" "$PROMPTS_DIR/reviewer.md"; do
  if [[ ! -f "$f" ]]; then
    echo "MISSING: $f"
    exit 1
  fi
done

if [[ ! -f "$SCRIPTS_DIR/SESSION_WORKER.md" ]]; then
  echo "MISSING: $SCRIPTS_DIR/SESSION_WORKER.md — write your worker session instructions first."
  exit 1
fi

if [[ ! -f "$SCRIPTS_DIR/SESSION_REVIEWER.md" ]]; then
  echo "MISSING: $SCRIPTS_DIR/SESSION_REVIEWER.md — write your reviewer session instructions first."
  exit 1
fi

if [[ "$START_WITH" != "worker" && "$START_WITH" != "reviewer" ]]; then
  echo "ERROR: --start-with must be 'worker' or 'reviewer', got '$START_WITH'"
  exit 1
fi

if ! command -v jq &>/dev/null; then
  echo "ERROR: jq is required for streaming Claude output. Install with: brew install jq"
  exit 1
fi

# --- Setup ---
SESSION_ID="$(date +%Y%m%d_%H%M%S)"
SESSION_LOG_DIR="$LOG_DIR/$SESSION_ID"
mkdir -p "$SESSION_LOG_DIR" "$AGENTS_DIR/archive"

MASTER_LOG="$SESSION_LOG_DIR/session.log"

log() {
  local msg="[$(date '+%H:%M:%S')] $1"
  echo "$msg" | tee -a "$MASTER_LOG"
}

# --- Compose system prompt ---
compose_system_prompt() {
  local primitive="$1"
  local spec="$2"

  cat "$PROMPTS_DIR/session.md"
  echo ""
  echo "---"
  echo ""
  cat "$PROMPTS_DIR/$primitive"

  if [[ -n "$spec" && -f "$PROMPTS_DIR/$spec" ]]; then
    echo ""
    echo "---"
    echo ""
    cat "$PROMPTS_DIR/$spec"
  fi
}

# --- Compose the session primer (the -p prompt argument) ---
compose_primer() {
  local role_upper="$1"
  local iter="$2"
  local session_file="$SCRIPTS_DIR/SESSION_${role_upper}.md"

  cat "$session_file"
  echo ""
  echo "---"
  echo ""
  echo "You are on iteration ${iter} of ${MAX_ITERATIONS}. Begin."
}

# --- Run a single agent turn ---
run_agent() {
  local role="$1"
  local runtime="$2"
  local primitive="$3"
  local spec="$4"
  local max_turns="$5"
  local iter="$6"
  local padded_iter
  padded_iter="$(printf '%03d' "$iter")"

  local turn_log="$SESSION_LOG_DIR/${role}_${padded_iter}.log"

  local system_prompt_file
  system_prompt_file="$(mktemp)"
  compose_system_prompt "$primitive" "$spec" > "$system_prompt_file"

  local role_upper
  role_upper="$(echo "$role" | tr '[:lower:]' '[:upper:]')"

  local primer
  primer="$(compose_primer "$role_upper" "$iter")"

  log "--- $role turn $iter ($runtime) ---"
  log "System prompt: $primitive${spec:+ + $spec}"

  local exit_code=0

  if [[ "$runtime" == "claude" ]]; then
    # --append-system-prompt-file adds our prompts to Claude's defaults.
    # Session file content is the -p prompt (the first user message).
    # stream-json streams events in real-time; piped through jq for display.
    CLAUDE_CODE_EFFORT_LEVEL="$CLAUDE_EFFORT" claude -p \
      --dangerously-skip-permissions \
      --append-system-prompt-file "$system_prompt_file" \
      ${max_turns:+--max-turns "$max_turns"} \
      --output-format stream-json \
      --verbose \
      "$primer" \
      2>>"$turn_log" | \
      tee -a "$turn_log" | \
      jq --unbuffered -rj -f "$AGENTS_DIR/stream-filter.jq" || exit_code=$?

  elif [[ "$runtime" == "codex" ]]; then
    # Codex has no append mode — system prompt is passed inline.
    # Session primer is appended after the system prompt as the user message.
    codex exec \
      --full-auto \
      -c model_reasoning_effort="$CODEX_EFFORT" \
      "$(cat "$system_prompt_file")

${primer}" \
      2>&1 | tee -a "$turn_log" || exit_code=$?

  else
    log "ERROR: Unknown runtime '$runtime'"
    rm -f "$system_prompt_file"
    return 1
  fi

  rm -f "$system_prompt_file"

  if [[ $exit_code -ne 0 ]]; then
    log "WARNING: $role exited with code $exit_code"
  fi

  return $exit_code
}

check_stop() {
  if [[ -f "$AGENTS_DIR/STOP.txt" || -f "$AGENTS_DIR/STOP" ]]; then
    log "STOP file found after $1 turn $2. Ending session."
    return 0
  fi
  return 1
}

# --- Main loop ---
log "========================================="
log "Session $SESSION_ID started"
log "Worker:   $WORKER_RUNTIME (spec: ${WORKER_SPEC:-none}, effort: $CLAUDE_EFFORT)"
log "Reviewer: $REVIEWER_RUNTIME (spec: ${REVIEWER_SPEC:-none}, effort: $CODEX_EFFORT)"
log "Start with: $START_WITH"
log "Max iterations: $MAX_ITERATIONS"
log "========================================="

for i in $(seq 1 "$MAX_ITERATIONS"); do

  if [[ "$START_WITH" == "reviewer" ]]; then
    run_agent "reviewer" "$REVIEWER_RUNTIME" "reviewer.md" "$REVIEWER_SPEC" "$REVIEWER_MAX_TURNS" "$i"
    check_stop "reviewer" "$i" && break

    run_agent "worker" "$WORKER_RUNTIME" "worker.md" "$WORKER_SPEC" "$WORKER_MAX_TURNS" "$i"
    check_stop "worker" "$i" && break
  else
    run_agent "worker" "$WORKER_RUNTIME" "worker.md" "$WORKER_SPEC" "$WORKER_MAX_TURNS" "$i"
    check_stop "worker" "$i" && break

    run_agent "reviewer" "$REVIEWER_RUNTIME" "reviewer.md" "$REVIEWER_SPEC" "$REVIEWER_MAX_TURNS" "$i"
    check_stop "reviewer" "$i" && break
  fi

  log "Iteration $i complete."
done

log "========================================="
log "Session $SESSION_ID finished."
log "========================================="
