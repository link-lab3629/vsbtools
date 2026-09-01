#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CODE_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

VSBTOOLS_SOURCE="$SCRIPT_DIR"
MATTERGEN_SOURCE="$CODE_ROOT/scout-matter"
ENV_ROOT="$CODE_ROOT/workflow-env"
PYTHON_BIN="${PYTHON_BIN:-python3}"
INSTALL_MODE="editable"
INSTALL_GRACE=1
VSBTOOLS_REF=""
MATTERGEN_REF=""
FETCH_SOURCES=0

NUMPY_VERSION="${NUMPY_VERSION:-1.26.4}"
# MatterGen 1.0.3 has lower bounds for these packages, so an otherwise fresh
# install can resolve a newer Emmet/Pymatgen API pair that is incompatible with
# MatterGen's imports (for example, emmet-core 0.87 expects pymatgen.core.graphs).
MATTERGEN_EMMET_CORE_VERSION="${MATTERGEN_EMMET_CORE_VERSION:-0.84.9}"
MATTERGEN_PYMATGEN_VERSION="${MATTERGEN_PYMATGEN_VERSION:-2024.10.29}"
PYTORCH_VERSION="${PYTORCH_VERSION:-}"
TORCHVISION_VERSION="${TORCHVISION_VERSION:-}"
TORCHAUDIO_VERSION="${TORCHAUDIO_VERSION:-}"
PYTORCH_INDEX_URL="${PYTORCH_INDEX_URL:-}"
PYG_WHEEL_URL="${PYG_WHEEL_URL:-}"

usage() {
    cat <<'EOF'
Usage: install_vsbtools_mattergen.sh [OPTIONS]

Creates reusable VSBTools, MatterGen, and GRACE virtual environments from
persistent local source checkouts. VSBTools and MatterGen are editable by
default, so source edits are visible after restarting Python or Jupyter.

Options:
  --vsbtools-source PATH   VSBTools checkout (default: directory containing this script)
  --mattergen-source PATH  scout-matter/MatterGen checkout (default: sibling scout-matter)
  --env-root PATH          Environment root (default: sibling workflow-env)
  --python PATH            Python 3.11 or newer used to create environments
  --vsbtools-ref REF       VSBTools branch, tag, or commit to check out
  --mattergen-ref REF      MatterGen branch, tag, or commit to check out
  --fetch                  Fetch origin before resolving requested refs; local
                           branches are then fast-forwarded when possible
  --editable               Install VSBTools and MatterGen editably (default)
  --regular                Install regular source snapshots into the environments
  --no-grace               Skip the GRACE/tensorpotential environment
  -h, --help               Show this help

Environment:
  NUMPY_VERSION             NumPy version for the MatterGen and VSBTools
                            environments (default: 1.26.4; must be <2)
  MATTERGEN_EMMET_CORE_VERSION
                            emmet-core version for MatterGen (default: 0.84.9)
  MATTERGEN_PYMATGEN_VERSION
                            pymatgen version paired with it (default: 2024.10.29)

Editable-install disclaimer:
  Later source edits change future runs. Preserve commit hashes and any
  uncommitted patch with important results. Use --regular for environments
  whose imports should remain unchanged when the checkouts are edited.

Example using selected branches:
  ./install_vsbtools_mattergen.sh --vsbtools-ref analysis-dev \
    --mattergen-ref guided-generation --fetch
EOF
}

fail() {
    printf 'Error: %s\n' "$*" >&2
    exit 2
}

