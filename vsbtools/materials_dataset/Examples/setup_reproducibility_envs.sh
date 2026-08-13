#!/usr/bin/env bash
set -euo pipefail

SCOUT_MATTER_REPO_URL="${SCOUT_MATTER_REPO_URL:-https://github.com/link-lab3629/scout-matter.git}"
VSBTOOLS_REF="${VSBTOOLS_REF:-}"
SCOUT_MATTER_REF="${SCOUT_MATTER_REF:-}"
PYTHON_BIN="${PYTHON_BIN:-}"
MANAGED_PYTHON_VERSION="${MANAGED_PYTHON_VERSION:-3.11}"
PYTORCH_VERSION="${PYTORCH_VERSION:-}"
TORCHVISION_VERSION="${TORCHVISION_VERSION:-}"
TORCHAUDIO_VERSION="${TORCHAUDIO_VERSION:-}"
PYTORCH_CUDA_INDEX_URL="${PYTORCH_CUDA_INDEX_URL:-}"
PYG_WHEEL_URL="${PYG_WHEEL_URL:-}"
HOST_OS="$(uname -s)"
case "$HOST_OS" in
    Darwin*)
        PYTORCH_VERSION="${PYTORCH_VERSION:-2.4.1}"
        TORCHVISION_VERSION="${TORCHVISION_VERSION:-0.19.1}"
        TORCHAUDIO_VERSION="${TORCHAUDIO_VERSION:-2.4.1}"
        PYG_WHEEL_URL="${PYG_WHEEL_URL:-https://data.pyg.org/whl/torch-2.4.0+cpu.html}"
        ;;
    Linux*|MINGW*|MSYS*|CYGWIN*)
        PYTORCH_VERSION="${PYTORCH_VERSION:-2.2.1+cu118}"
        TORCHVISION_VERSION="${TORCHVISION_VERSION:-0.17.1+cu118}"
        TORCHAUDIO_VERSION="${TORCHAUDIO_VERSION:-2.2.1+cu118}"
        PYTORCH_CUDA_INDEX_URL="${PYTORCH_CUDA_INDEX_URL:-https://download.pytorch.org/whl/cu118}"
        PYG_WHEEL_URL="${PYG_WHEEL_URL:-https://data.pyg.org/whl/torch-2.2.1+cu118.html}"
        ;;
    *)
        echo "Unsupported operating system for reproducibility setup: $HOST_OS" >&2
        exit 1
        ;;
esac
ROOT="${VSBTOOLS_REPRO_ROOT:-$PWD/vsbtools_reproducibility_env}"
RUN_ROOT="${VSBTOOLS_REPRO_RUN_ROOT:-$PWD/vsbtools_reproducibility_run}"
EXISTING_VSBTOOLS_VENV=""
EXISTING_SCOUT_VENV=""
EXISTING_GRACE_VENV=""
LAUNCH=1
FORCE=0
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LOCAL_VSBTOOLS_REPO="$(git -C "$SCRIPT_DIR" rev-parse --show-toplevel 2>/dev/null || true)"
if [[ -n "${VSBTOOLS_REPO_URL:-}" ]]; then
    VSBTOOLS_REPO_URL="$VSBTOOLS_REPO_URL"
elif [[ -n "$LOCAL_VSBTOOLS_REPO" && -f "$LOCAL_VSBTOOLS_REPO/pyproject.toml" ]]; then
    VSBTOOLS_REPO_URL="$LOCAL_VSBTOOLS_REPO"
else
    VSBTOOLS_REPO_URL="https://github.com/link-lab3629/vsbtools.git"
fi

