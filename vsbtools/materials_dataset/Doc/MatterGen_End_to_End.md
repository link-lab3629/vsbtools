# MatterGen to VSBTools: generation and analysis

This guide has two parts:

1. install the software under `CODE_ROOT`;
2. organize `WORK_ROOT` by chemical system, then generate and postprocess.

The examples use `Ni-Pd-H` and target `CN([Pd,Ni]-H) = 6`. Replace the system,
species, target, GPU, and guidance settings as needed.

## Quick start: three reusable files

Once the installation under `CODE_ROOT` is available, the reusable workflow
uses one generation script, one notebook, and one launcher. Choose a system
directory, generate the desired settings, launch the copied notebook, and run
its cells:

```bash
SYSTEM_ROOT="$PWD/mattergen-project/work/Ni-Pd-H"

# Unguided setting; the chemical system defaults to the directory name.
./generate_mattergen.sh "$SYSTEM_ROOT" --runs 1 --batch-size 20

# Guided setting; a new gen_N is selected automatically.
./generate_mattergen.sh "$SYSTEM_ROOT" --runs 10 \
  --guidance "{'group_coordination': {'mode':'huber', 'alpha':3.0, '[Pd,Ni]-H':6}}"

# Copies mattergen_analysis.ipynb to SYSTEM_ROOT/analysis-run/ and opens Jupyter.
./launch_mattergen_analysis.sh "$SYSTEM_ROOT"
```

The root-level files are:

- `generate_mattergen.sh` — unified guided/unguided generation with `gen_N/run_N`
  organization.
- `mattergen_analysis.ipynb` — editable YAML scenario plus all processing,
  summary, histogram/KDE, Pareto, and manifest cells.
- `launch_mattergen_analysis.sh` — environment-aware notebook launcher that
  preserves system-local edits.

The scripts locate `workflow_env.sh` through `--env-root`,
`VSBTOOLS_WORKFLOW_ENV`, the system marker `.vsbtools-env-root`, or the default
repository layout. Supply `--env-root PATH` on the first command when the
managed environments live elsewhere; subsequent commands remember it. Use
`--refresh` on the launcher to copy a fresh template into `analysis-run/`.

## 1. Install the code

### 1.1 Prepare Linux or macOS

Run these commands in a terminal. The installer requires Python 3.11 or newer.
Internet access is needed for GitHub, Python packages, MatterGen checkpoints,
GRACE, and OPTIMADE data.

On Linux, an NVIDIA GPU is strongly recommended; the installer uses CUDA 11.8
PyTorch wheels by default. On macOS, the installer selects CPU-compatible
wheels automatically. MatterGen can fall back to CPU, although generation and
energy estimation will be much slower.

#### 1.1.1 Install operating-system prerequisites

Debian or Ubuntu:

```bash
sudo apt update
sudo apt install -y git build-essential python3 python3-venv python3-dev
```

Fedora or RHEL:

```bash
sudo dnf install -y git gcc gcc-c++ make python3 python3-devel
```

macOS with Homebrew:

```bash
xcode-select --install
brew install git python
```

If Xcode command-line tools are already installed, continue. Conda users can
skip the Homebrew Python install; the Conda environment supplies Python and Git.

### 1.2 Set up the code root

Choose a parent directory and define the project, code, and work roots:

```bash
export PROJECT_ROOT="$PWD/mattergen-project"
export CODE_ROOT="$PROJECT_ROOT/code"
export WORK_ROOT="$PROJECT_ROOT/work"

mkdir -p "$CODE_ROOT" "$WORK_ROOT"
```

Keep source checkouts and virtual environments under `CODE_ROOT`. Create the
system-specific work directories later in Section 2:

```text
mattergen-project/
├── code/                         # installed software
│   ├── vsbtools/                 # VSBTools checkout
│   ├── scout-matter/             # MatterGen checkout
│   ├── bootstrap-venv/           # optional installer environment
│   └── workflow-env/             # reusable runtime environments
└── work/                         # one directory per chemical system
```