missing_value() {
    fail "$1 requires a value"
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        --vsbtools-source)
            [[ $# -ge 2 ]] || missing_value "$1"
            VSBTOOLS_SOURCE="$2"
            shift 2
            ;;
        --mattergen-source)
            [[ $# -ge 2 ]] || missing_value "$1"
            MATTERGEN_SOURCE="$2"
            shift 2
            ;;
        --env-root)
            [[ $# -ge 2 ]] || missing_value "$1"
            ENV_ROOT="$2"
            shift 2
            ;;
        --python)
            [[ $# -ge 2 ]] || missing_value "$1"
            PYTHON_BIN="$2"
            shift 2
            ;;
        --vsbtools-ref)
            [[ $# -ge 2 ]] || missing_value "$1"
            VSBTOOLS_REF="$2"
            shift 2
            ;;
        --mattergen-ref|--scout-matter-ref)
            [[ $# -ge 2 ]] || missing_value "$1"
            MATTERGEN_REF="$2"
            shift 2
            ;;
        --fetch)
            FETCH_SOURCES=1
            shift
            ;;
        --editable)
            INSTALL_MODE="editable"
            shift
            ;;
        --regular)
            INSTALL_MODE="regular"
            shift
            ;;
        --no-grace)
            INSTALL_GRACE=0
            shift
            ;;
        -h|--help)
            usage
            exit 0
            ;;
        *)
            fail "unknown option '$1'; run with --help for usage"
            ;;
    esac
done

if [[ "$NUMPY_VERSION" =~ ^2([.]|$) ]]; then
    fail "NUMPY_VERSION=$NUMPY_VERSION is incompatible with MatterGen's numpy<2 requirement"
fi

log() {
    printf '\n[%s] %s\n' "$(date '+%H:%M:%S')" "$*"
}

require_command() {
    command -v "$1" >/dev/null 2>&1 || fail "required command not found: $1"
}

canonical_directory() {
    [[ -d "$1" ]] || fail "directory does not exist: $1"
    (cd "$1" && pwd)
}

git_commit() {
    git -C "$1" rev-parse HEAD 2>/dev/null || printf 'not-a-git-checkout\n'
}

git_dirty() {
    if git -C "$1" diff --quiet --ignore-submodules HEAD -- 2>/dev/null \
        && [[ -z "$(git -C "$1" ls-files --others --exclude-standard 2>/dev/null)" ]]; then
        printf 'false\n'
    else
        printf 'true\n'
    fi
}

git_branch() {
    git -C "$1" symbolic-ref --quiet --short HEAD 2>/dev/null \
        || printf 'detached\n'
}

checkout_source_ref() {
    local source="$1"
    local ref="$2"
    local label="$3"
    local branch_name

    [[ -n "$ref" ]] || return 0
    git -C "$source" rev-parse --git-dir >/dev/null 2>&1 \
        || fail "$label source is not a Git checkout: $source"
    if [[ -n "$(git -C "$source" status --porcelain --untracked-files=normal)" ]]; then
        fail "$label checkout has uncommitted or untracked files; preserve them before selecting '$ref'"
    fi

    if [[ "$FETCH_SOURCES" -eq 1 ]]; then
        log "Fetching $label refs from origin"
        git -C "$source" fetch --tags --prune origin
    fi

    branch_name="${ref#refs/heads/}"
    branch_name="${branch_name#origin/}"
    if git -C "$source" show-ref --verify --quiet "refs/heads/$branch_name"; then
        git -C "$source" checkout "$branch_name"
        if [[ "$FETCH_SOURCES" -eq 1 ]] \
            && git -C "$source" show-ref --verify --quiet \
                "refs/remotes/origin/$branch_name"; then
            git -C "$source" merge --ff-only "origin/$branch_name"
        fi
    elif git -C "$source" show-ref --verify --quiet \
        "refs/remotes/origin/$branch_name"; then
        git -C "$source" checkout --track -b "$branch_name" "origin/$branch_name"
    elif git -C "$source" rev-parse --verify "${ref}^{commit}" >/dev/null 2>&1; then
        git -C "$source" checkout --detach "$ref"
    else
        fail "$label ref '$ref' was not found; rerun with --fetch if it exists on origin"
    fi

    log "$label source: $(git_branch "$source") at $(git_commit "$source")"
}

make_venv() {
    local venv="$1"
    if [[ ! -x "$venv/bin/python" ]]; then
        log "Creating $venv"
        "$PYTHON_BIN" -m venv "$venv"
    fi
    # MatterGen's pinned PyTorch Lightning still imports pkg_resources,
    # which was removed from newer setuptools releases.
    "$venv/bin/python" -m pip install --upgrade pip "setuptools<81" wheel
}

pip_with_pytorch_index() {
    local python="$1"
    shift
    if [[ -n "$PYTORCH_INDEX_URL" ]]; then
        "$python" -m pip install --extra-index-url "$PYTORCH_INDEX_URL" "$@"
    else
        "$python" -m pip install "$@"
    fi
}

enforce_numpy_version() {
    local python="$1"
    local label="$2"

    log "Enforcing NumPy $NUMPY_VERSION in the $label environment"
    "$python" -m pip install --force-reinstall --no-deps \
        "numpy==$NUMPY_VERSION"
}

check_numpy_version() {
    local python="$1"
    local label="$2"
    local installed

    installed="$("$python" -c 'import numpy; print(numpy.__version__)')"
    [[ "$installed" == "$NUMPY_VERSION" ]] \
        || fail "$label environment has NumPy $installed; expected $NUMPY_VERSION"
}

enforce_mattergen_api_versions() {
    log "Enforcing MatterGen-compatible Emmet/Pymatgen versions"
    "$MATTERGEN_PYTHON" -m pip install --force-reinstall --no-deps \
        "emmet-core==$MATTERGEN_EMMET_CORE_VERSION" \
        "pymatgen==$MATTERGEN_PYMATGEN_VERSION"
}

check_mattergen_api_versions() {
    local installed_emmet installed_pymatgen

    installed_emmet="$("$MATTERGEN_PYTHON" -c \
        'from importlib.metadata import version; print(version("emmet-core"))')"
    installed_pymatgen="$("$MATTERGEN_PYTHON" -c \
        'from importlib.metadata import version; print(version("pymatgen"))')"

    [[ "$installed_emmet" == "$MATTERGEN_EMMET_CORE_VERSION" ]] \
        || fail "MatterGen environment has emmet-core $installed_emmet; expected $MATTERGEN_EMMET_CORE_VERSION"
    [[ "$installed_pymatgen" == "$MATTERGEN_PYMATGEN_VERSION" ]] \
        || fail "MatterGen environment has pymatgen $installed_pymatgen; expected $MATTERGEN_PYMATGEN_VERSION"
}

require_command git
require_command "$PYTHON_BIN"

VSBTOOLS_SOURCE="$(canonical_directory "$VSBTOOLS_SOURCE")"
MATTERGEN_SOURCE="$(canonical_directory "$MATTERGEN_SOURCE")"
checkout_source_ref "$VSBTOOLS_SOURCE" "$VSBTOOLS_REF" "VSBTools"
checkout_source_ref "$MATTERGEN_SOURCE" "$MATTERGEN_REF" "MatterGen"
[[ -f "$VSBTOOLS_SOURCE/pyproject.toml" ]] \
    || fail "VSBTools pyproject.toml is missing under $VSBTOOLS_SOURCE"
[[ -f "$MATTERGEN_SOURCE/pyproject.toml" ]] \
    || fail "MatterGen pyproject.toml is missing under $MATTERGEN_SOURCE"

if ! "$PYTHON_BIN" - <<'PY'
import sys
raise SystemExit(0 if sys.version_info[:2] >= (3, 11) else 1)
PY
then
    fail "$PYTHON_BIN must be Python 3.11 or newer"
fi

HOST_OS="$(uname -s)"
case "$HOST_OS" in
    Darwin*)
        PYTORCH_VERSION="${PYTORCH_VERSION:-2.4.1}"
        TORCHVISION_VERSION="${TORCHVISION_VERSION:-0.19.1}"
        TORCHAUDIO_VERSION="${TORCHAUDIO_VERSION:-2.4.1}"
        PYG_WHEEL_URL="${PYG_WHEEL_URL:-https://data.pyg.org/whl/torch-2.4.0+cpu.html}"
        ;;
    Linux*)
        PYTORCH_VERSION="${PYTORCH_VERSION:-2.2.1+cu118}"
        TORCHVISION_VERSION="${TORCHVISION_VERSION:-0.17.1+cu118}"
        TORCHAUDIO_VERSION="${TORCHAUDIO_VERSION:-2.2.1+cu118}"
        PYTORCH_INDEX_URL="${PYTORCH_INDEX_URL:-https://download.pytorch.org/whl/cu118}"
        PYG_WHEEL_URL="${PYG_WHEEL_URL:-https://data.pyg.org/whl/torch-2.2.1+cu118.html}"
        ;;
    *)
        fail "unsupported operating system: $HOST_OS"
        ;;