usage() {
    cat <<'USAGE'
Usage: setup_reproducibility_envs.sh [options]

Creates a contained reproducibility workspace with three virtual environments:
  1. vsbtools notebook/kernel environment from https://github.com/link-lab3629/vsbtools
  2. scout-matter/MatterGen environment from https://github.com/link-lab3629/scout-matter
  3. GRACE/tensorpotential environment

Options:
  --root PATH               Environment workspace root. Default: ./vsbtools_reproducibility_env
  --run-root PATH           Reproducibility output root. Default: ./vsbtools_reproducibility_run
  --python PATH             Python used to create venvs. Default: compatible local Python, otherwise managed Python 3.11
  --vsbtools-ref REF        Git ref for vsbtools. Default: repository default branch
  --scout-matter-ref REF    Git ref for scout-matter. Default: repository default branch
  --no-launch               Install/configure only; do not launch JupyterLab
  --force                   Recreate env workspace internals and output files under --run-root
  -h, --help                Show this help

Environment overrides:
  VSBTOOLS_REPO_URL         Default: containing vsbtools checkout, otherwise https://github.com/link-lab3629/vsbtools.git
  SCOUT_MATTER_REPO_URL     Default: https://github.com/link-lab3629/scout-matter.git
  VSBTOOLS_REF              Default: repository default branch
  SCOUT_MATTER_REF          Default: repository default branch
  PYTHON_BIN                Python used to create venvs
  MANAGED_PYTHON_VERSION    Default: 3.11
  PYTORCH_VERSION           Linux/Windows: 2.2.1+cu118; macOS: 2.4.1
  TORCHVISION_VERSION       Linux/Windows: 0.17.1+cu118; macOS: 0.19.1
  TORCHAUDIO_VERSION        Linux/Windows: 2.2.1+cu118; macOS: 2.4.1
  PYTORCH_CUDA_INDEX_URL    Linux/Windows default: https://download.pytorch.org/whl/cu118
  PYG_WHEEL_URL             Linux/Windows: torch-2.2.1+cu118; macOS: torch-2.4.0+cpu
  VSBTOOLS_REPRO_ROOT       Default: ./vsbtools_reproducibility_env
  VSBTOOLS_REPRO_RUN_ROOT   Default: ./vsbtools_reproducibility_run
All Jupyter, IPython, matplotlib, pip, and vsbtools external-path state is kept
inside --root/state. The script does not write to ~/.config/vsbtools or install
a user/global Jupyter kernel.
USAGE
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        --root)
            ROOT="$2"
            shift 2
            ;;
        --run-root)
            RUN_ROOT="$2"
            shift 2
            ;;
        --python)
            PYTHON_BIN="$2"
            shift 2
            ;;
        --vsbtools-ref)
            VSBTOOLS_REF="$2"
            shift 2
            ;;
        --scout-matter-ref)
            SCOUT_MATTER_REF="$2"
            shift 2
            ;;
        --no-launch)
            LAUNCH=0
            shift
            ;;
        --force)
            FORCE=1
            shift
            ;;
        -h|--help)
            usage
            exit 0
            ;;
        *)
            echo "Unknown argument: $1" >&2
            usage >&2
            exit 2
            ;;
    esac
done

log() {
    printf '\n[%s] %s\n' "$(date '+%H:%M:%S')" "$*"
}

require_cmd() {
    if ! command -v "$1" >/dev/null 2>&1; then
        echo "Required command not found: $1" >&2
        exit 1
    fi
}

venv_executable() {
    local venv="$1"
    local executable="$2"
    if [[ -x "$venv/bin/$executable" ]]; then
        printf '%s\n' "$venv/bin/$executable"
    elif [[ -x "$venv/Scripts/$executable.exe" ]]; then
        printf '%s\n' "$venv/Scripts/$executable.exe"
    elif [[ -x "$venv/Scripts/$executable" ]]; then
        printf '%s\n' "$venv/Scripts/$executable"
    else
        printf '%s\n' "$venv/bin/$executable"
    fi
}

venv_python() {
    venv_executable "$1" python
}

python_version_label() {
    "$1" - <<'PY'
import sys
print(f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}")
PY
}

is_compatible_python() {
    "$1" - <<'PY' >/dev/null 2>&1
import sys

raise SystemExit(0 if (3, 9) <= sys.version_info[:2] <= (3, 11) else 1)
PY
}

install_uv() {
    local bootstrap_python="$1"
    UV_BOOTSTRAP_VENV="$STATE_DIR/uv_bootstrap"
    if [[ ! -x "$(venv_python "$UV_BOOTSTRAP_VENV")" ]]; then
        log "Creating uv bootstrap venv with $bootstrap_python"
        "$bootstrap_python" -m venv "$UV_BOOTSTRAP_VENV"
    fi
    "$(venv_python "$UV_BOOTSTRAP_VENV")" -m pip install --upgrade pip uv
    UV_BIN="$(venv_executable "$UV_BOOTSTRAP_VENV" uv)"
}

