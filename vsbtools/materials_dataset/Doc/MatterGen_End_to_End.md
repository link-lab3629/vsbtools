# MatterGen to VSBTools: generation and analysis

This procedure installs `vsbtools` and `scout-matter`/MatterGen from GitHub,
installs GRACE through the `tensorpotential` package, generates matched unguided
and guided batches, and produces processed datasets, summary tables, Pareto
fronts, and histogram or KDE figures.

The examples use `Ni-Pd-H` with target `CN([Pd,Ni]-H) = 6`. Change the chemical
system, species, target, GPU number, and guidance weights for the experiment.

## 0. Prepare Linux or macOS

Run all commands in a terminal. The installer accepts Python 3.11 or newer.
Internet access is needed for GitHub repositories, Python packages, MatterGen
checkpoints, GRACE, and OPTIMADE data.

On Linux, an NVIDIA GPU is strongly recommended; the installer uses CUDA 11.8
PyTorch wheels by default. On macOS, the installer selects CPU-compatible
wheels automatically. MatterGen can fall back to CPU, although generation and
energy estimation will be much slower.

### 0.1 Install operating-system prerequisites

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

### 0.2 Separate installed software from generated work

Choose a parent directory and define one project root plus separate software
and work roots for the current terminal session:

```bash
export PROJECT_ROOT="$PWD/mattergen-project"
export CODE_ROOT="$PROJECT_ROOT/code"
export WORK_ROOT="$PROJECT_ROOT/work"

mkdir -p "$CODE_ROOT" "$WORK_ROOT/configs" "$WORK_ROOT/logs"
```

The guide uses this layout throughout:

```text
mattergen-project/
├── code/                         # software: source code and environments
│   ├── vsbtools/                 # Git checkout and editable source
│   ├── scout-matter/             # Git checkout and editable MatterGen source
│   ├── bootstrap-venv/           # present when the venv option is used
│   └── workflow-env/             # vsbtools, scout-matter, and GRACE envs
└── work/                         # experiment inputs and generated results
    ├── configs/
    ├── logs/
    ├── raw-generations/
    ├── repeated-guided/
    └── analysis-run/
```

`CODE_ROOT` contains reinstallable software. `WORK_ROOT` contains the batches
and analyses to preserve. Commands may be run from any directory after these
absolute variables are defined. In a new terminal, set `PROJECT_ROOT` to this
same absolute directory and repeat the `CODE_ROOT` and `WORK_ROOT` exports.

### 0.3 Create one bootstrap environment

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

## 1. Install software under `CODE_ROOT`

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

The installer creates persistent environments for VSBTools,
scout-matter/MatterGen, and GRACE. Running it again updates those environments
from the current source checkouts.

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

### 1.1 Editable installs and the regular alternative

`--editable` installs VSBTools from `$CODE_ROOT/vsbtools` and MatterGen from
`$CODE_ROOT/scout-matter`. The environments contain their dependencies and
console scripts, while Python imports the source files directly from these two
Git checkouts. Restart the Python process or Jupyter kernel after editing source
code; rebuilding the environments is usually unnecessary.

Verify the live source paths:

```bash
"$CODE_ROOT/workflow-env/venvs/vsbtools/bin/python" -c \
  "import vsbtools; print(vsbtools.__file__)"
"$CODE_ROOT/workflow-env/venvs/scout-matter/bin/python" -c \
  "import mattergen; print(mattergen.__file__)"
```

The first path should be under `$CODE_ROOT/vsbtools`; the second should be under
`$CODE_ROOT/scout-matter`.

Editable installations are mutable. Uncommitted edits and later branch changes
alter subsequent runs, and a commit hash alone cannot reproduce uncommitted
content. Before conducting an experiment, record the relevant commit hashes and
save any uncommitted changes as a patch. Archive these provenance records
together with `WORK_ROOT`.

For a stable installed snapshot, first check out the desired clean commits and
use `--regular` with a separate environment root:

```bash
bash "$CODE_ROOT/vsbtools/install_vsbtools_mattergen.sh" \
  --vsbtools-source "$CODE_ROOT/vsbtools" \
  --mattergen-source "$CODE_ROOT/scout-matter" \
  --env-root "$CODE_ROOT/workflow-env-regular" \
  --python "$PYTHON_FOR_SETUP" \
  --regular
```