esac

ENV_ROOT="$(mkdir -p "$ENV_ROOT" && cd "$ENV_ROOT" && pwd)"
VENVS_DIR="$ENV_ROOT/venvs"
STATE_DIR="$ENV_ROOT/state"
mkdir -p "$VENVS_DIR" "$STATE_DIR"

VSBTOOLS_VENV="$VENVS_DIR/vsbtools"
MATTERGEN_VENV="$VENVS_DIR/scout-matter"
GRACE_VENV="$VENVS_DIR/grace"

make_venv "$MATTERGEN_VENV"
MATTERGEN_PYTHON="$MATTERGEN_VENV/bin/python"

log "Installing MatterGen binary dependencies"
"$MATTERGEN_PYTHON" -m pip install "numpy==$NUMPY_VERSION"
pip_with_pytorch_index "$MATTERGEN_PYTHON" \
    "torch==$PYTORCH_VERSION" \
    "torchvision==$TORCHVISION_VERSION" \
    "torchaudio==$TORCHAUDIO_VERSION"

PYG_PACKAGES=(torch_scatter torch_sparse torch_cluster torch_spline_conv)
if [[ "$HOST_OS" == Linux* ]]; then
    PYG_PACKAGES=(pyg_lib "${PYG_PACKAGES[@]}")
