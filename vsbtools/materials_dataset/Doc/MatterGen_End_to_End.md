# MatterGen to VSBTools: generation and analysis

This guide has two parts:

1. install the software under `CODE_ROOT`;
2. create one work tree per chemical system under `WORK_ROOT`, generate batches,
   and postprocess them.

The examples use `Ni-Pd-H` and target `CN([Pd,Ni]-H) = 6`. Replace the system,
species, target, GPU, and guidance settings as needed.

## 1. Install the code

### 1.1 Prepare Linux or macOS

Run all commands in a terminal. The installer accepts Python 3.11 or newer.
Internet access is needed for GitHub repositories, Python packages, MatterGen
checkpoints, GRACE, and OPTIMADE data.

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

If the Xcode command reports that the command-line tools are already installed,
continue with the next step. Conda users can skip the Homebrew Python install;
the Conda environment below supplies a suitable Python and Git.

### 1.2 Set up the code root

Choose a parent directory and define the project and code roots:

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

`CODE_ROOT` contains reinstallable software. `WORK_ROOT` contains experiment
inputs and results. In a new terminal, repeat the three exports above.

### 1.3 Create a bootstrap environment

Choose either standard Python `venv` or Conda. This bootstrap environment only
provides the Python interpreter used by the installer.

#### Option A: `python3 -m venv`

```bash
python3 -m venv "$CODE_ROOT/bootstrap-venv"
source "$CODE_ROOT/bootstrap-venv/bin/activate"
python -m pip install --upgrade pip

export PYTHON_FOR_SETUP="$CODE_ROOT/bootstrap-venv/bin/python"
```

#### Option B: Conda

Use this option when Conda or Miniconda is already installed:

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

The reported Python version must be 3.11 or newer. A system Python 3.12 can be
passed directly to the installer through `PYTHON_FOR_SETUP`.

The next installer creates three independent environments under
`$CODE_ROOT/workflow-env/venvs/`: `vsbtools`, `scout-matter`, and `grace`. Keep
the bootstrap environment active only while running the installer.

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

The installer creates persistent VSBTools, MatterGen, and GRACE environments.
Running it again updates them from the selected source checkouts.

To install selected branches, add one or both ref options:

```bash
bash "$CODE_ROOT/vsbtools/install_vsbtools_mattergen.sh" \
  --vsbtools-source "$CODE_ROOT/vsbtools" \
  --mattergen-source "$CODE_ROOT/scout-matter" \
  --env-root "$CODE_ROOT/workflow-env" \
  --python "$PYTHON_FOR_SETUP" \
  --vsbtools-ref VSBTOOLS_BRANCH \
  --mattergen-ref MATTERGEN_BRANCH \
  --fetch \
  --editable
```

The ref values may be branch names, tags, or commit hashes. `--fetch` is
optional; include it to fetch `origin` first and fast-forward an existing local
branch when possible. Ref selection requires a clean checkout and stops before
changing branches when tracked, staged, or untracked files are present. The
resolved branches and commits are saved in `installation_manifest.json`.

### 1.5 Choose editable or regular installation

Use `--editable` while developing or comparing source branches in a reusable
checkout. Python imports the live files from the Git checkouts; restart Python
or Jupyter after changing branches or source files. Re-run the installer when
dependencies or installation metadata change.

Use `--regular` for a fixed copy of a branch. Give each independent snapshot a
separate environment root:

```bash
bash "$CODE_ROOT/vsbtools/install_vsbtools_mattergen.sh" \
  --vsbtools-source "$CODE_ROOT/vsbtools" \
  --mattergen-source "$CODE_ROOT/scout-matter" \
  --env-root "$CODE_ROOT/workflow-env-regular" \
  --python "$PYTHON_FOR_SETUP" \
  --regular
```

The regular installation copies package code into its environments, so later
checkout edits do not affect it. The installer records the selected commits in
`installation_manifest.json`. For the packaged demonstration notebook, use the
separate `vsbtools/materials_dataset/Examples/setup_reproducibility_envs.sh`;
it creates its own contained environments and outputs.

### 1.6 Select an installed environment

