# MatterGen to VSBTools: generation and analysis

This guide has two parts:

1. install the software under `CODE_ROOT`;
2. organize `WORK_ROOT` by chemical system, then generate and postprocess.

The examples use `Ni-Pd-H` and target `CN([Pd,Ni]-H) = 6`. Replace the system,
species, target, GPU, and guidance settings as needed.

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

There are two ways to repeat one setting:

| Output               | How it is produced                               | Meaning                                                                |
| -------------------- | ------------------------------------------------ | ---------------------------------------------------------------------- |
| `batch_N/`           | Separate direct `mattergen-generate` invocations | One manually named repeat; keep the invocation settings identical.     |
| `results/.../run_N/` | `multiple_runs.sh --runs N`                      | One independent MatterGen invocation per run, with OOM retry handling. |

The direct MatterGen option `--num_batches` controls batches inside one
invocation and does not create a new generation setting. `batch_N` and `run_N`
are both repeat directories; they may coexist under one `gen_N` only when their
meaningful settings match.

```text
work/
├── Ni-Pd-H/
│   ├── raw-generations/
│   │   ├── non_guided/
│   │   │   ├── gen_1/              # one non-guided setting
│   │   │   │   ├── generated_crystals.extxyz
│   │   │   │   ├── input_parameters.txt
│   │   │   │   └── provenance/       # installation manifest and source state
│   │   │   └── gen_2/              # another non-guided setting; contains provenance/
│   │   └── repeated-guided/
│   │       ├── gen_1/              # ranked-softplus setting
│   │       │   ├── batch_1/
│   │       │   ├── batch_2/
│   │       │   └── provenance/       # installation manifest and source state
│   │       └── gen_2/              # mean-coordination setting
│   │           ├── results/.../run_1/
│   │           ├── results/.../run_2/
│   │           └── provenance/       # installation manifest and source state
│   ├── configs/
│   ├── logs/
│   └── analysis-run/
└── Mg-B-H/
    ├── raw-generations/
    │   ├── non_guided/
    │   │   ├── gen_1/              # one non-guided setting
    │   │   └── gen_2/              # another non-guided setting
    │   └── repeated-guided/
    │       ├── gen_1/              # one homogeneous guided setting
    │       └── gen_2/              # another homogeneous guided setting
    ├── configs/
    ├── logs/
    └── analysis-run/
```

### 2.2 Generate raw structures

Choose one or more generation patterns below. For each `gen_N`, run the
provenance step in Section 2.3 before its first generation command.

#### 2.2.1 Non-guided generation

```bash
GEN_ROOT="$RAW_ROOT/non_guided/gen_1"
mattergen-generate "$GEN_ROOT" \
  --pretrained-name=chemical_system \
  --batch_size=20 \
  --num_batches=1 \
  --properties_to_condition_on="{'chemical_system':'Ni-Pd-H'}" \
  --diffusion_guidance_factor=2.0 \
  --record_trajectories=False \
  --print_loss=False \
  --force_gpu=0
```

#### 2.2.2 Repeated direct outputs with ranked-softplus guidance

These two direct outputs share the same ranked-softplus settings and therefore
belong to one homogeneous generation group, `repeated-guided/gen_1`. Use a new `gen_N`
for a different guidance objective, target, or other meaningful setting.

```bash
GEN_ROOT="$RAW_ROOT/repeated-guided/gen_1"
```

`ranked_coordination` applies the ranked-neighbor softplus objective. The
grouped center `[Pd,Ni]` is one coordination constraint. The loop changes only
the output directory, creating `batch_1` and `batch_2` with the same settings.

```bash
for BATCH in 1 2; do
  mattergen-generate "$GEN_ROOT/batch_$BATCH" \
    --pretrained-name=chemical_system \
    --batch_size=20 \
    --num_batches=1 \
    --properties_to_condition_on="{'chemical_system':'Ni-Pd-H'}" \
    --diffusion_guidance_factor=2.0 \
    --guidance="{'ranked_coordination': {'margin':0.05, 'temperature':0.10, 'alpha':2.0, 'cn_tolerance':0.4, 'cn_temperature':0.05, 'satisfaction_weight':1.0, '[Pd,Ni]-H':6}}" \
    --diffusion_loss_weight="[0.01,0.01,True]" \
    --self_rec_steps=3 \
    --back_step=2 \
    --algo=1 \
    --record_trajectories=False \
    --print_loss=False \
    --force_gpu=0
done
```