fi
"$MATTERGEN_PYTHON" -m pip install \
    --find-links "$PYG_WHEEL_URL" \
    --only-binary :all: \
    "${PYG_PACKAGES[@]}"

if [[ "$INSTALL_MODE" == "editable" ]]; then
    log "Installing MatterGen editably from $MATTERGEN_SOURCE"
    pip_with_pytorch_index "$MATTERGEN_PYTHON" \
        --find-links "$PYG_WHEEL_URL" -e "$MATTERGEN_SOURCE"
else
    log "Installing a regular MatterGen package from $MATTERGEN_SOURCE"
    pip_with_pytorch_index "$MATTERGEN_PYTHON" \
        --find-links "$PYG_WHEEL_URL" "$MATTERGEN_SOURCE"
fi

# MatterGen's lower-bound requirements otherwise allow pip to combine its
# 1.0.3 code with a newer emmet-core that imports a different Pymatgen API.
# Install the compatible pair explicitly so rerunning this script also repairs
# an already-created environment.
enforce_mattergen_api_versions
check_mattergen_api_versions

make_venv "$VSBTOOLS_VENV"
VSBTOOLS_PYTHON="$VSBTOOLS_VENV/bin/python"

log "Installing the VSBTools analysis environment"
"$VSBTOOLS_PYTHON" -m pip install "numpy==$NUMPY_VERSION"
if [[ "$INSTALL_MODE" == "editable" ]]; then
    "$VSBTOOLS_PYTHON" -m pip install -e "$VSBTOOLS_SOURCE"
else
    "$VSBTOOLS_PYTHON" -m pip install "$VSBTOOLS_SOURCE"
fi
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
    scipy
pip_with_pytorch_index "$VSBTOOLS_PYTHON" "torch==$PYTORCH_VERSION"