install_managed_python() {
    local bootstrap_python="$1"
    local managed_install_dir="$STATE_DIR/uv_python_installations"

    if command -v uv >/dev/null 2>&1; then
        UV_BIN="$(command -v uv)"
    else
        install_uv "$bootstrap_python"
    fi

    log "Installing managed Python $MANAGED_PYTHON_VERSION under $managed_install_dir"
    UV_PYTHON_INSTALL_DIR="$managed_install_dir" "$UV_BIN" python install "$MANAGED_PYTHON_VERSION"
    PYTHON_BIN="$(UV_PYTHON_INSTALL_DIR="$managed_install_dir" "$UV_BIN" python find "$MANAGED_PYTHON_VERSION")"

    if ! is_compatible_python "$PYTHON_BIN"; then
        echo "Managed Python is not compatible: $PYTHON_BIN ($(python_version_label "$PYTHON_BIN"))" >&2
        exit 1
    fi
    log "Using managed Python $PYTHON_BIN ($(python_version_label "$PYTHON_BIN"))"
}

select_python_bin() {
    if [[ -n "$PYTHON_BIN" ]]; then
        require_cmd "$PYTHON_BIN"
        if is_compatible_python "$PYTHON_BIN"; then
            log "Using selected Python $PYTHON_BIN ($(python_version_label "$PYTHON_BIN"))"
            return
        fi
        log "Selected Python $PYTHON_BIN ($(python_version_label "$PYTHON_BIN")) is outside the supported 3.9-3.11 range"
        install_managed_python "$PYTHON_BIN"
        return
    fi
    for candidate in python3.11 python3.10 python3.9 python3; do
        if command -v "$candidate" >/dev/null 2>&1 && is_compatible_python "$candidate"; then
            PYTHON_BIN="$candidate"
            log "Using local Python $PYTHON_BIN ($(python_version_label "$PYTHON_BIN"))"
            return
        fi
    done

    local bootstrap_python=""
    for candidate in python3 python python3.12 python3.13; do
        if command -v "$candidate" >/dev/null 2>&1; then
            bootstrap_python="$candidate"
            break
        fi
    done

    if [[ -z "$bootstrap_python" ]]; then
        echo "Required command not found: python3 or python" >&2
        exit 1
    fi

    log "No local Python 3.9-3.11 found; bootstrapping from $bootstrap_python ($(python_version_label "$bootstrap_python"))"
    install_managed_python "$bootstrap_python"
}

check_python_version() {
    if ! is_compatible_python "$PYTHON_BIN"; then
        echo "Selected Python is not compatible: $PYTHON_BIN ($(python_version_label "$PYTHON_BIN"))" >&2
        echo "The reproducibility venvs need Python 3.9-3.11 for the selected scout-matter dependencies." >&2
        exit 1
    fi
}

clone_or_checkout() {
    local url="$1"
    local ref="$2"
    local dest="$3"
    if [[ -d "$dest/.git" ]]; then
        log "Updating $dest"
        git -C "$dest" remote set-url origin "$url"
        git -C "$dest" fetch --tags --prune origin
    elif [[ -e "$dest" ]]; then
        echo "Path exists but is not a git checkout: $dest" >&2
        exit 1
    else
        log "Cloning $url into $dest"
        git clone "$url" "$dest"
    fi
    if [[ -n "$ref" ]]; then
        git -C "$dest" checkout "$ref"
    else
        local default_ref
        default_ref="$(git -C "$dest" symbolic-ref --quiet --short refs/remotes/origin/HEAD || true)"
        if [[ -n "$default_ref" ]]; then
            local default_branch="${default_ref#origin/}"
            git -C "$dest" checkout "$default_branch"
            git -C "$dest" merge --ff-only "$default_ref"
        else
            log "Using current checkout in $dest"
        fi
    fi
}

make_venv() {
    local venv="$1"
    if [[ ! -x "$(venv_python "$venv")" ]]; then
        log "Creating venv $venv"
        "$PYTHON_BIN" -m venv "$venv"
    fi
    "$(venv_python "$venv")" -m pip install --upgrade pip setuptools wheel
}

prompt_existing_venv() {
    local label="$1"
    local answer=""
    if [[ ! -r /dev/tty || ! -w /dev/tty ]]; then
        printf '\n'
        return
    fi

    printf 'Existing %s venv path [Enter to create under --root]: ' "$label" >/dev/tty
    read -r answer </dev/tty
    if [[ -z "$answer" ]]; then
        printf '\n'
        return
    fi

    answer="${answer/#\~/$HOME}"
    local venv
    venv="$(cd "$answer" 2>/dev/null && pwd || true)"
    if [[ -z "$venv" || ! -x "$(venv_python "$venv")" ]]; then
        echo "$label venv must be a virtual-environment directory containing Python: $answer" >&2
        exit 1
    fi
    printf '%s\n' "$venv"
}

