#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SOURCE_NOTEBOOK="$SCRIPT_DIR/mattergen_analysis.ipynb"

usage() {
    cat <<'EOF'
Usage:
  launch_mattergen_analysis.sh SYSTEM_ROOT [OPTIONS] [-- JUPYTER_ARGS...]

Create or open SYSTEM_ROOT/analysis-run/mattergen_analysis.ipynb using the
managed VSBTools kernel with MatterGen and GRACE paths configured.

Options:
  --env-root PATH   Managed environment root containing workflow_env.sh
  --refresh         Replace the system notebook with the repository template
  --no-launch       Prepare and validate the notebook without starting Jupyter
  -h, --help        Show this help

The launcher remembers the resolved environment root in
SYSTEM_ROOT/.vsbtools-env-root. Notebook edits under analysis-run are preserved
until --refresh is requested.
EOF
}

fail() {
    printf 'Error: %s\n' "$*" >&2
    exit 2
}

[[ $# -gt 0 ]] || { usage >&2; exit 2; }
case "$1" in
    -h|--help)
        usage
        exit 0
        ;;
esac

SYSTEM_ROOT="$1"
shift
ENV_ROOT=""
REFRESH=0
LAUNCH=1
JUPYTER_ARGS=()

while [[ $# -gt 0 ]]; do
    case "$1" in
        --env-root)
            [[ $# -ge 2 ]] || fail "$1 requires a value"
            ENV_ROOT="$2"
            shift 2
            ;;
        --refresh)
            REFRESH=1
            shift
            ;;
        --no-launch)
            LAUNCH=0
            shift
            ;;
        -h|--help)
            usage
            exit 0
            ;;
        --)
            shift
            JUPYTER_ARGS=("$@")
            break
            ;;
        *)
            fail "unknown option '$1'; use -- before Jupyter arguments"
            ;;
    esac
done

[[ -f "$SOURCE_NOTEBOOK" ]] || fail "notebook template is missing: $SOURCE_NOTEBOOK"
mkdir -p "$SYSTEM_ROOT"
SYSTEM_ROOT="$(cd "$SYSTEM_ROOT" && pwd)"

resolve_env_file() {
    local marker="$SYSTEM_ROOT/.vsbtools-env-root"
    local candidate
    local candidates=()

    if [[ -n "$ENV_ROOT" ]]; then
        candidates+=("$ENV_ROOT/workflow_env.sh")
    fi
    if [[ -n "${VSBTOOLS_WORKFLOW_ENV:-}" ]]; then
        candidates+=("$VSBTOOLS_WORKFLOW_ENV/workflow_env.sh")
    fi
    if [[ -f "$marker" ]]; then
        candidate="$(<"$marker")"
        candidates+=("$candidate/workflow_env.sh")
    fi
    candidates+=(
        "$SCRIPT_DIR/workflow-env/workflow_env.sh"
        "$(dirname "$SCRIPT_DIR")/workflow-env/workflow_env.sh"
    )

    for candidate in "${candidates[@]}"; do
        if [[ -f "$candidate" ]]; then
            printf '%s\n' "$candidate"
            return 0
        fi
    done
    return 1
}

ENV_FILE="$(resolve_env_file)" || fail \
    "workflow_env.sh was not found; pass --env-root once for this system"
ENV_ROOT="$(cd "$(dirname "$ENV_FILE")" && pwd)"
source "$ENV_FILE"

[[ -x "${VSBTOOLS_PYTHON:-}" ]] || fail "VSBTOOLS_PYTHON is unavailable"
[[ -x "${MATTERGEN_PYTHON:-}" ]] || fail "MATTERGEN_PYTHON is unavailable"
if [[ -n "${GRACE_PYTHON:-}" ]]; then
    [[ -x "$GRACE_PYTHON" ]] || fail "GRACE_PYTHON is unavailable: $GRACE_PYTHON"
fi

ANALYSIS_ROOT="$SYSTEM_ROOT/analysis-run"
TARGET_NOTEBOOK="$ANALYSIS_ROOT/mattergen_analysis.ipynb"
mkdir -p "$ANALYSIS_ROOT"

if [[ ! -f "$TARGET_NOTEBOOK" || "$REFRESH" -eq 1 ]]; then
    cp "$SOURCE_NOTEBOOK" "$TARGET_NOTEBOOK"
    printf 'Prepared notebook: %s\n' "$TARGET_NOTEBOOK"
else
    printf 'Using existing notebook: %s\n' "$TARGET_NOTEBOOK"
fi
printf '%s\n' "$ENV_ROOT" > "$SYSTEM_ROOT/.vsbtools-env-root"

export SYSTEM_ROOT
export VSBTOOLS_WORKFLOW_ENV="$ENV_ROOT"
cd "$ANALYSIS_ROOT"

printf 'VSBTools Python: %s\n' "$VSBTOOLS_PYTHON"
printf 'MatterGen Python: %s\n' "$MATTERGEN_PYTHON"
printf 'GRACE Python: %s\n' "${GRACE_PYTHON:-disabled}"
printf 'System root: %s\n' "$SYSTEM_ROOT"

if [[ "$LAUNCH" -eq 0 ]]; then
    exit 0
fi

exec "$VSBTOOLS_PYTHON" -m jupyter lab \
    --notebook-dir "$ANALYSIS_ROOT" \
    "$TARGET_NOTEBOOK" \
    "${JUPYTER_ARGS[@]}"