if [[ "$INSTALL_GRACE" -eq 1 ]]; then
    make_venv "$GRACE_VENV"
    GRACE_PYTHON="$GRACE_VENV/bin/python"
    log "Installing GRACE/tensorpotential"
    "$GRACE_PYTHON" -m pip install "ase<3.26" tensorpotential
    "$GRACE_PYTHON" - <<'PY'
import tensorpotential.calculator
print("tensorpotential.calculator import OK")
PY
else
    GRACE_PYTHON=""
fi

# MatterGen pins NumPy below 2, and the selected PyTorch wheels use the NumPy
# 1.x C ABI. Reapply the pin after every package installation because a later
# dependency resolver can otherwise upgrade the VSBTools environment to NumPy 2.
enforce_numpy_version "$MATTERGEN_PYTHON" "MatterGen"
enforce_numpy_version "$VSBTOOLS_PYTHON" "VSBTools"
check_numpy_version "$MATTERGEN_PYTHON" "MatterGen"
check_numpy_version "$VSBTOOLS_PYTHON" "VSBTools"

log "Validating MatterGen CLI imports"
"$MATTERGEN_PYTHON" - <<'PY'
from importlib.metadata import version
from pathlib import Path

import mattergen
from mattergen.scripts.generate import _main
import torch

print("mattergen:", Path(mattergen.__file__).resolve())
print("emmet-core:", version("emmet-core"))
print("pymatgen:", version("pymatgen"))
print("torch:", torch.__version__)
PY

MATTERGEN_IMPORT_ROOT="$("$MATTERGEN_PYTHON" - <<'PY'
from pathlib import Path
import mattergen
print(Path(mattergen.__file__).resolve().parent.parent)
PY
)"
MATTERGEN_SITE_PACKAGES="$("$MATTERGEN_PYTHON" - <<'PY'
import sysconfig
print(sysconfig.get_paths()["purelib"])
PY
)"

export MATTERGEN_IMPORT_ROOT MATTERGEN_SITE_PACKAGES
log "Validating VSBTools/MatterGen bridge imports"
"$VSBTOOLS_PYTHON" - <<'PY'
import os
import sys
from pathlib import Path

sys.path.insert(0, os.environ["MATTERGEN_IMPORT_ROOT"])
sys.path.append(os.environ["MATTERGEN_SITE_PACKAGES"])

import mattergen
import torch
import vsbtools

print("vsbtools:", Path(vsbtools.__file__).resolve())
print("mattergen:", Path(mattergen.__file__).resolve())
print("torch:", torch.__version__)
PY

VSBTOOLS_COMMIT="$(git_commit "$VSBTOOLS_SOURCE")"
MATTERGEN_COMMIT="$(git_commit "$MATTERGEN_SOURCE")"
VSBTOOLS_BRANCH="$(git_branch "$VSBTOOLS_SOURCE")"
MATTERGEN_BRANCH="$(git_branch "$MATTERGEN_SOURCE")"
VSBTOOLS_DIRTY="$(git_dirty "$VSBTOOLS_SOURCE")"
MATTERGEN_DIRTY="$(git_dirty "$MATTERGEN_SOURCE")"