Each installation root has its own `workflow_env.sh`, VSBTools environment,
MatterGen environment, and GRACE environment. Select one installation in a
fresh shell (or deactivate the current virtual environment).

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

Use one block per shell. The generated `workflow_env.sh` selects the Python
paths for VSBTools, MatterGen, and GRACE; it does not perform an installation.
Launch Jupyter with the matching `launch_jupyter.sh`; use the matching
`venvs/scout-matter/bin/mattergen-generate` for generation and
`venvs/vsbtools/bin/python` for analysis.

### 1.7 Install and verify GRACE/tensorpotential

GRACE is provided through the `tensorpotential` package. The reusable installer
creates `$CODE_ROOT/workflow-env/venvs/grace` and runs the equivalent of:

```bash
"$CODE_ROOT/workflow-env/venvs/grace/bin/python" -m pip install "ase<3.26" tensorpotential
```

Verify that the separate GRACE interpreter can load its calculator:

```bash
"$CODE_ROOT/workflow-env/venvs/grace/bin/python" -c \
  "import tensorpotential.calculator; print('GRACE/tensorpotential import OK')"
```

The first energy-estimation run may download the selected GRACE model. Keep
internet access available or provide an already cached model.

If the bundled setup script is not used, create the GRACE environment manually:

```bash
"$PYTHON_FOR_SETUP" -m venv "$CODE_ROOT/workflow-env/venvs/grace"
export GRACE_PYTHON="$CODE_ROOT/workflow-env/venvs/grace/bin/python"

"$GRACE_PYTHON" -m pip install --upgrade pip
"$GRACE_PYTHON" -m pip install "ase<3.26" tensorpotential
"$GRACE_PYTHON" -c \
  "import tensorpotential.calculator; print('GRACE/tensorpotential import OK')"
```

The generated `workflow_env.sh` exports `GRACE_PYTHON`. Source that file when
configuring another shell manually.

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

Create one work tree per chemical system. Keep configurations, logs, raw
generations, and analysis results inside that system's directory:

```bash
export SYSTEM="Ni-Pd-H"
export SYSTEM_ROOT="$WORK_ROOT/$SYSTEM"
export RAW_ROOT="$SYSTEM_ROOT/raw-generations"
export CONFIG_ROOT="$SYSTEM_ROOT/configs"
export LOG_ROOT="$SYSTEM_ROOT/logs"
export ANALYSIS_ROOT="$SYSTEM_ROOT/analysis-run"
export VSBTOOLS_SOURCE="$CODE_ROOT/vsbtools"
export MATTERGEN_SOURCE="$CODE_ROOT/scout-matter"

mkdir -p "$RAW_ROOT/non_guided" "$RAW_ROOT/repeated-guided" \
  "$CONFIG_ROOT" "$LOG_ROOT" "$ANALYSIS_ROOT"

# Select the installation for this system; use workflow-env-regular (or another
# installed root) when this system should use a regular snapshot.
export INSTALL_ROOT="$CODE_ROOT/workflow-env"
source "$INSTALL_ROOT/venvs/scout-matter/bin/activate"
```

Use `gen_N` for one generation campaign. A campaign that contains separate
outputs can use `batch_N` below it. A `multiple_runs.sh` campaign keeps the
script's own `run_N` directories inside its `gen_N` directory.