The regular installation copies package code into its environments, so later
edits in the checkouts do not affect it. Record the commits printed in
`installation_manifest.json`. For reproduction of the packaged demonstration
notebook itself, use the separate
`vsbtools/materials_dataset/Examples/setup_reproducibility_envs.sh`; that script
creates contained source copies, runtime state, and notebook outputs for its
specific reproducibility task.

### 1.2 Install and verify GRACE/tensorpotential

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

## 2. Generate three matched batches under `WORK_ROOT`

Activate scout-matter and define one output root:

```bash
source "$CODE_ROOT/workflow-env/venvs/scout-matter/bin/activate"
export SYSTEM="Ni-Pd-H"
export RAW_ROOT="$WORK_ROOT/raw-generations/$SYSTEM"
mkdir -p "$RAW_ROOT"
```

### 2.1 Unguided baseline

```bash
mattergen-generate "$RAW_ROOT/unguided" \
  --pretrained-name=chemical_system \
  --batch_size=20 \
  --num_batches=1 \
  --properties_to_condition_on="{'chemical_system':'Ni-Pd-H'}" \
  --diffusion_guidance_factor=2.0 \
  --record_trajectories=False \
  --print_loss=False \
  --force_gpu=0
```

### 2.2 Ranked-neighbor softplus guidance

`ranked_coordination` applies the ranked-neighbor softplus objective. The
grouped center `[Pd,Ni]` is treated as one coordination constraint.

```bash
mattergen-generate "$RAW_ROOT/ranked-softplus" \
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

### 2.3 Mean group-coordination guidance

Grouped species use the current `mean_coordination` objective with a grouped
key. `group_coordination` remains a compatibility alias.

```bash
mattergen-generate "$RAW_ROOT/group-coordination" \
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

### 2.4 Generate an ensemble with `multiple_runs.sh`

Use scout-matter's root-level `multiple_runs.sh` for many independent guided
runs. It invokes `mattergen-generate` once per run, retries CUDA out-of-memory
failures with a smaller batch, records run durations, and combines the
successful structures into one aggregate `.extxyz` file.

Activate the scout-matter environment from `CODE_ROOT`, then enter its source
repository because `multiple_runs.sh` lives at the repository root:

```bash
source "$CODE_ROOT/workflow-env/venvs/scout-matter/bin/activate"
cd "$CODE_ROOT/scout-matter"

./multiple_runs.sh --help
```

The following command repeats the mean group-coordination generation from
Section 2.3 fifty times:

```bash
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
  --base-dir "$WORK_ROOT/repeated-guided" \
  --log-file "$WORK_ROOT/logs/group-coordination.log"
```

Append `--dry-run` first to inspect every generated `mattergen-generate`
command without starting generation. The important size controls are:

- `--batch-size`: structures generated in each batch.
- `--num-batches`: batches generated within each independent run.
- `--runs`: number of independent runs.

For ranked-neighbor softplus guidance, either change `--guidance` in the command
above or use a YAML config. Create
`$WORK_ROOT/configs/repeated-ranked-softplus.yaml` with:

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

# These paths lead from code/scout-matter into the separate work tree.
base_dir: ../../work/repeated-guided
log_file: ../../work/logs/ranked-softplus.log
dry_run: false
```

Run the YAML configuration as the only command-line option:

```bash
./multiple_runs.sh --config "$WORK_ROOT/configs/repeated-ranked-softplus.yaml"
```

On an out-of-memory failure, the script retries the same run with
`ceil(current_batch_size * oom_backoff_percent / 100)`. It stops after
`oom_retries`, or when another reduction would cross `min_batch_size`. Therefore,
record the `final_batch_size` column when comparing ensembles whose retries may
have produced different numbers of structures.

Results are nested under a path derived from the system, guidance parameters,
and guidance settings:

```text
$WORK_ROOT/repeated-guided/results/Ni-Pd-H/<guidance>/<parameters>/<settings>/
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

For the pipeline in Section 3, collect the individual run directories:

```python
import os
from pathlib import Path

WORK_ROOT = Path(os.environ["WORK_ROOT"])
REPEATED_ROOT = WORK_ROOT / "repeated-guided"
generation_dirs = sorted(
    path.parent
    for path in REPEATED_ROOT.glob("results/Ni-Pd-H/**/run_*/input_parameters.txt")
)
```