python_site_packages() {
    "$1" - <<'PY'
import sysconfig
print(sysconfig.get_paths()["purelib"])
PY
}

ROOT="$(mkdir -p "$ROOT" && cd "$ROOT" && pwd)"
RUN_ROOT="$(mkdir -p "$RUN_ROOT" && cd "$RUN_ROOT" && pwd)"

if [[ "$FORCE" -eq 1 ]]; then
    log "Removing contained environment directories under $ROOT"
    rm -rf "$ROOT/src" "$ROOT/venvs" "$ROOT/state" "$ROOT/work"
    log "Removing reproducibility outputs under $RUN_ROOT"
    rm -rf "$RUN_ROOT"
fi

require_cmd git

SRC_DIR="$ROOT/src"
VENVS_DIR="$ROOT/venvs"
STATE_DIR="$ROOT/state"
WORK_DIR="$ROOT/work"
mkdir -p "$SRC_DIR" "$VENVS_DIR" "$STATE_DIR" "$WORK_DIR" "$RUN_ROOT"

export XDG_CONFIG_HOME="$STATE_DIR/xdg_config"
export XDG_CACHE_HOME="$STATE_DIR/xdg_cache"
export JUPYTER_CONFIG_DIR="$STATE_DIR/jupyter_config"
export JUPYTER_DATA_DIR="$STATE_DIR/jupyter_data"
export JUPYTER_RUNTIME_DIR="$STATE_DIR/jupyter_runtime"
export IPYTHONDIR="$STATE_DIR/ipython"
export MPLCONFIGDIR="$STATE_DIR/matplotlib"
export PIP_CACHE_DIR="$STATE_DIR/pip_cache"
export VSBTOOLS_EXTERNAL_PATHS_CONFIG="$STATE_DIR/vsbtools_external_paths.json"
mkdir -p "$XDG_CONFIG_HOME" "$XDG_CACHE_HOME" "$JUPYTER_CONFIG_DIR" \
    "$JUPYTER_DATA_DIR" "$JUPYTER_RUNTIME_DIR" "$IPYTHONDIR" "$MPLCONFIGDIR" "$PIP_CACHE_DIR"

EXISTING_VSBTOOLS_VENV="$(prompt_existing_venv "vsbtools/Jupyter")"
EXISTING_SCOUT_VENV="$(prompt_existing_venv "scout-matter/MatterGen")"
EXISTING_GRACE_VENV="$(prompt_existing_venv "GRACE/tensorpotential")"

select_python_bin
check_python_version

VSBTOOLS_SRC="$SRC_DIR/vsbtools"
SCOUT_SRC="$SRC_DIR/scout-matter"
VSBTOOLS_VENV="$VENVS_DIR/vsbtools"
SCOUT_VENV="$VENVS_DIR/scout-matter"
GRACE_VENV="$VENVS_DIR/grace"
if [[ -n "$EXISTING_VSBTOOLS_VENV" ]]; then
    VSBTOOLS_VENV="$EXISTING_VSBTOOLS_VENV"
fi
if [[ -n "$EXISTING_SCOUT_VENV" ]]; then
    SCOUT_VENV="$EXISTING_SCOUT_VENV"
fi
if [[ -n "$EXISTING_GRACE_VENV" ]]; then
    GRACE_VENV="$EXISTING_GRACE_VENV"
fi
clone_or_checkout "$VSBTOOLS_REPO_URL" "$VSBTOOLS_REF" "$VSBTOOLS_SRC"
clone_or_checkout "$SCOUT_MATTER_REPO_URL" "$SCOUT_MATTER_REF" "$SCOUT_SRC"
VSBTOOLS_COMMIT="$(git -C "$VSBTOOLS_SRC" rev-parse HEAD)"
SCOUT_MATTER_COMMIT="$(git -C "$SCOUT_SRC" rev-parse HEAD)"

VSBTOOLS_PYTHON="$(venv_python "$VSBTOOLS_VENV")"
SCOUT_PYTHON="$(venv_python "$SCOUT_VENV")"
GRACE_PYTHON_BIN="$(venv_python "$GRACE_VENV")"