```text
work/
├── Ni-Pd-H/
│   ├── raw-generations/
│   │   ├── non_guided/
│   │   │   ├── gen_1/
│   │   │   │   ├── generated_crystals.extxyz
│   │   │   │   ├── input_parameters.txt
│   │   │   │   └── provenance/       # installation manifest and source state
│   │   │   └── gen_2/
│   │   └── repeated-guided/
│   │       ├── gen_1/
│   │       │   ├── batch_1/
│   │       │   ├── batch_2/
│   │       │   └── provenance/       # installation manifest and source state
│   │       └── gen_2/
│   │           ├── results/.../run_1/
│   │           ├── results/.../run_2/
│   │           └── provenance/       # installation manifest and source state
│   ├── configs/
│   ├── logs/
│   └── analysis-run/
└── Mg-B-H/
    ├── raw-generations/
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

#### 2.2.2 Guided batches

The following two batches form `repeated-guided/gen_1`. They use the same code
installation and differ only in the guidance objective. Put a new campaign in
`gen_2`, with its own provenance directory, when its code or settings differ.

```bash
GEN_ROOT="$RAW_ROOT/repeated-guided/gen_1"
```

`ranked_coordination` applies the ranked-neighbor softplus objective. The
grouped center `[Pd,Ni]` is one coordination constraint.

```bash
mattergen-generate "$GEN_ROOT/batch_1" \
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
```

The mean group-coordination batch uses the current `mean_coordination` objective.
`group_coordination` remains a compatibility alias.

```bash
mattergen-generate "$GEN_ROOT/batch_2" \
  --pretrained-name=chemical_system \
  --batch_size=20 \
  --num_batches=1 \
  --properties_to_condition_on="{'chemical_system':'Ni-Pd-H'}" \
  --diffusion_guidance_factor=2.0 \
  --guidance="{'mean_coordination': {'mode':'huber', 'alpha':3.0, '[Pd,Ni]-H':6}}" \
  --diffusion_loss_weight="[0.01,0.01,True]" \
  --self_rec_steps=3 \
  --back_step=2 \
  --algo=1 \
  --record_trajectories=False \
  --print_loss=False \
  --force_gpu=0
```

Each output directory must retain both files:

```text
generated_crystals.extxyz
input_parameters.txt
```

The weights above are starting values. Ranked-softplus has a different loss
scale from sigmoid mean coordination and should be calibrated independently.
If a batch runs out of GPU memory, reduce `--batch_size`.

#### 2.2.3 Repeated guided campaigns

Use scout-matter's root-level `multiple_runs.sh` for many independent guided
runs. It invokes `mattergen-generate` once per run, retries CUDA out-of-memory
failures with a smaller batch, records run durations, and combines the
successful structures into one aggregate `.extxyz` file.

The helper uses the selected MatterGen environment. Enter the source repository
because `multiple_runs.sh` lives at its root:

```bash
source "$INSTALL_ROOT/venvs/scout-matter/bin/activate"
cd "$CODE_ROOT/scout-matter"

./multiple_runs.sh --help
```

The following command stores one repeated-guided campaign in `gen_2` and
repeats the mean group-coordination generation fifty times:

```bash
GEN_ROOT="$RAW_ROOT/repeated-guided/gen_2"
./multiple_runs.sh \
  --batch-size 20 \
  --num-batches 1 \
  --runs 50 \
  --system Ni-Pd-H \
  --guidance "{'mean_coordination': {'mode':'huber', 'alpha':3.0, '[Pd,Ni]-H':6}}" \
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

Append `--dry-run` first to inspect every generated `mattergen-generate`
command without starting generation. The important size controls are:

- `--batch-size`: structures generated in each batch.
- `--num-batches`: batches generated within each independent run.
- `--runs`: number of independent runs.

For ranked-neighbor softplus guidance, either change `--guidance` in the command
above or use a YAML config. Create
`$CONFIG_ROOT/repeated-ranked-softplus.yaml` with:

```yaml
batch_size: 20
num_batches: 1
runs: 50
system: Ni-Pd-H

guidance:
  type: ranked_coordination
  parameters:
    margin: 0.05
    temperature: 0.10
    alpha: 2.0
    cn_tolerance: 0.4
    cn_temperature: 0.05
    satisfaction_weight: 1.0
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
base_dir: ../../work/Ni-Pd-H/raw-generations/repeated-guided/gen_3
log_file: ../../work/Ni-Pd-H/logs/ranked-softplus.log
dry_run: false
```

Run the YAML configuration as the only command-line option:

```bash
GEN_ROOT="$RAW_ROOT/repeated-guided/gen_3"
./multiple_runs.sh --config "$CONFIG_ROOT/repeated-ranked-softplus.yaml"
```

Use a new `gen_N` for every independent campaign; the campaign directory must
match the YAML `base_dir`.

On an out-of-memory failure, the script retries the same run with
`ceil(current_batch_size * oom_backoff_percent / 100)`. It stops after
`oom_retries`, or when another reduction would cross `min_batch_size`. Therefore,
record the `final_batch_size` column when comparing ensembles whose retries may
have produced different numbers of structures.

