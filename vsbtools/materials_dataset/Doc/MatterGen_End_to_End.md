# MatterGen to VSBTools: generation and analysis

This procedure installs `vsbtools` and `scout-matter` from GitHub, generates
matched unguided and guided batches, and produces processed datasets, summary
tables, Pareto fronts, and histogram or KDE figures.

The examples use `Ni-Pd-H` with target `CN([Pd,Ni]-H) = 6`. Change the chemical
system, species, target, GPU number, and guidance weights for the experiment.

## 1. Install from GitHub

Requirements: Git, an NVIDIA GPU/driver suitable for CUDA 11.8, and internet
access for Python packages, MatterGen checkpoints, GRACE, and OPTIMADE.

```bash
mkdir mattergen-work
cd mattergen-work

git clone https://github.com/link-lab3629/vsbtools.git
git clone https://github.com/link-lab3629/scout-matter.git

VSBTOOLS_REPO_URL="$PWD/vsbtools" \
SCOUT_MATTER_REPO_URL="$PWD/scout-matter" \
bash "$PWD/vsbtools/vsbtools/materials_dataset/Examples/setup_reproducibility_envs.sh" \
  --root "$PWD/workflow-env" \
  --run-root "$PWD/analysis-run" \
  --no-launch
```

At each environment prompt, press Enter. The installer creates compatible
environments for VSBTools, scout-matter/MatterGen, and GRACE. For a reproducible
installation, add `--vsbtools-ref COMMIT` and `--scout-matter-ref COMMIT`.

The main executables are now:

```text
workflow-env/venvs/scout-matter/bin/mattergen-generate
workflow-env/venvs/vsbtools/bin/python
workflow-env/run_reproducibility_notebook.sh
```

## 2. Generate three matched batches

Activate scout-matter and define one output root:

```bash
source "$PWD/workflow-env/venvs/scout-matter/bin/activate"
export SYSTEM="Ni-Pd-H"
export RAW_ROOT="$PWD/raw-generations/$SYSTEM"
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

## 3. Postprocess the three batches

Launch the configured notebook environment:

```bash
deactivate
"$PWD/workflow-env/run_reproducibility_notebook.sh"
```

Open `mg_generation_postprocessing_pipeline.ipynb`, run its Sections 0 and 1,
then run the cells below. Use absolute paths if the notebook is launched from a
different working directory.

### 3.1 Run the scenario pipeline

```python
from importlib.resources import files
from pathlib import Path

from vsbtools.materials_dataset.analysis.scenario_pipeline import process_generation_dir

WORK = Path("/absolute/path/to/mattergen-work")
RAW_ROOT = WORK / "raw-generations" / "Ni-Pd-H"
PROCESSED_ROOT = WORK / "analysis-run" / "processed"
FIGURE_ROOT = WORK / "analysis-run" / "figures"
SCENARIO = Path(str(files("vsbtools.materials_dataset").joinpath(
    "Examples", "scenario_no_relax.yaml"
)))

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

The scenario performs structure parsing, symmetrization, minimum-distance
filtering, GRACE energy estimation, OPTIMADE reference collection, structural
deduplication, and reference merging. Rerunning it resumes from saved stages.

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

## 4. Expected outputs

```text
analysis-run/
├── processed/Ni-Pd-H/<generation>/
│   └── <stage>/
│       ├── manifest.yaml, data.csv, POSCARS/
│       ├── summary.csv, table.txt
│       ├── *_pf_1.csv, *_pf_1_table.txt
│       └── *_pf_1/                 # Pareto-front POSCAR files
└── figures/
    ├── Ni-Pd-H_coordination_kde.pdf
    └── repo_*_pareto.pdf
```

Keep the raw generation directories, processed repositories, scenario YAML,
Git commit hashes, and final figures together. They are the minimum inputs
needed to reproduce the analysis.

For many repeated guided runs, use scout-matter's `multiple_runs.sh`. Process
its individual `run_N/` directories; the parent directory also contains an
aggregate `generated_crystals.extxyz`, so processing both would duplicate
structures.