`CODE_ROOT` holds the software. `WORK_ROOT` holds experiment inputs and results.
Repeat the exports in each new terminal.

### 1.3 Create a bootstrap environment

Choose standard Python `venv` or Conda. This environment only supplies the
installer's Python interpreter.

#### Option A: `python3 -m venv`

```bash
python3 -m venv "$CODE_ROOT/bootstrap-venv"
source "$CODE_ROOT/bootstrap-venv/bin/activate"
python -m pip install --upgrade pip

export PYTHON_FOR_SETUP="$CODE_ROOT/bootstrap-venv/bin/python"
```

#### Option B: Conda

Use this option if Conda or Miniconda is installed:

```bash
conda create -n mattergen-bootstrap python=3.12 pip git -y
conda activate mattergen-bootstrap

export PYTHON_FOR_SETUP="$CONDA_PREFIX/bin/python"
```

Confirm the prerequisites before continuing:

```bash
git --version
"$PYTHON_FOR_SETUP" --version
```

The reported Python version must be 3.11 or newer. You can also point
`PYTHON_FOR_SETUP` directly at any suitable system interpreter.

The installer creates `vsbtools`, `scout-matter`, and `grace` environments under
`$CODE_ROOT/workflow-env/venvs/`. Keep the bootstrap environment active while
running it.

### 1.4 Install VSBTools and MatterGen

Clone both repositories into the software tree, then run the reusable installer
located at the VSBTools repository root:

```bash
git clone https://github.com/link-lab3629/vsbtools.git "$CODE_ROOT/vsbtools"
git clone https://github.com/link-lab3629/scout-matter.git "$CODE_ROOT/scout-matter"

bash "$CODE_ROOT/vsbtools/install_vsbtools_mattergen.sh" \
  --vsbtools-source "$CODE_ROOT/vsbtools" \
  --mattergen-source "$CODE_ROOT/scout-matter" \
  --env-root "$CODE_ROOT/workflow-env" \
  --python "$PYTHON_FOR_SETUP" \
  --editable
```

The installer creates persistent VSBTools, MatterGen, and GRACE environments;
rerunning it updates them from the selected checkouts.

To install selected branches, add one or both ref options:

```bash
bash "$CODE_ROOT/vsbtools/install_vsbtools_mattergen.sh" \
  --vsbtools-source "$CODE_ROOT/vsbtools" \
  --mattergen-source "$CODE_ROOT/scout-matter" \
  --env-root "$CODE_ROOT/workflow-env" \
  --python "$PYTHON_FOR_SETUP" \
  --vsbtools-ref "linklab-installation-procedure" \
  --mattergen-ref MATTERGEN_BRANCH \
  --fetch \
  --editable
```

Each ref may be a branch, tag, or commit hash. Add `--fetch` to fetch `origin`
first and fast-forward an existing local branch when possible. Ref selection
requires clean checkouts. Resolved branches and commits are saved in
`installation_manifest.json`.

The installer also pins the MatterGen environment to the compatible
`emmet-core`/`pymatgen` pair `0.84.9`/`2024.10.29`. If an existing environment
reports `No module named pymatgen.core.graphs`, rerun the installer: it repairs
the package pair and imports `mattergen.scripts.generate` as part of its
validation.

### 1.5 Choose editable or regular installation

Use `--editable` for development or branch comparisons. Python imports live
files from the checkouts, so restart Python or Jupyter after changing branches
or source files. Rerun the installer when dependencies or installation metadata
change.

Use `--regular` for a fixed copy of a branch. Give each snapshot its own
environment root:

```bash
bash "$CODE_ROOT/vsbtools/install_vsbtools_mattergen.sh" \
  --vsbtools-source "$CODE_ROOT/vsbtools" \
  --mattergen-source "$CODE_ROOT/scout-matter" \
  --env-root "$CODE_ROOT/workflow-env-regular" \
  --python "$PYTHON_FOR_SETUP" \
  --regular
```