Every direct output must retain `generated_crystals.extxyz` and
`input_parameters.txt`. Treat these weights as starting values and calibrate
the objectives independently. Reduce `--batch_size` if GPU memory is
insufficient.

#### 2.2.3 Repeat one setting with `multiple_runs.sh`

Use scout-matter's root-level `multiple_runs.sh` for independent repeats of one
guided setting. It invokes `mattergen-generate` per run, retries CUDA
out-of-memory failures with a smaller batch, and records durations. Each run
keeps its own output under `run_N/`.

Activate the selected MatterGen environment and enter the source repository;
`multiple_runs.sh` is at its root:

```bash
source "$INSTALL_ROOT/venvs/scout-matter/bin/activate"
cd "$CODE_ROOT/scout-matter"

./multiple_runs.sh --help
```

This is a separate setting from the ranked-softplus generation group above, so
it uses `repeated-guided/gen_2`. All fifty runs share the same
group-coordination guidance settings; `run_N` only identifies the
independent repeat.

```bash
GEN_ROOT="$RAW_ROOT/repeated-guided/gen_2"
./multiple_runs.sh \
  --batch-size 20 \
  --num-batches 1 \
  --runs 50 \
  --system Ni-Pd-H \
  --guidance "{'group_coordination': {'mode':'huber', 'alpha':3.0, '[Pd,Ni]-H':6}}" \
  --forward-weight 0.01 \
  --backward-weight 0.01 \
  --normalize true \
  --self-rec-steps 3 \
  --back-step 2 \
  --algorithm 1 \
  --diffusion-guidance-factor 2.0 \
  --gpu 0 \
  --base-dir "$GEN_ROOT" \
  --log-file "$LOG_ROOT/group-coordination.log"
```

Add `--dry-run` to inspect the generated commands before starting. The size
controls are:

- `--batch-size`: structures generated in each batch.
- `--num-batches`: batches generated within each independent run.
- `--runs`: number of independent runs.

`group_coordination` and `mean_coordination` are distinct registered
guidance types. This example uses `group_coordination` because one target is
defined for the pooled central-species group `[Pd,Ni]`. The same `gen_2`
setting can instead be stored in a YAML configuration file. Use either the
direct CLI invocation above or the config-file invocation below. Use a new
`gen_N` if the guidance type, its parameters, or another meaningful
setting changes.

```yaml
batch_size: 20
num_batches: 1
runs: 50
system: Ni-Pd-H

guidance:
  type: group_coordination
  parameters:
    mode: huber
    alpha: 3.0
    "[Pd,Ni]-H": 6
  settings:
    forward_weight: 0.01
    backward_weight: 0.01
    normalize: true
    self_rec_steps: 3
    back_step: 2
    algorithm: 1

diffusion_guidance_factor: 2.0
gpu: 0

oom_retries: 30
oom_backoff_percent: 80
min_batch_size: 1
oom_wait_seconds: 10

# These paths lead from code/scout-matter into the Ni-Pd-H work tree.
base_dir: ../../work/Ni-Pd-H/raw-generations/repeated-guided/gen_2
log_file: ../../work/Ni-Pd-H/logs/group-coordination-yaml.log
dry_run: false
```

Save the YAML as `$CONFIG_ROOT/group-coordination.yaml`, then run it as the only
command-line option:

```bash
./multiple_runs.sh --config "$CONFIG_ROOT/group-coordination.yaml"
```

Match the homogeneous generation directory to the YAML `base_dir`. If the
preceding direct CLI invocation was used, do not also launch the config-file
invocation: both forms describe the same `gen_2` setting.

On out-of-memory, the script retries with
`ceil(current_batch_size * oom_backoff_percent / 100)`. It stops after
`oom_retries` or at `min_batch_size`; compare ensembles using `final_batch_size`.