Process each `run_N/` once. The parent settings directory contains the aggregate
`generated_crystals.extxyz`; processing that file as an additional batch would
duplicate the same structures.

## 3. Postprocess the batches under `WORK_ROOT`

Copy the packaged scenario into the work tree once, then launch the configured
notebook environment. Customize the copy under `WORK_ROOT/configs` for this
experiment:

```bash
if [[ ! -f "$WORK_ROOT/configs/scenario_no_relax.yaml" ]]; then
  cp "$CODE_ROOT/vsbtools/vsbtools/materials_dataset/Examples/scenario_no_relax.yaml" \
    "$WORK_ROOT/configs/scenario_no_relax.yaml"
fi

deactivate
mkdir -p "$WORK_ROOT/analysis-run"
if [[ ! -f "$WORK_ROOT/analysis-run/mg_generation_postprocessing_pipeline.ipynb" ]]; then
  cp "$CODE_ROOT/vsbtools/vsbtools/materials_dataset/Examples/mg_generation_postprocessing_pipeline.ipynb" \
    "$WORK_ROOT/analysis-run/mg_generation_postprocessing_pipeline.ipynb"
fi
cd "$WORK_ROOT/analysis-run"
"$CODE_ROOT/workflow-env/launch_jupyter.sh"
```

Open `mg_generation_postprocessing_pipeline.ipynb`, run its Sections 0 and 1,
then run the cells below. Use absolute paths if the notebook is launched from a
different working directory.

### 3.1 Run the scenario pipeline

```python
import os
from pathlib import Path

from vsbtools.materials_dataset.analysis.scenario_pipeline import process_generation_dir

WORK_ROOT = Path(os.environ["WORK_ROOT"])
RAW_ROOT = WORK_ROOT / "raw-generations" / "Ni-Pd-H"
PROCESSED_ROOT = WORK_ROOT / "analysis-run" / "processed"
FIGURE_ROOT = WORK_ROOT / "analysis-run" / "figures"
SCENARIO = WORK_ROOT / "configs" / "scenario_no_relax.yaml"

PROCESSED_ROOT.mkdir(parents=True, exist_ok=True)
FIGURE_ROOT.mkdir(parents=True, exist_ok=True)

generation_dirs = [
    RAW_ROOT / "unguided",
    RAW_ROOT / "ranked-softplus",
    RAW_ROOT / "group-coordination",
]

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

### 3.2 Build summary tables and Pareto-front files

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

### 3.3 Choose the histogram/KDE callable

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

Use the same `get_loss_fn(name, target=...)` pattern shown in Section 3.2 when
you need to recompute a loss for Pareto analysis.

### 3.4 Plot a histogram or KDE

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

### 3.5 Plot the Pareto fronts

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

## 4. Expected directory layout

```text
$PROJECT_ROOT/
├── code/                              # installed software; CODE_ROOT
│   ├── vsbtools/                      # editable VSBTools source checkout
│   ├── scout-matter/                  # editable MatterGen source checkout
│   └── workflow-env/venvs/            # executable environments
│       ├── vsbtools/
│       ├── scout-matter/
│       └── grace/
└── work/                              # experiment data; WORK_ROOT
    ├── configs/
    │   ├── scenario_no_relax.yaml
    │   └── repeated-ranked-softplus.yaml
    ├── logs/
    │   ├── group-coordination.log
    │   └── ranked-softplus.log
    ├── raw-generations/Ni-Pd-H/
    │   ├── unguided/
    │   ├── ranked-softplus/
    │   └── group-coordination/
    ├── repeated-guided/results/Ni-Pd-H/
    │   └── <guidance>/<parameters>/<settings>/
    │       ├── generated_crystals.extxyz
    │       ├── durations.csv
    │       └── run_N/
    └── analysis-run/
        ├── processed/Ni-Pd-H/<generation>/<stage>/
        │   ├── manifest.yaml, data.csv, POSCARS/
        │   ├── summary.csv, table.txt
        │   ├── *_pf_1.csv, *_pf_1_table.txt
        │   └── *_pf_1/                # Pareto-front POSCAR files
        └── figures/
            ├── Ni-Pd-H_coordination_kde.pdf
            └── repo_*_pareto.pdf
```

Keep `WORK_ROOT` together with the scenario YAML and the Git commit hashes from
both repositories. These are the inputs needed to reproduce the analysis with a
fresh `CODE_ROOT` installation.