The regular installation copies package code into its environments. The
installer records the selected commits in `installation_manifest.json`. For the
packaged demonstration notebook, use the separate
`vsbtools/materials_dataset/Examples/setup_reproducibility_envs.sh`; it creates
its own contained environments and outputs.

### 1.6 Select an installed environment

Each installation root has its own `workflow_env.sh` and three runtime
environments. Select the desired root in a fresh shell (or deactivate the
current virtual environment).

For the editable installation:

```bash
source "$CODE_ROOT/workflow-env/workflow_env.sh"
source "$CODE_ROOT/workflow-env/venvs/scout-matter/bin/activate"
```

For the regular installation:

```bash
source "$CODE_ROOT/workflow-env-regular/workflow_env.sh"
source "$CODE_ROOT/workflow-env-regular/venvs/scout-matter/bin/activate"
```

Use one block per shell. `workflow_env.sh` selects the matching Python paths;
it does not install anything. Use the same root's `launch_jupyter.sh`,
`venvs/scout-matter/bin/mattergen-generate`, and `venvs/vsbtools/bin/python`.

### 1.7 Install and verify GRACE/tensorpotential

GRACE is provided through `tensorpotential`. The installer creates
`$CODE_ROOT/workflow-env/venvs/grace`. The commands below use the default
editable installation root; replace `$CODE_ROOT/workflow-env` with the selected
`--env-root` when it differs.

```bash
"$CODE_ROOT/workflow-env/venvs/grace/bin/python" -m pip install "ase<3.26" tensorpotential
```

Verify that the separate GRACE interpreter can load its calculator:

```bash
"$CODE_ROOT/workflow-env/venvs/grace/bin/python" -c \
  "import tensorpotential.calculator; print('GRACE/tensorpotential import OK')"
```

The first energy-estimation run may download the GRACE model, so keep internet
access available or provide a cached model.

To create GRACE environment manually instead:

```bash
"$PYTHON_FOR_SETUP" -m venv "$CODE_ROOT/workflow-env/venvs/grace"
export GRACE_PYTHON="$CODE_ROOT/workflow-env/venvs/grace/bin/python"

"$GRACE_PYTHON" -m pip install --upgrade pip
"$GRACE_PYTHON" -m pip install "ase<3.26" tensorpotential
"$GRACE_PYTHON" -c \
  "import tensorpotential.calculator; print('GRACE/tensorpotential import OK')"
```

Source the generated `workflow_env.sh` in another shell; it exports
`GRACE_PYTHON`.

The main executables are now:

```text
$CODE_ROOT/workflow-env/venvs/scout-matter/bin/mattergen-generate
$CODE_ROOT/workflow-env/venvs/vsbtools/bin/python
$CODE_ROOT/workflow-env/venvs/grace/bin/python
$CODE_ROOT/workflow-env/workflow_env.sh
$CODE_ROOT/workflow-env/launch_jupyter.sh
```

## 2. Organize the work

### 2.1 Create the system work tree

Create one work tree per chemical system. Keep its configurations, logs, raw
generations, and analysis results together:

```bash
export SYSTEM="Ni-Pd-H"
export SYSTEM_ROOT="$WORK_ROOT/$SYSTEM"
export RAW_ROOT="$SYSTEM_ROOT/raw-generations"
export CONFIG_ROOT="$SYSTEM_ROOT/configs"
export LOG_ROOT="$SYSTEM_ROOT/logs"
export ANALYSIS_ROOT="$SYSTEM_ROOT/analysis-run"
# Use the source checkouts that produced INSTALL_ROOT.
export VSBTOOLS_SOURCE="$CODE_ROOT/vsbtools"
export MATTERGEN_SOURCE="$CODE_ROOT/scout-matter"

mkdir -p "$RAW_ROOT/non_guided" "$RAW_ROOT/repeated-guided" \
  "$CONFIG_ROOT" "$LOG_ROOT" "$ANALYSIS_ROOT"

# Select one runtime from Section 1.6.
export INSTALL_ROOT="$CODE_ROOT/workflow-env"  # editable
# export INSTALL_ROOT="$CODE_ROOT/workflow-env-regular"  # regular snapshot
source "$INSTALL_ROOT/venvs/scout-matter/bin/activate"
```