Results are nested under `gen_2/results` (or the selected `gen_N`), with paths
derived from the system, guidance parameters, and settings:

```text
$RAW_ROOT/repeated-guided/gen_2/results/Ni-Pd-H/<guidance>/<parameters>/<settings>/
├── durations.csv                # duration, final batch size, and attempts
├── run_1/
│   ├── generated_crystals.extxyz
│   ├── input_parameters.txt
│   └── attempt_1.log
├── run_2/
│   └── ...
└── run_50/
    └── ...
```

For a `multiple_runs.sh` generation, process each `run_N/` directory once. The
script does not create a parent `generated_crystals.extxyz`, so every generated
structure appears only in its corresponding run output.

### 2.3 Automatic MatterGen provenance

No separate provenance command is required. Every `mattergen-generate`
invocation writes its record automatically into the same output directory:

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

With `multiple_runs.sh`, every `run_N/` receives its own provenance record. This
also captures the actual batch size used after any out-of-memory retry. Keep the
`provenance/` directory beside the generated structures when moving or
archiving a generation.

### 2.4 Postprocess the selected generations

Copy the scenario and notebook into this system's work tree, then launch
Jupyter from the selected analysis environment:

```bash
if [[ ! -f "$CONFIG_ROOT/scenario_no_relax.yaml" ]]; then
  cp "$CODE_ROOT/vsbtools/vsbtools/materials_dataset/Examples/scenario_no_relax.yaml" \
    "$CONFIG_ROOT/scenario_no_relax.yaml"
fi

ANALYSIS_INSTALL_ROOT="$INSTALL_ROOT"
mkdir -p "$ANALYSIS_ROOT"
if [[ ! -f "$ANALYSIS_ROOT/mg_generation_postprocessing_pipeline.ipynb" ]]; then
  cp "$CODE_ROOT/vsbtools/vsbtools/materials_dataset/Examples/mg_generation_postprocessing_pipeline.ipynb" \
    "$ANALYSIS_ROOT/mg_generation_postprocessing_pipeline.ipynb"
fi
cd "$ANALYSIS_ROOT"
"$ANALYSIS_INSTALL_ROOT/launch_jupyter.sh"
```

Open `mg_generation_postprocessing_pipeline.ipynb`, run Sections 0 and 1, then
run the cells below. `ANALYSIS_INSTALL_ROOT` must match `INSTALL_ROOT`.

#### 2.4.1 Run the scenario pipeline

```python
import os
from pathlib import Path

from vsbtools.materials_dataset.analysis.scenario_pipeline import process_generation_dir

SYSTEM_ROOT = Path(os.environ["SYSTEM_ROOT"])
RAW_ROOT = SYSTEM_ROOT / "raw-generations"
PROCESSED_ROOT = SYSTEM_ROOT / "analysis-run" / "processed"
FIGURE_ROOT = SYSTEM_ROOT / "analysis-run" / "figures"
SCENARIO = SYSTEM_ROOT / "configs" / "scenario_no_relax.yaml"

PROCESSED_ROOT.mkdir(parents=True, exist_ok=True)
FIGURE_ROOT.mkdir(parents=True, exist_ok=True)

generation_dirs = [
    path
    for path in (RAW_ROOT / "non_guided").glob("gen_*")
    if path.is_dir()
]
for generation_root in sorted((RAW_ROOT / "repeated-guided").glob("gen_*")):
    generation_dirs.extend(
        path for path in generation_root.glob("batch_*") if path.is_dir()
    )
    generation_dirs.extend(
        path.parent
        for path in generation_root.glob("results/**/run_*/input_parameters.txt")
    )
generation_dirs = sorted(set(generation_dirs))
if not generation_dirs:
    raise RuntimeError(f"No generation directories found under {RAW_ROOT}")

repos = []
for generation_dir in generation_dirs:
    repo = process_generation_dir(
        generation_dir,
        PROCESSED_ROOT,
        SCENARIO,
        batch_metadata_file="input_parameters.txt",
    )
    if repo is None:
        raise RuntimeError(f"Missing input_parameters.txt under {generation_dir}")
    repos.append(repo.root)

system_repo = repos[0].parent
print(*repos, sep="\n")
```