Results are nested under `gen_2/results` (or the selected `gen_N`) with paths
derived from the system, guidance parameters, and settings:

```text
$RAW_ROOT/repeated-guided/gen_2/results/Ni-Pd-H/<guidance>/<parameters>/<settings>/
├── generated_crystals.extxyz    # aggregate of every successful run
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

For a `multiple_runs.sh` campaign, process each `run_N/` directory once. The
parent settings directory contains an aggregate `generated_crystals.extxyz`;
do not process it as an additional batch.

### 2.3 Record provenance for each generation

The generation examples above describe what to run. Save the selected
installation and source state under each campaign's `gen_N` directory. For two
batches from the same campaign, save one record in the campaign directory;
`multiple_runs.sh` also gets one record for its campaign, with its `run_N`
directories below it.

Define this helper once:

```bash
record_generation_provenance() {
  local generation_root="$1"
  local install_root="$2"
  local vsbtools_source="$3"
  local mattergen_source="$4"
  local provenance_root="$generation_root/provenance"
  local repo_name
  local repo_root

  mkdir -p "$provenance_root"
  cp "$install_root/installation_manifest.json" \
    "$provenance_root/installation_manifest.json"
  cp "$install_root/workflow_env.sh" \
    "$provenance_root/workflow_env.sh"

  for repo_name in vsbtools scout-matter; do
    if [[ "$repo_name" == vsbtools ]]; then
      repo_root="$vsbtools_source"
    else
      repo_root="$mattergen_source"
    fi
    git -C "$repo_root" rev-parse HEAD \
      > "$provenance_root/${repo_name}.commit"
    git -C "$repo_root" status --short --branch \
      > "$provenance_root/${repo_name}.status"
    git -C "$repo_root" diff --binary HEAD \
      > "$provenance_root/${repo_name}.patch"
    git -C "$repo_root" ls-files --others --exclude-standard \
      > "$provenance_root/${repo_name}.untracked"
  done
}
```

After selecting the environment and branches, run the helper immediately before
the first matching generation command in Section 2.2:

```bash
# Non-guided generation
GEN_ROOT="$RAW_ROOT/non_guided/gen_1"
record_generation_provenance \
  "$GEN_ROOT" \
  "$INSTALL_ROOT" \
  "$VSBTOOLS_SOURCE" \
  "$MATTERGEN_SOURCE"

# The two direct guided batches in repeated-guided/gen_1
GEN_ROOT="$RAW_ROOT/repeated-guided/gen_1"
record_generation_provenance \
  "$GEN_ROOT" \
  "$INSTALL_ROOT" \
  "$VSBTOOLS_SOURCE" \
  "$MATTERGEN_SOURCE"

# The multiple_runs.sh campaign in repeated-guided/gen_2
GEN_ROOT="$RAW_ROOT/repeated-guided/gen_2"
record_generation_provenance \
  "$GEN_ROOT" \
  "$INSTALL_ROOT" \
  "$VSBTOOLS_SOURCE" \
  "$MATTERGEN_SOURCE"
```

For the YAML campaign, use the `gen_N` directory specified by `base_dir`:

```bash
GEN_ROOT="$RAW_ROOT/repeated-guided/gen_3"
record_generation_provenance \
  "$GEN_ROOT" \
  "$INSTALL_ROOT" \
  "$VSBTOOLS_SOURCE" \
  "$MATTERGEN_SOURCE"