if [[ -n "$EXISTING_SCOUT_VENV" ]]; then
    log "Reusing scout-matter venv $SCOUT_VENV"
else
    make_venv "$SCOUT_VENV"
    SCOUT_PYTHON="$(venv_python "$SCOUT_VENV")"
    log "Installing scout-matter PyTorch/PyG binary dependencies"
    PYTORCH_INDEX_ARGS=()
    if [[ -n "$PYTORCH_CUDA_INDEX_URL" ]]; then
        PYTORCH_INDEX_ARGS=(--extra-index-url "$PYTORCH_CUDA_INDEX_URL")
    fi
    "$SCOUT_PYTHON" -m pip install "${PYTORCH_INDEX_ARGS[@]}" \
        "torch==$PYTORCH_VERSION" \
        "torchvision==$TORCHVISION_VERSION" \
        "torchaudio==$TORCHAUDIO_VERSION"
    PYG_PACKAGES=(torch_scatter \
        torch_sparse \
        torch_cluster \
        torch_spline_conv)
    case "$HOST_OS" in
        Darwin*)
            log "macOS detected; installing the universal2 PyG extensions required by scout-matter"
            ;;
        MINGW*|MSYS*|CYGWIN*)
            log "Windows detected; installing the PyG extensions available for Windows"
            ;;
        *)
            PYG_PACKAGES=(pyg_lib "${PYG_PACKAGES[@]}")
            ;;
    esac
    "$SCOUT_PYTHON" -m pip install --find-links "$PYG_WHEEL_URL" --only-binary :all: \
        "${PYG_PACKAGES[@]}"

    log "Installing scout-matter into its contained venv"
    if ! "$SCOUT_PYTHON" -m pip install "${PYTORCH_INDEX_ARGS[@]}" --find-links "$PYG_WHEEL_URL" "$SCOUT_SRC"; then
        log "Non-editable scout-matter install failed; trying editable install"
        "$SCOUT_PYTHON" -m pip install "${PYTORCH_INDEX_ARGS[@]}" --find-links "$PYG_WHEEL_URL" -e "$SCOUT_SRC"
    fi
    "$SCOUT_PYTHON" - <<'PY'
import mattergen
print("mattergen:", mattergen.__file__)
PY
fi
SCOUT_SITE_PACKAGES="$(python_site_packages "$SCOUT_PYTHON")"

if [[ -n "$EXISTING_GRACE_VENV" ]]; then
    log "Reusing GRACE/tensorpotential venv $GRACE_VENV"
else
    make_venv "$GRACE_VENV"
    GRACE_PYTHON_BIN="$(venv_python "$GRACE_VENV")"
    log "Installing GRACE/tensorpotential into its contained venv"
    "$GRACE_PYTHON_BIN" -m pip install "ase<3.26" tensorpotential
    "$GRACE_PYTHON_BIN" - <<'PY'
import tensorpotential.calculator
print("tensorpotential.calculator import OK")
PY
fi

if [[ -n "$EXISTING_VSBTOOLS_VENV" ]]; then
    log "Reusing vsbtools notebook/kernel venv $VSBTOOLS_VENV"
else
    make_venv "$VSBTOOLS_VENV"
    VSBTOOLS_PYTHON="$(venv_python "$VSBTOOLS_VENV")"
    log "Installing vsbtools notebook/kernel environment"
    "$VSBTOOLS_PYTHON" -m pip install -e "$VSBTOOLS_SRC"
    "$VSBTOOLS_PYTHON" -m pip install \
        dscribe \
        ijson \
        jupyterlab \
        ipykernel \
        nbconvert \
        matplotlib \
        mp-api \
        networkx \
        pandas \
        prettytable \
        pymatgen \
        PyYAML \
        scipy \
        torch
    if "$VSBTOOLS_PYTHON" -m pip install mysqlclient; then
        log "Optional mysqlclient dependency installed"
    else
        log "Optional mysqlclient dependency failed to install; continuing because this notebook does not use local OQMD/MySQL"
    fi
fi

export MATTERGEN_PYTHON_PATH="$SCOUT_SITE_PACKAGES"
export GRACE_PYTHON="$GRACE_PYTHON_BIN"

log "Validating bridge imports from the vsbtools venv"
"$VSBTOOLS_PYTHON" - <<'PY'
import os
import sys
from pathlib import Path