The scenario parses structures, filters minimum distances, symmetrizes, estimates
GRACE energies, collects OPTIMADE references, deduplicates, and merges
references. The distance filter precedes spglib symmetrization. Reruns resume
from saved stages; use a fresh processed directory after changing dependencies.

#### 2.4.2 Build summary tables and Pareto-front files

Pass explicit reporting callables for ranked and grouped guidance. Use the same
loss dictionaries as in generation.

```python
from pymatgen.core import Element

from vsbtools.materials_dataset.analysis.guidance_statistics import (
    get_loss_fn,
    get_target_value_fn,
)
from vsbtools.materials_dataset.scripts.build_tables import (
    build_guidance_summary_for_processed_system,
)

center_species = [Element("Pd").Z, Element("Ni").Z]
neighbor_species = Element("H").Z

ranked_target = {
    "margin": 0.05,
    "temperature": 0.10,
    "alpha": 2.0,
    "cn_tolerance": 0.4,
    "cn_temperature": 0.05,
    "satisfaction_weight": 1.0,
    "[Pd,Ni]-H": 6,
}
group_target = {
    "mode": "huber",
    "alpha": 3.0,
    "[Pd,Ni]-H": 6,
}

descriptor_fn = get_target_value_fn(
    "compute_mean_coordination",
    force_gpu=0,
    type_A=center_species,
    type_B=neighbor_species,
    alpha=3.0,
)
report_callables = {
    "CN_[Pd,Ni]-H": descriptor_fn,
    "loss_ranked_coordination": get_loss_fn(
        "ranked_coordination", force_gpu=0, target=ranked_target
    ),
    "loss_mean_group_coordination": get_loss_fn(
        "mean_coordination", force_gpu=0, target=group_target
    ),
}

PARETO_STAGE = "add_ref_deduplicated"
summary_report = build_guidance_summary_for_processed_system(
    system_repo,
    target_stages=[PARETO_STAGE],
    auto_ref_stages=True,
    callables=report_callables,
    max_pareto_front=3,
    return_report=True,
)
print(summary_report)
```

Use `PARETO_STAGE = "deduplicate_all"` for generated structures only;
`add_ref_deduplicated` also includes reference structures.

#### 2.4.3 Choose the histogram/KDE callable

Choose one callable regime below, then run the common plotting cell.

#### Regime A: reconstruct callables from guided batch metadata

`callables_from_ds(parse_raw_dataset)` reads `batch_metadata["guidance"]` and
recreates the descriptor, target, and matching loss. It supports guided runs
with simple metadata, such as `mean_coordination` with `Co-O`,
`target_coordination_share`, or `volume_pa`.

```python
from vsbtools.materials_dataset.analysis.guidance_statistics import callables_from_ds
from vsbtools.materials_dataset.scripts.build_tables import stage_datasets_from_repo

guided_parse_ds = None
for repo in repos:
    parse_ds = stage_datasets_from_repo(repo)["parse_raw"]
    guidance = parse_ds.metadata["batch_metadata"].get("guidance")
    if isinstance(guidance, dict) and guidance:
        guided_parse_ds = parse_ds
        break

if guided_parse_ds is None:
    raise RuntimeError("No guided batch metadata was found.")

automatic_callables, automatic_targets, guidance_name = callables_from_ds(
    guided_parse_ds,
    force_gpu=0,
)
descriptor_names = [
    name for name in automatic_callables
    if not name.startswith("loss_")
]
if len(descriptor_names) != 1:
    raise RuntimeError(f"Choose one descriptor from {descriptor_names!r}.")

descriptor_name = descriptor_names[0]
descriptor_fn = automatic_callables[descriptor_name]
descriptor_target = automatic_targets[descriptor_name]
descriptor_label = descriptor_name
print("Guidance:", guidance_name, "Descriptor:", descriptor_name)
```

Use the manual regime for the ranked-softplus and grouped-key examples here;
the metadata helper cannot infer ranked-softplus descriptors or grouped keys
such as `[Pd,Ni]-H`.

