#!/usr/bin/env bash
set -euo pipefail

# Assume this script lives directly inside vsbtools_reproducibility_env.
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ENV_FILE="$ROOT/reproducibility_env.sh"

if [[ ! -f "$ENV_FILE" ]]; then
    echo "Missing environment file: $ENV_FILE" >&2
    exit 1
fi

# Restore all paths and bridge variables created by the setup script:
#   VSBTOOLS_PYTHON
#   MATTERGEN_PYTHON_PATH
#   GRACE_PYTHON
#   JUPYTER_PATH
#   VSBTOOLS_EXTERNAL_PATHS_CONFIG
#   Jupyter/IPython/XDG state directories
#   etc.
source "$ENV_FILE"

TARGET="${1:-$PWD}"

if [[ -f "$TARGET" ]]; then
    NOTEBOOK="$(cd "$(dirname "$TARGET")" && pwd)/$(basename "$TARGET")"
    WORKDIR="$(dirname "$NOTEBOOK")"
elif [[ -d "$TARGET" ]]; then
    NOTEBOOK=""
    WORKDIR="$(cd "$TARGET" && pwd)"
else
    echo "No such notebook or directory: $TARGET" >&2
    exit 1
fi

cd "$WORKDIR"

echo "vsbtools environment: $VSBTOOLS_VENV"
echo "MatterGen environment: $SCOUT_MATTER_VENV"
echo "GRACE environment: $GRACE_VENV"
echo "Kernel: vsbtools-repro"
echo "Working directory: $WORKDIR"

if [[ -n "$NOTEBOOK" ]]; then
    exec "$VSBTOOLS_PYTHON" -m jupyter lab \
        --notebook-dir "$WORKDIR" \
        --MappingKernelManager.default_kernel_name=vsbtools-repro \
        "$NOTEBOOK"
else
    exec "$VSBTOOLS_PYTHON" -m jupyter lab \
        --notebook-dir "$WORKDIR" \
        --MappingKernelManager.default_kernel_name=vsbtools-repro
fi