ENV_FILE="$ENV_ROOT/workflow_env.sh"
{
    printf '#!/usr/bin/env bash\n'
    printf 'export VSBTOOLS_INSTALL_MODE=%q\n' "$INSTALL_MODE"
    printf 'export VSBTOOLS_REF=%q\n' "$VSBTOOLS_REF"
    printf 'export MATTERGEN_REF=%q\n' "$MATTERGEN_REF"
    printf 'export VSBTOOLS_SOURCE=%q\n' "$VSBTOOLS_SOURCE"
    printf 'export MATTERGEN_SOURCE=%q\n' "$MATTERGEN_SOURCE"
    printf 'export VSBTOOLS_VENV=%q\n' "$VSBTOOLS_VENV"
    printf 'export MATTERGEN_VENV=%q\n' "$MATTERGEN_VENV"
    printf 'export GRACE_VENV=%q\n' "$GRACE_VENV"
    printf 'export VSBTOOLS_PYTHON=%q\n' "$VSBTOOLS_PYTHON"
    printf 'export MATTERGEN_PYTHON=%q\n' "$MATTERGEN_PYTHON"
    printf 'export GRACE_PYTHON=%q\n' "$GRACE_PYTHON"
    printf 'export MATTERGEN_EMMET_CORE_VERSION=%q\n' "$MATTERGEN_EMMET_CORE_VERSION"
    printf 'export MATTERGEN_PYMATGEN_VERSION=%q\n' "$MATTERGEN_PYMATGEN_VERSION"
    printf 'export MATTERGEN_PYTHON_PATH=%q\n' "$MATTERGEN_IMPORT_ROOT"
    printf 'export SCOUT_MATTER_SITE_PACKAGES=%q\n' "$MATTERGEN_SITE_PACKAGES"
    printf 'export VSBTOOLS_EXTERNAL_PATHS_CONFIG=%q\n' \
        "$STATE_DIR/vsbtools_external_paths.json"
    printf 'export PATH=%q:$PATH\n' "$VSBTOOLS_VENV/bin"
} > "$ENV_FILE"
chmod +x "$ENV_FILE"

MANIFEST="$ENV_ROOT/installation_manifest.json"
cat > "$MANIFEST" <<EOF
{
  "install_mode": "$INSTALL_MODE",
  "vsbtools_source": "$VSBTOOLS_SOURCE",
  "vsbtools_requested_ref": "$VSBTOOLS_REF",
  "vsbtools_branch": "$VSBTOOLS_BRANCH",
  "vsbtools_commit": "$VSBTOOLS_COMMIT",
  "vsbtools_dirty": $VSBTOOLS_DIRTY,
  "mattergen_source": "$MATTERGEN_SOURCE",
  "mattergen_requested_ref": "$MATTERGEN_REF",
  "mattergen_branch": "$MATTERGEN_BRANCH",
  "mattergen_commit": "$MATTERGEN_COMMIT",
  "mattergen_dirty": $MATTERGEN_DIRTY,
  "vsbtools_python": "$VSBTOOLS_PYTHON",
  "mattergen_python": "$MATTERGEN_PYTHON",
  "grace_python": "$GRACE_PYTHON",
  "pytorch_version": "$PYTORCH_VERSION",
  "numpy_version": "$NUMPY_VERSION",
  "mattergen_emmet_core_version": "$MATTERGEN_EMMET_CORE_VERSION",
  "mattergen_pymatgen_version": "$MATTERGEN_PYMATGEN_VERSION"
}
EOF

JUPYTER_LAUNCHER="$ENV_ROOT/launch_jupyter.sh"
cat > "$JUPYTER_LAUNCHER" <<EOF
#!/usr/bin/env bash
set -euo pipefail
source "$ENV_FILE"
exec "$VSBTOOLS_PYTHON" -m jupyter lab "\$@"
EOF
chmod +x "$JUPYTER_LAUNCHER"

cat <<EOF

Reusable workflow environments are ready.

Install mode:
  $INSTALL_MODE

Live sources:
  VSBTools:  $VSBTOOLS_SOURCE ($VSBTOOLS_BRANCH, $VSBTOOLS_COMMIT)
  MatterGen: $MATTERGEN_SOURCE ($MATTERGEN_BRANCH, $MATTERGEN_COMMIT)

Virtual environments:
  VSBTools:  $VSBTOOLS_VENV
  MatterGen: $MATTERGEN_VENV
  GRACE:     $GRACE_VENV

Load paths in a new terminal:
  source "$ENV_FILE"

Launch Jupyter from the desired work directory:
  "$JUPYTER_LAUNCHER"

Installation manifest:
  $MANIFEST
EOF