#### Regime B: construct callables manually

Use manual construction for an unguided batch (`guidance: None`) and for testing
alternative descriptors, cutoffs, targets, or losses on the same structures.

```python
from pymatgen.core import Element

from vsbtools.materials_dataset.analysis.guidance_statistics import (
    get_target_value_fn,
)

descriptor_fn = get_target_value_fn(
    "compute_mean_coordination",
    force_gpu=0,
    type_A=[Element("Pd").Z, Element("Ni").Z],
    type_B=Element("H").Z,
    alpha=3.0,
)
descriptor_target = 6
descriptor_label = "mean CN([Pd,Ni]-H)"
```

Use the `get_loss_fn(name, target=...)` pattern from Section 2.4.2 to recompute a
loss for Pareto analysis.

#### 2.4.4 Plot a histogram or KDE

Run this after either regime. Set `PLOT_KIND` to `"histogram"` or `"kde"`.

```python
import matplotlib.pyplot as plt

from vsbtools.materials_dataset.analysis.guidance_statistics import (
    calculate_values,
    collect_stage_dataset_dict,
    histo_data_collection,
    plot_multi_kde,
    plot_multihistogram,
)

datasets = collect_stage_dataset_dict(
    repos,
    stage="symmetrize_raw",
    ref_stage="poll_db",
)
PLOT_KIND = "kde"

if PLOT_KIND == "kde":
    values = calculate_values(datasets, fn=descriptor_fn, filter_max_el=False)
    fig, ax = plot_multi_kde(
        values,
        target=descriptor_target,
        max_value=10,
        simplified_legend=True,
    )
else:
    histogram_data = histo_data_collection(
        datasets,
        fn=descriptor_fn,
        filter_max_el=False,
        auto_adjust_bins=True,
        n_bins=20,
    )
    fig, ax = plot_multihistogram(
        histogram_data,
        target=descriptor_target,
        max_bincenter=10,
        show_gaussian=True,
        simplified_legend=True,
    )

ax.set_xlabel(descriptor_label)
fig.savefig(
    FIGURE_ROOT / f"Ni-Pd-H_coordination_{PLOT_KIND}.pdf",
    bbox_inches="tight",
    pad_inches=0.1,
)
plt.close(fig)
```

#### 2.4.5 Plot the Pareto fronts

The summary step already creates front CSVs, tables, and POSCAR directories.
This cell creates PDF figures for both losses.

```python
import matplotlib.pyplot as plt

from vsbtools.materials_dataset.analysis.pareto_fronts import plot_pareto
from vsbtools.materials_dataset.scripts.build_tables import stage_datasets_from_repo

losses = {
    "loss_ranked_coordination": "ranked_coordination_",
    "loss_mean_group_coordination": "mean_group_coordination_",
}

for repo_no, repo in enumerate(repos, start=1):
    stage_dir = Path(stage_datasets_from_repo(repo)[PARETO_STAGE].base_path)
    for loss_column, prefix in losses.items():
        if not (stage_dir / f"{prefix}pf_1.csv").exists():
            continue
        ax = plot_pareto(
            stage_dir,
            col1=loss_column,
            col2="e_hull/at",
            trim_col1=None,
            trim_col2=0.3,
            n_fronts=3,
            prefix=prefix,
            article_axes=True,
            show_title=False,
        )
        ax.figure.savefig(
            FIGURE_ROOT / f"repo_{repo_no}_{prefix}pareto.pdf",
            bbox_inches="tight",
            pad_inches=0.1,
        )
        plt.close(ax.figure)
```

### 2.5 Archive the system

Keep each `gen_N` directory with its own `provenance/` directory. The system
archive then contains its raw generations, configuration, logs, processed
datasets, figures, and provenance records.

Archive one system, including all its generations and provenance, with:

```bash
SYSTEM_ARCHIVE="${SYSTEM_ROOT%/}.tar.gz"
tar -czf "$SYSTEM_ARCHIVE" \
  -C "$(dirname "$SYSTEM_ROOT")" "$(basename "$SYSTEM_ROOT")"
```