sys.path.append(os.environ["MATTERGEN_PYTHON_PATH"])
import mattergen.common.data.chemgraph
import mattergen.diffusion.diffusion_loss

import vsbtools
import vsbtools.materials_dataset
print("vsbtools:", Path(vsbtools.__file__).resolve())
print("MATTERGEN_PYTHON_PATH:", os.environ["MATTERGEN_PYTHON_PATH"])
print("GRACE_PYTHON:", os.environ["GRACE_PYTHON"])
PY

NOTEBOOK_SRC="$VSBTOOLS_SRC/vsbtools/materials_dataset/Examples/mg_generation_postprocessing_pipeline.ipynb"
if [[ ! -f "$NOTEBOOK_SRC" && -f "$SCRIPT_DIR/mg_generation_postprocessing_pipeline.ipynb" ]]; then
    NOTEBOOK_SRC="$SCRIPT_DIR/mg_generation_postprocessing_pipeline.ipynb"
fi
if [[ ! -f "$NOTEBOOK_SRC" ]]; then
    echo "Could not find mg_generation_postprocessing_pipeline.ipynb in cloned vsbtools or beside this script." >&2
    exit 1
fi
NOTEBOOK_DST="$WORK_DIR/mg_generation_postprocessing_pipeline.ipynb"
cp "$NOTEBOOK_SRC" "$NOTEBOOK_DST"
"$VSBTOOLS_PYTHON" - "$NOTEBOOK_DST" <<'PY'
import json
import sys
from pathlib import Path

path = Path(sys.argv[1])
notebook = json.loads(path.read_text())
notebook.setdefault("metadata", {})["kernelspec"] = {
    "display_name": "vsbtools reproducibility",
    "language": "python",
    "name": "vsbtools-repro",
}
path.write_text(json.dumps(notebook, indent=1) + "\n")
PY

KERNEL_PREFIX="$STATE_DIR/jupyter_kernel_prefix"
"$VSBTOOLS_PYTHON" -m ipykernel install \
    --prefix "$KERNEL_PREFIX" \
    --name vsbtools-repro \
    --display-name "vsbtools reproducibility"

ENV_FILE="$ROOT/reproducibility_env.sh"
cat > "$ENV_FILE" <<EOF
#!/usr/bin/env bash
export VSBTOOLS_REPRO_ROOT="$ROOT"
export VSBTOOLS_REPRO_RUN_ROOT="$RUN_ROOT"
export VSBTOOLS_SRC="$VSBTOOLS_SRC"
export SCOUT_MATTER_SRC="$SCOUT_SRC"
export VSBTOOLS_COMMIT="$VSBTOOLS_COMMIT"
export SCOUT_MATTER_COMMIT="$SCOUT_MATTER_COMMIT"
export REPRODUCIBILITY_PYTHON="$PYTHON_BIN"
export MANAGED_PYTHON_VERSION="$MANAGED_PYTHON_VERSION"
export PYTORCH_VERSION="$PYTORCH_VERSION"
export TORCHVISION_VERSION="$TORCHVISION_VERSION"
export TORCHAUDIO_VERSION="$TORCHAUDIO_VERSION"
export PYTORCH_CUDA_INDEX_URL="$PYTORCH_CUDA_INDEX_URL"
export PYG_WHEEL_URL="$PYG_WHEEL_URL"
export VSBTOOLS_VENV="$VSBTOOLS_VENV"
export SCOUT_MATTER_VENV="$SCOUT_VENV"
export GRACE_VENV="$GRACE_VENV"
export VSBTOOLS_PYTHON="$VSBTOOLS_PYTHON"
export SCOUT_PYTHON="$SCOUT_PYTHON"
export MATTERGEN_PYTHON_PATH="$MATTERGEN_PYTHON_PATH"
export GRACE_PYTHON="$GRACE_PYTHON"
export PATH="$(dirname "$VSBTOOLS_PYTHON"):\$PATH"
export XDG_CONFIG_HOME="$XDG_CONFIG_HOME"
export XDG_CACHE_HOME="$XDG_CACHE_HOME"
export JUPYTER_CONFIG_DIR="$JUPYTER_CONFIG_DIR"
export JUPYTER_DATA_DIR="$JUPYTER_DATA_DIR"
export JUPYTER_RUNTIME_DIR="$JUPYTER_RUNTIME_DIR"
export JUPYTER_PATH="$KERNEL_PREFIX/share/jupyter"
export IPYTHONDIR="$IPYTHONDIR"
export MPLCONFIGDIR="$MPLCONFIGDIR"
export PIP_CACHE_DIR="$PIP_CACHE_DIR"
export VSBTOOLS_EXTERNAL_PATHS_CONFIG="$VSBTOOLS_EXTERNAL_PATHS_CONFIG"
EOF
chmod +x "$ENV_FILE"