Repeat this block with a new `SYSTEM` value for every chemical system.
Generation numbering restarts under each mode, so `non_guided/gen_1` and
`repeated-guided/gen_1` are separate settings.

Use `gen_N` for one homogeneous generation setting. Every structure below one
`gen_N` must have the same meaningful settings: chemical system, checkpoint,
guidance type and parameters, targets, guidance/loss weights, algorithm, and
the code version that affects generation. Execution details such as batch size,
number of batches or runs, GPU and memory allocation, output paths, and OOM
retry settings may vary. Create a new `gen_N` whenever a meaningful setting
changes, especially the guidance objective or target.

Every invocation uses the same repeat convention: `gen_N/run_N`. A single run
is `run_1`; `--runs N` creates `run_1` through `run_N`. The direct MatterGen
option `--num_batches` controls batches inside one `run_N` invocation. The new
workflow never creates `batch_N`; existing `batch_N` trees remain readable as
legacy input.

```text
work/
├── Ni-Pd-H/
│   ├── raw-generations/
│   │   ├── non_guided/
│   │   │   ├── gen_1/              # one non-guided setting
│   │   │   │   └── run_1/          # one invocation
│   │   │   └── gen_2/              # another non-guided setting
│   │   └── repeated-guided/
│   │       ├── gen_1/              # ranked-softplus setting
│   │       │   ├── run_1/           # structures, parameters, and provenance/
│   │       │   └── run_2/           # structures, parameters, and provenance/
│   │       └── gen_2/              # mean-coordination setting
│   │           ├── run_1/           # structures, parameters, and provenance/
│   │           └── run_2/           # structures, parameters, and provenance/
│   ├── configs/
│   ├── logs/
│   └── analysis-run/
└── Mg-B-H/
    ├── raw-generations/
    │   ├── non_guided/
    │   │   ├── gen_1/              # one non-guided setting
    │   │   │   └── run_1/          # one invocation
    │   │   └── gen_2/              # another non-guided setting
    │   │       └── run_1/          # one invocation
    │   └── repeated-guided/
    │       ├── gen_1/              # one homogeneous guided setting
    │       │   └── run_1/          # one invocation
    │       └── gen_2/              # another homogeneous guided setting
    │           └── run_1/          # one invocation
    ├── configs/
    ├── logs/
    └── analysis-run/
```

### 2.2 Generate raw structures

Choose the system directory, then use the repository-level generator. Section
2.3 describes the provenance record created automatically by each invocation.

#### 2.2.1 Non-guided generation

```bash
./generate_mattergen.sh "$SYSTEM_ROOT" --runs 1 --batch-size 20
```

This creates `raw-generations/non_guided/gen_1/run_1/`. The chemical system
defaults to the final component of `SYSTEM_ROOT`; pass `--chemical-system` when
the directory name and MatterGen condition differ.

#### 2.2.2 Guided generation

Guidance is optional. Supplying it selects `repeated-guided`; every invocation
still uses `run_N` below one homogeneous `gen_N`.

```bash
./generate_mattergen.sh "$SYSTEM_ROOT" --runs 2 --batch-size 20 \
  --guidance "{'ranked_coordination': {'margin':0.05, 'temperature':0.10, 'alpha':2.0, 'cn_tolerance':0.4, 'cn_temperature':0.05, 'satisfaction_weight':1.0, '[Pd,Ni]-H':6}}" \
  --self-rec-steps 3 --back-step 2 --algo 1
```