```

`installation_manifest.json` identifies the selected environment. The commit,
status, patch, and untracked-file records identify the exact source checkouts
used for that generation, including local tracked edits in an editable
installation. Use another checkout and environment root for a generation that
runs concurrently with a different branch.

### 2.4 Postprocess the selected generations

Copy the scenario into this system's work tree and launch Jupyter from the
analysis environment:

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
run the cells below. Set `ANALYSIS_INSTALL_ROOT` to the selected installation.

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
    RAW_ROOT / "non_guided" / "gen_1",
    RAW_ROOT / "repeated-guided" / "gen_1" / "batch_1",
    RAW_ROOT / "repeated-guided" / "gen_1" / "batch_2",
]

for campaign_root in sorted((RAW_ROOT / "repeated-guided").glob("gen_*")):
    generation_dirs.extend(
        path.parent
        for path in campaign_root.glob("results/**/run_*/input_parameters.txt")
    )

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

The scenario performs structure parsing, minimum-distance filtering, then
symmetrization, followed by GRACE energy estimation, OPTIMADE reference
collection, structural deduplication, and reference merging. Filtering first
keeps pathological short-distance structures away from the spglib symmetry
search. Rerunning it resumes from saved stages; use a fresh processed-output
directory after changing stage dependencies.

#### 2.4.2 Build summary tables and Pareto-front files

Ranked and grouped guidance require explicit reporting callables. Keep the loss
dictionaries identical to those used for generation.

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

Use `PARETO_STAGE = "deduplicate_all"` when the fronts should contain generated
structures only. `add_ref_deduplicated` also includes reference structures.

#### 2.4.3 Choose the histogram/KDE callable

There are two callable regimes. Run one of the following cells, then run the
common plotting cell below it.

#### Regime A: reconstruct callables from guided batch metadata

`callables_from_ds(parse_raw_dataset)` reads `batch_metadata["guidance"]` and
recreates the descriptor callable, its target, and the matching loss callable.
This is convenient for guided runs whose metadata uses a supported simple pair
descriptor, such as `mean_coordination` with `Co-O`,
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

For the ranked-softplus and grouped-key commands in this document, use the
manual regime: the current metadata helper does not infer ranked-softplus
descriptors or parse grouped keys such as `[Pd,Ni]-H`.

#### Regime B: construct callables manually

Manual construction is required for an unguided batch because its metadata has
`guidance: None`. It is also useful for testing alternative descriptors,
cutoffs, targets, and losses on the same structures.

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

Use the same `get_loss_fn(name, target=...)` pattern shown in Section 2.4.2 when
you need to recompute a loss for Pareto analysis.

#### 2.4.4 Plot a histogram or KDE

Run this after either callable regime. Set `PLOT_KIND` to `"histogram"` or
`"kde"`.

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

`build_guidance_summary_for_processed_system` has already created the front
CSVs, text tables, and front-specific POSCAR directories. This cell creates PDF
figures for both losses.

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

### 2.5 Expected directory layout

```text
$PROJECT_ROOT/
├── code/                              # installed software; CODE_ROOT
│   ├── vsbtools/                      # VSBTools checkout
│   ├── scout-matter/                  # MatterGen checkout
│   ├── bootstrap-venv/                # optional installer environment
│   └── workflow-env/                  # editable runtime environments
└── work/                              # experiment data; WORK_ROOT
    ├── Ni-Pd-H/                       # one system work tree
    │   ├── raw-generations/
    │   │   ├── non_guided/
    │   │   │   ├── gen_1/
    │   │   │   │   ├── generated_crystals.extxyz
    │   │   │   │   ├── input_parameters.txt
    │   │   │   │   └── provenance/       # installation manifest and source state
    │   │   │   └── gen_2/
    │   │   └── repeated-guided/
    │   │       ├── gen_1/             # multi-batch campaign
    │   │       │   ├── batch_1/
    │   │       │   ├── batch_2/
    │   │       │   └── provenance/       # installation manifest and source state
    │   │       └── gen_2/             # multiple_runs.sh campaign
    │   │           ├── results/.../run_N/
    │   │           └── provenance/       # installation manifest and source state
    │   ├── configs/
    │   ├── logs/
    │   └── analysis-run/
    │       ├── processed/<system>/<generation-repository>/<stage>/
    │       └── figures/
    └── Mg-B-H/                        # another independent system
        ├── raw-generations/
        ├── configs/
        ├── logs/
        └── analysis-run/
```

Keep each generation directory together with its own `provenance/` directory.
These per-generation records, the scenario YAML, and the processed outputs are
the inputs needed to reproduce the analysis with a fresh `CODE_ROOT`
installation.

Archive one system, including all its generations and provenance, with:

```bash
SYSTEM_ARCHIVE="${SYSTEM_ROOT%/}.tar.gz"
tar -czf "$SYSTEM_ARCHIVE" \
  -C "$(dirname "$SYSTEM_ROOT")" "$(basename "$SYSTEM_ROOT")"
```
