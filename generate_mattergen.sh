#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

usage() {
    cat <<'EOF'
Usage:
  generate_mattergen.sh SYSTEM_ROOT [OPTIONS] [-- EXTRA_MATTERGEN_ARGS...]

Generate one homogeneous MatterGen setting below SYSTEM_ROOT. The chemical
system defaults to the SYSTEM_ROOT directory name. Guidance selects the guided
layout automatically; an invocation without guidance uses the unguided layout.

Examples:
  ./generate_mattergen.sh /data/work/Ni-Pd-H

  ./generate_mattergen.sh /data/work/Ni-Pd-H --runs 10 \
    --guidance "{'ranked_coordination': {'margin':0.05, '[Pd,Ni]-H':6}}"

Options:
  --env-root PATH             Managed environment root containing workflow_env.sh
  --chemical-system SYSTEM   MatterGen chemical system (default: SYSTEM_ROOT name)
  --generation N|gen_N       Generation group (default: next gen_N for this mode)
  --runs N                   Independent invocations in run_N directories (default: 1; creates run_1)
  --guidance MAPPING         MatterGen guidance mapping; enables guided mode
  --guidance-file PATH       Read the guidance mapping from a text file
  --batch-size N             Structures per batch (default: 20)
  --num-batches N            Batches per invocation (default: 1)
  --gpu N                    GPU index passed to MatterGen (default: 0)
  --diffusion-guidance-factor X  Sampling guidance factor (default: 2.0)
  --diffusion-loss-weight VALUE  Guided loss weight (default: [0.01,0.01,True])
  --self-rec-steps N         Self-reconstruction steps (default: 1)
  --back-step N              Back steps (default: 0)
  --algo N                   Sampling algorithm (default: 3)
  --pretrained-name NAME     MatterGen checkpoint name (default: chemical_system)
  --record-trajectories      Save trajectories
  --print-loss               Print MatterGen loss values
  --dry-run                  Print resolved commands and create no generation output
  -h, --help                 Show this help

The script remembers the resolved environment root in SYSTEM_ROOT/.vsbtools-env-root.
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
CHEMICAL_SYSTEM=""
GENERATION=""
RUNS=1
GUIDANCE=""
BATCH_SIZE=20
NUM_BATCHES=1
GPU=0
DIFFUSION_GUIDANCE_FACTOR=2.0
DIFFUSION_LOSS_WEIGHT="[0.01,0.01,True]"
SELF_REC_STEPS=1
BACK_STEP=0
ALGO=3
PRETRAINED_NAME="chemical_system"
RECORD_TRAJECTORIES="False"
PRINT_LOSS="False"
DRY_RUN=0
EXTRA_ARGS=()

while [[ $# -gt 0 ]]; do
    case "$1" in
        --env-root)
            [[ $# -ge 2 ]] || fail "$1 requires a value"
            ENV_ROOT="$2"
            shift 2
            ;;
        --chemical-system)
            [[ $# -ge 2 ]] || fail "$1 requires a value"
            CHEMICAL_SYSTEM="$2"
            shift 2
            ;;
        --generation)
            [[ $# -ge 2 ]] || fail "$1 requires a value"
            GENERATION="$2"
            shift 2
            ;;
        --runs)
            [[ $# -ge 2 ]] || fail "$1 requires a value"
            RUNS="$2"
            shift 2
            ;;
        --guidance)
            [[ $# -ge 2 ]] || fail "$1 requires a value"
            GUIDANCE="$2"
            shift 2
            ;;
        --guidance-file)
            [[ $# -ge 2 ]] || fail "$1 requires a value"
            [[ -f "$2" ]] || fail "guidance file does not exist: $2"
            GUIDANCE="$(<"$2")"
            shift 2
            ;;
        --batch-size)
            [[ $# -ge 2 ]] || fail "$1 requires a value"
            BATCH_SIZE="$2"
            shift 2
            ;;
        --num-batches)
            [[ $# -ge 2 ]] || fail "$1 requires a value"
            NUM_BATCHES="$2"
            shift 2
            ;;
        --gpu)
            [[ $# -ge 2 ]] || fail "$1 requires a value"
            GPU="$2"
            shift 2
            ;;
        --diffusion-guidance-factor)
            [[ $# -ge 2 ]] || fail "$1 requires a value"
            DIFFUSION_GUIDANCE_FACTOR="$2"
            shift 2
            ;;
        --diffusion-loss-weight)
            [[ $# -ge 2 ]] || fail "$1 requires a value"
            DIFFUSION_LOSS_WEIGHT="$2"
            shift 2
            ;;
        --self-rec-steps)
            [[ $# -ge 2 ]] || fail "$1 requires a value"
            SELF_REC_STEPS="$2"
            shift 2
            ;;
        --back-step)
            [[ $# -ge 2 ]] || fail "$1 requires a value"
            BACK_STEP="$2"
            shift 2
            ;;
        --algo)
            [[ $# -ge 2 ]] || fail "$1 requires a value"
            ALGO="$2"
            shift 2
            ;;
        --pretrained-name)
            [[ $# -ge 2 ]] || fail "$1 requires a value"
            PRETRAINED_NAME="$2"
            shift 2
            ;;
        --record-trajectories)
            RECORD_TRAJECTORIES="True"
            shift
            ;;
        --print-loss)
            PRINT_LOSS="True"
            shift
            ;;
        --dry-run)
            DRY_RUN=1
            shift
            ;;
        -h|--help)
            usage
            exit 0
            ;;
        --)
            shift
            EXTRA_ARGS=("$@")
            break
            ;;
        *)
            fail "unknown option '$1'; use -- before raw MatterGen arguments"
            ;;
    esac
done

[[ "$RUNS" =~ ^[1-9][0-9]*$ ]] || fail "--runs must be a positive integer"
[[ "$BATCH_SIZE" =~ ^[1-9][0-9]*$ ]] || fail "--batch-size must be a positive integer"
[[ "$NUM_BATCHES" =~ ^[1-9][0-9]*$ ]] || fail "--num-batches must be a positive integer"

mkdir -p "$SYSTEM_ROOT"
SYSTEM_ROOT="$(cd "$SYSTEM_ROOT" && pwd)"
CHEMICAL_SYSTEM="${CHEMICAL_SYSTEM:-$(basename "$SYSTEM_ROOT")}"

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

MATTERGEN_EXECUTABLE="${MATTERGEN_VENV:-}/bin/mattergen-generate"
if [[ ! -x "$MATTERGEN_EXECUTABLE" && -n "${MATTERGEN_PYTHON:-}" ]]; then
    candidate="$(dirname "$MATTERGEN_PYTHON")/mattergen-generate"
    [[ -x "$candidate" ]] && MATTERGEN_EXECUTABLE="$candidate"
fi
[[ -x "$MATTERGEN_EXECUTABLE" ]] || fail \
    "mattergen-generate is missing from the managed MatterGen environment"

if [[ -n "$GUIDANCE" ]]; then
    MODE_DIR="repeated-guided"
else
    MODE_DIR="non_guided"
fi
MODE_ROOT="$SYSTEM_ROOT/raw-generations/$MODE_DIR"

next_generation() {
    local max=0
    local path name number
    if [[ -d "$MODE_ROOT" ]]; then
        for path in "$MODE_ROOT"/gen_*; do
            [[ -d "$path" ]] || continue
            name="$(basename "$path")"
            number="${name#gen_}"
            if [[ "$number" =~ ^[0-9]+$ ]] && (( number > max )); then
                max="$number"
            fi
        done
    fi
    printf 'gen_%d\n' "$((max + 1))"
}

if [[ -z "$GENERATION" ]]; then
    GENERATION="$(next_generation)"
elif [[ "$GENERATION" =~ ^[0-9]+$ ]]; then
    GENERATION="gen_$GENERATION"
elif [[ ! "$GENERATION" =~ ^gen_[0-9]+$ ]]; then
    fail "--generation must be an integer or gen_N"
fi

GENERATION_ROOT="$MODE_ROOT/$GENERATION"

next_run_number() {
    local max=0
    local path name number
    if [[ -d "$GENERATION_ROOT" ]]; then
        for path in "$GENERATION_ROOT"/run_*; do
            [[ -d "$path" ]] || continue
            name="$(basename "$path")"
            number="${name#run_}"
            if [[ "$number" =~ ^[0-9]+$ ]] && (( number > max )); then
                max="$number"
            fi
        done
    fi
    printf '%d\n' "$((max + 1))"
}

if [[ -d "$GENERATION_ROOT" && ( -f "$GENERATION_ROOT/generated_crystals.extxyz" \
    || -f "$GENERATION_ROOT/input_parameters.txt" ) ]]; then
    fail "$GENERATION_ROOT contains a direct generation; move it under run_N or select another --generation"
fi

if [[ "$DRY_RUN" -eq 0 ]]; then
    mkdir -p "$GENERATION_ROOT"
    printf '%s\n' "$ENV_ROOT" > "$SYSTEM_ROOT/.vsbtools-env-root"
fi

START_RUN="$(next_run_number)"

printf 'System root: %s\n' "$SYSTEM_ROOT"
printf 'Chemical system: %s\n' "$CHEMICAL_SYSTEM"
printf 'Generation: %s (%s)\n' "$GENERATION" "$MODE_DIR"
printf 'Environment root: %s\n' "$ENV_ROOT"

for ((offset = 0; offset < RUNS; offset++)); do
    OUTPUT_PATH="$GENERATION_ROOT/run_$((START_RUN + offset))"

    command=(
        "$MATTERGEN_EXECUTABLE"
        "$OUTPUT_PATH"
        "--pretrained-name=$PRETRAINED_NAME"
        "--batch_size=$BATCH_SIZE"
        "--num_batches=$NUM_BATCHES"
        "--properties_to_condition_on={'chemical_system':'$CHEMICAL_SYSTEM'}"
        "--diffusion_guidance_factor=$DIFFUSION_GUIDANCE_FACTOR"
        "--record_trajectories=$RECORD_TRAJECTORIES"
        "--print_loss=$PRINT_LOSS"
        "--force_gpu=$GPU"
    )
    if [[ -n "$GUIDANCE" ]]; then
        command+=(
            "--guidance=$GUIDANCE"
            "--diffusion_loss_weight=$DIFFUSION_LOSS_WEIGHT"
            "--self_rec_steps=$SELF_REC_STEPS"
            "--back_step=$BACK_STEP"
            "--algo=$ALGO"
        )
    fi
    command+=("${EXTRA_ARGS[@]}")

    printf 'Output: %s\n' "$OUTPUT_PATH"
    printf 'Command:'
    printf ' %q' "${command[@]}"
    printf '\n'
    if [[ "$DRY_RUN" -eq 0 ]]; then
        "${command[@]}"
    fi
done

if [[ "$DRY_RUN" -eq 0 ]]; then
    printf '\nGeneration complete. Analyze with:\n  %q %q\n' \
        "$SCRIPT_DIR/launch_mattergen_analysis.sh" "$SYSTEM_ROOT"
fi