This creates `raw-generations/repeated-guided/gen_1/run_1/` and `run_2/` with
the same scientific settings. Use a new `gen_N` whenever the guidance type,
target, checkpoint, or another meaningful setting changes. Reduce
`--batch-size` when GPU memory is insufficient.

#### 2.2.3 Repeat controls

The repeat interface mirrors a `multiple_runs.sh` routine while allowing the
guidance option to be omitted. The key controls are:

- `--runs`: number of independent `run_N` directories; the default `1` creates
  exactly `run_1`.
- `--batch-size`: structures generated in each invocation.
- `--num-batches`: batches generated inside each invocation.
- `--dry-run`: print all resolved `run_N` commands without executing them.

`group_coordination` and `mean_coordination` are distinct registered
guidance types. The generator accepts either mapping through `--guidance`; omit
that option for an unguided run.

The generator follows the same independent-run model as `multiple_runs.sh`,
with guidance optional and output paths normalized to `gen_N/run_N`. Existing
outputs produced by older MatterGen or `multiple_runs.sh` layouts can still be
processed recursively.

### 2.3 Automatic MatterGen provenance

Every `mattergen-generate` invocation writes its provenance record into the
same output directory:

```text
<generation-output>/
├── generated_crystals.extxyz
├── input_parameters.txt
└── provenance/
    ├── generation.json
    ├── mattergen.patch             # present when tracked source files differ from HEAD
    └── mattergen.untracked.txt     # present when relevant source files are untracked
```

`generation.json` records the complete generation arguments, command line,
timestamp, MatterGen package and source location, Git commit and branch, Python
runtime, platform, active environment, and installed package versions. For a
regular installation outside a Git checkout, it records a SHA-256 digest of the
installed MatterGen package tree.

Every `run_N/` receives its own provenance record. This also captures the actual
batch size used after any out-of-memory retry when the external
`multiple_runs.sh` routine is used. Keep the `provenance/` directory beside the
generated structures when moving or archiving a generation.

### 2.4 Postprocess the selected generations

From the VSBTools repository root, launch the reusable notebook for this
system:

```bash
./launch_mattergen_analysis.sh "$SYSTEM_ROOT"
```

The launcher copies `mattergen_analysis.ipynb` into
`$SYSTEM_ROOT/analysis-run/`, selects the managed VSBTools/MatterGen/GRACE
environments, and opens Jupyter. Edit the inline `SCENARIO_YAML` and
`ANALYSIS_YAML` strings when you need different stages, descriptors, losses, or
plot settings. Then run the notebook cells in order. They discover every
homogeneous `gen_N` root, collect all nested `run_N` outputs, run the scenario,
build `table.txt` and Pareto-front files, and save figures below
`$SYSTEM_ROOT/analysis-run`.

Complete the selected generation outputs before the first processing run.
Scenario repositories resume committed stages. After adding or removing a
`run_N`, rerun discovery so the changed input tree receives a new
processed cache key.

#### 2.4.1 Expected outputs

After Section 4 finishes, check:

```text
$SYSTEM_ROOT/analysis-run/
├── processed/                    # scenario repositories and stage datasets
└── figures/                      # histogram/KDE and Pareto-front PDFs
```

The processed Pareto stage contains `table.txt`, front CSV files, and selected
POSCAR directories. Section 4.2 explains the choice between generated-only and
generated-plus-reference Pareto stages.

### 2.5 Archive the system

Keep every generation output together with its adjacent `provenance/`
directory. The system archive then contains its raw generations, configuration,
logs, processed datasets, figures, and provenance records.

Archive one system, including all its generations and provenance, with:

```bash
SYSTEM_ARCHIVE="${SYSTEM_ROOT%/}.tar.gz"
tar -czf "$SYSTEM_ARCHIVE" \
  -C "$(dirname "$SYSTEM_ROOT")" "$(basename "$SYSTEM_ROOT")"
```