SETUP_MANIFEST="$ROOT/setup_manifest.json"
cat > "$SETUP_MANIFEST" <<EOF
{
  "vsbtools_repo_url": "$VSBTOOLS_REPO_URL",
  "vsbtools_ref": "$VSBTOOLS_REF",
  "vsbtools_commit": "$VSBTOOLS_COMMIT",
  "scout_matter_repo_url": "$SCOUT_MATTER_REPO_URL",
  "scout_matter_ref": "$SCOUT_MATTER_REF",
  "scout_matter_commit": "$SCOUT_MATTER_COMMIT",
  "root": "$ROOT",
  "run_root": "$RUN_ROOT",
  "host_os": "$HOST_OS",
  "reproducibility_python": "$PYTHON_BIN",
  "managed_python_version": "$MANAGED_PYTHON_VERSION",
  "pytorch_version": "$PYTORCH_VERSION",
  "torchvision_version": "$TORCHVISION_VERSION",
  "torchaudio_version": "$TORCHAUDIO_VERSION",
  "pytorch_cuda_index_url": "$PYTORCH_CUDA_INDEX_URL",
  "pyg_wheel_url": "$PYG_WHEEL_URL",
  "vsbtools_venv": "$VSBTOOLS_VENV",
  "scout_matter_venv": "$SCOUT_VENV",
  "grace_venv": "$GRACE_VENV",
  "mattergen_python_path": "$MATTERGEN_PYTHON_PATH",
  "grace_python": "$GRACE_PYTHON"
}
EOF

LAUNCHER="$ROOT/run_reproducibility_notebook.sh"
cat > "$LAUNCHER" <<EOF
#!/usr/bin/env bash
set -euo pipefail
source "$ENV_FILE"
cd "$WORK_DIR"
exec "$VSBTOOLS_PYTHON" -m jupyter lab \\
    --notebook-dir "$WORK_DIR" \\
    "$NOTEBOOK_DST"
EOF
chmod +x "$LAUNCHER"

TEST_RUNNER="$ROOT/test_reproducibility_notebook.sh"
cat > "$TEST_RUNNER" <<EOF
#!/usr/bin/env bash
set -euo pipefail
source "$ENV_FILE"
cd "$WORK_DIR"

executed_notebook="$WORK_DIR/mg_generation_postprocessing_pipeline.executed.ipynb"

set +e
"$VSBTOOLS_PYTHON" -m jupyter nbconvert \\
    --to notebook \\
    --execute "$NOTEBOOK_DST" \\
    --output "\$(basename "\$executed_notebook")" \\
    --output-dir "$WORK_DIR" \\
    --ExecutePreprocessor.kernel_name=vsbtools-repro \\
    --ExecutePreprocessor.timeout=-1
status=\$?
set -e

if [[ "\$status" -ne 0 ]]; then
    echo "Reproducibility notebook test failed; preserving outputs under $RUN_ROOT" >&2
else
    echo "Reproducibility notebook test passed; outputs preserved under $RUN_ROOT"
fi

exit "\$status"
EOF
chmod +x "$TEST_RUNNER"

log "Contained reproducibility environment is ready"
cat <<EOF

Workspace:
  $ROOT

Virtual environments:
  vsbtools:      $VSBTOOLS_VENV
  scout-matter:  $SCOUT_VENV
  GRACE:         $GRACE_VENV

Notebook copy:
  $NOTEBOOK_DST

Run outputs:
  $RUN_ROOT

Environment file:
  $ENV_FILE

Setup manifest:
  $SETUP_MANIFEST

Launcher:
  $LAUNCHER

Headless test runner:
  $TEST_RUNNER

EOF

if [[ "$LAUNCH" -eq 1 ]]; then
    log "Launching JupyterLab"
    exec "$LAUNCHER"
else
    log "Launch skipped. Run this later:"
    echo "  $LAUNCHER"
fi
