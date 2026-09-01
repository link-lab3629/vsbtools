# vsbtools

`vsbtools` is a Python research toolbox for building, transforming, and
analyzing crystal-structure datasets. Its dataset tools live in
`vsbtools/materials_dataset`.

## Overview

`CrystalEntry` represents one structure plus its id, optional energy, formula,
and metadata. `CrystalDataset` is a read-oriented collection of entries with
dataset metadata, a cached `elements` property derived from entry compositions,
`merge()` and `filter()` helpers, and parent/child tracking for processed
stages. Datasets also keep track of the directory used for their
`manifest.yaml`, `data.csv`, and `POSCARS/` files.

The package can:

- store datasets as `manifest.yaml`/`data.csv`/`POSCARS/` bundles, the
  package's native on-disk format;
- import structures from collections of individual POSCAR files, multi-image
  POSCARS, CIF collections, and extended XYZ files (`.extxyz`);
- export datasets as POSCAR collections or multi-image POSCARS;
- filter pathological structures by density, cell geometry, and minimum
  interatomic distance;
- analyze and enforce crystallographic symmetry, including space-group labels,
  symmetry-operation counts, nonequivalent-site counts, primitive standard
  structures, and refined structures;
- poll and cache reference structures from OPTIMADE providers, Alexandria,
  OQMD, Materials Project, and local structure/energy files;
- merge generated datasets with reference datasets and mark reproduced
  reference structures;
- estimate energies and relax structures through registered ML backends such as
  MatterSim and GRACE;
- build phase diagrams, compute formation energies and energy above hull, and
  filter structures by hull distance;
- compare structures with DScribe/USPEX-style fingerprints, detect structures
  already present in a reference set, cluster duplicates, and keep best
  representatives;
- access descriptors used for guidance losses in `scout-matter`;
- collect summary tables, generation statistics, histograms, KDE plots, Pareto
  fronts, and reproducibility artifacts.

## Core Modules

| File | Role |
| --- | --- |
| `crystal_entry.py` | `CrystalEntry`: one crystal structure plus id, optional energy, formula, and metadata. |
| `crystal_dataset.py` | `CrystalDataset`: read-oriented collection of entries with metadata, provenance, `merge()`, and `filter()`. |
| `analysis/scenario_pipeline.py` | YAML/JSON scenario executor for user-defined directed acyclic workflows. |
| `analysis/symmetry_tools.py` | Space-group analysis, symmetry-operation counts, nonequivalent-site counts, and symmetrized structures. |
| `analysis/similarity_tools.py` | Fingerprint-based structure matching, reference-set lookup, and deduplication. |
| `analysis/phase_diagram_tools.py` | Phase diagram and energy-above-hull calculations. |
| `analysis/summary.py`, `analysis/guidance_statistics.py` | Per-entry summary tables and guidance-analysis reporting. |
| `energy_estimation/` | Energy estimation and structure relaxation through MatterSim and GRACE adapters. |
| `geom_utils/structure_checks.py` | Density, cell-shape, and minimum-distance structure sanity checks. |
| `io/` | Dataset manifests, CSV/POSCAR bundles, POSCAR/CIF/extxyz readers, generation metadata parsing, and database-source parsers. |
| `scripts/poll_databases.py` | Integrates reference structures from Alexandria, OQMD, Materials Project, and OPTIMADE providers. |

## Tutorial

The `Doc` directory contains a worked tutorial for common dataset operations:

- `vsbtools/materials_dataset/Doc/Crystal_Dataset_Use_Cases.ipynb`
- `vsbtools/materials_dataset/Doc/Crystal_Dataset_Use_Cases.md`

The notebook is the source version; the Markdown file is a rendered copy for
quick reading. It walks through loading generated structures, polling reference
databases, cleaning, deduplication, symmetrization, energy and hull analysis,
dataset persistence, reporting, Pareto-front examples, and multi-dataset
descriptor plots.

For a concise installation-to-analysis recipe covering unguided MatterGen,
ranked-softplus guidance, grouped-species coordination guidance, postprocessing,
Pareto fronts, and histogram/KDE figures, see
[`MatterGen_End_to_End.md`](vsbtools/materials_dataset/Doc/MatterGen_End_to_End.md).

## Scenario Workflows

`analysis/scenario_pipeline.py` runs YAML/JSON-defined workflows as a directed
acyclic graph of stages. Registered operations include raw parsing, density and
minimum-distance filtering, symmetrization, database polling, reference merging,
energy estimation, relaxation, hull filtering, and deduplication.

Reference database polling prefers OPTIMADE by default. Other supported sources
include local Alexandria JSON exports, local OQMD MySQL deployments, and
Materials Project through its API.

Database caches use the platform's per-user cache location and are created only
when data is written:

- Windows: `%LOCALAPPDATA%\vsbtools\Cache\DB_caches`
- macOS: `~/Library/Caches/vsbtools/DB_caches`
- Linux/Unix: `${XDG_CACHE_HOME:-~/.cache}/vsbtools/DB_caches`

Set `VSBTOOLS_CACHE_DIR` to override the `vsbtools` cache root on any platform.

## MatterGen Postprocessing

One important packaged use case is postprocessing MatterGen outputs, especially
guided generations produced by the `scout-matter` fork. The provided workflow
preserves generation metadata and uses it to analyze guidance-loss
distributions, target-property distributions, structural descriptors, Pareto
fronts, and reproducibility metrics.

For an installation reused across generation and analysis projects, keep the
VSBTools and scout-matter checkouts beside each other and run the repository-root
installer:

```bash
git clone https://github.com/link-lab3629/scout-matter.git ../scout-matter
bash ./install_vsbtools_mattergen.sh \
  --mattergen-source ../scout-matter \
  --env-root ../workflow-env \
  --python python3 \
  --editable
```

The MatterGen installer accepts Python 3.11 or newer for the bootstrap
interpreter. Use the system `python3`, a virtual environment, or a Conda
environment, provided that its reported version is at least 3.11:

```bash
"$PYTHON_FOR_SETUP" --version
```

When using a bootstrap virtual environment, the standard `python3` executable
is sufficient when it is version 3.11 or newer:

```bash
python3 -m venv "$CODE_ROOT/bootstrap-venv"
source "$CODE_ROOT/bootstrap-venv/bin/activate"
export PYTHON_FOR_SETUP="$CODE_ROOT/bootstrap-venv/bin/python"
```

In a multiline shell command, the backslash must be the final character on the
line. The complete branch-selecting form is:

```bash
bash "$CODE_ROOT/vsbtools/install_vsbtools_mattergen.sh" \
  --vsbtools-source "$CODE_ROOT/vsbtools" \
  --mattergen-source "$CODE_ROOT/scout-matter" \
  --env-root "$CODE_ROOT/workflow-env" \
  --python "$PYTHON_FOR_SETUP" \
  --vsbtools-ref linklab-installation-procedure \
  --fetch \
  --editable
```

Use `--vsbtools-ref BRANCH`, `--mattergen-ref BRANCH`, and optionally `--fetch`
to select source branches during installation.

### Choosing editable or regular installation

If you want to try another branch and can reuse the current environment, use
the same `workflow-env` with `--editable`. Select the branch with the ref
options above, or switch the clean source checkouts manually, then restart the
Python process or Jupyter kernel. Reinstall only when the branch changes its
dependencies or installation metadata.

Use `--regular` when the new experiment must have its own stable code snapshot
while the existing editable environment remains available. Give it a separate
environment root, and preferably separate source checkouts or Git worktrees if
both experiments will run at the same time:

```bash
bash "$CODE_ROOT/vsbtools/install_vsbtools_mattergen.sh" \
  --vsbtools-source "$CODE_ROOT/vsbtools-branch-b" \
  --mattergen-source "$CODE_ROOT/scout-matter-branch-b" \
  --env-root "$CODE_ROOT/workflow-env-branch-b" \
  --python "$PYTHON_FOR_SETUP" \
  --vsbtools-ref VSBTOOLS_BRANCH_B \
  --mattergen-ref MATTERGEN_BRANCH_B \
  --fetch \
  --regular
```

Thus, switching branches in an existing editable setup and creating an
independent regular snapshot are two different workflows. The `--regular`
name means the ordinary non-editable `pip install` mode; it does not mean that
every branch change requires a second installation.

### Switching between installed environments

The two installation modes are selected by their environment roots. For
example, keep the editable installation in `workflow-env` and the regular
snapshot in `workflow-env-branch-b`. To switch, start a fresh shell (or first
deactivate the current virtual environment), then source the environment file
for the installation you want.

For the editable installation:

```bash
source "$CODE_ROOT/workflow-env/workflow_env.sh"
source "$CODE_ROOT/workflow-env/venvs/scout-matter/bin/activate"
```

For the regular snapshot:

```bash
source "$CODE_ROOT/workflow-env-branch-b/workflow_env.sh"
source "$CODE_ROOT/workflow-env-branch-b/venvs/scout-matter/bin/activate"
```

Use only one block in a shell. The generated
`workflow_env.sh` selects the matching `VSBTOOLS_PYTHON`, `MATTERGEN_PYTHON`,
and `GRACE_PYTHON`; it does not reinstall anything. The corresponding
`launch_jupyter.sh` also starts Jupyter with the selected VSBTools environment.
For the editable installation:

```bash
"$CODE_ROOT/workflow-env/launch_jupyter.sh"
```

For the regular snapshot:

```bash
"$CODE_ROOT/workflow-env-branch-b/launch_jupyter.sh"
```

Choose the command from the environment root whose code and dependencies you
want to use. If only one installation exists, run the installer once to create
the other one; switching thereafter only means selecting the desired
environment.

See the [end-to-end MatterGen guide](vsbtools/materials_dataset/Doc/MatterGen_End_to_End.md)
for generation, postprocessing, Pareto fronts, and distribution plots.

Before generation, preserve the selected installation and source state under
`WORK_ROOT/provenance`. The installer writes `installation_manifest.json` with
the selected branches, commits, and dirty-state flags. The end-to-end guide
contains a copy-and-record command block for that manifest, `workflow_env.sh`,
the two commit hashes, Git status files, and patches for uncommitted tracked
changes.

A packaged reproducibility pipeline is provided for the MatterGen guidance
analysis workflow. It starts from the raw-generation archives in
`Examples/raw_generations`, postprocesses them into staged datasets, builds
summary/Pareto artifacts, plots descriptor distributions, and writes a run
manifest.

```text
vsbtools/materials_dataset/Examples/
├── README_reproducibility.md
├── setup_reproducibility_envs.sh
└── mg_generation_postprocessing_pipeline.ipynb
```

The setup script creates a contained workspace with three virtual environments:
`vsbtools`, `scout-matter`/MatterGen, and GRACE/`tensorpotential`. Notebook
outputs are written to a separate run directory. Each prompt accepts an existing
venv root, including an editable MatterGen environment; pressing Enter creates
the corresponding contained environment. This script is specific to reproducing
the packaged notebook.

```bash
bash vsbtools/materials_dataset/Examples/setup_reproducibility_envs.sh \
  --root ./vsbtools_reproducibility_env \
  --run-root ./vsbtools_reproducibility_run
```

See `Examples/README_reproducibility.md` for manual configuration, pinned
commit/tag setup, and launch instructions.

## Python Scenario Example

```python
from pathlib import Path
from vsbtools.materials_dataset.analysis.scenario_pipeline import ScenarioPipeline
from vsbtools.materials_dataset.io import write

pipeline = ScenarioPipeline.from_file(Path("scenario.yaml"))
pipeline.ctx.globals["elements"] = ["Si", "O"]
pipeline.ctx.toolkit_options["structure_parser"]["root"] = Path("input_structures")

for stage_name, dataset in pipeline.run():
    write(dataset, enforce_base_path=Path("processed") / stage_name)
```

## Installation

Python 3.10 or newer is required for the standalone `vsbtools` package. The
MatterGen workflow installer requires Python 3.11 or newer as described above.

```bash
python3 -m pip install -e .
python3 -m pip install -e ".[materials_dataset]"
```

Additional external requirements depend on the workflow:

| Workflow | External dependency |
| --- | --- |
| Optional legacy `USPEXBridge` similarity backend | Python USPEX package/installation importable as `USPEX`. |
| Database polling | Materials Project credentials and/or Alexandria/OQMD access. |
| ML energy estimation | MatterSim and/or GRACE environment. |
| Diffusion guidance analysis | MatterGen importability via `MATTERGEN_PYTHON_PATH` or host-specific configuration. |
| Packaged reproducibility notebook | Use `Examples/setup_reproducibility_envs.sh` to create contained `vsbtools`, `scout-matter`, and GRACE environments. |

External tools mentioned above:

- MatterGen is a crystal generative model; `scout-matter` is the MatterGen fork
  used by the guidance workflow (<https://github.com/link-lab3629/scout-matter>).
- MatterSim and GRACE are ML interatomic-potential/energy-estimation backends;
  GRACE is accessed through `tensorpotential`.
- USPEX is an evolutionary crystal-structure-prediction code. `materials_dataset`
  retains a legacy-compatible structural fingerprint and optional bridge where
  needed for dataset deduplication.

## Running Tests

There is no single project test runner configured. The repository contains
`unittest`-style tests under `materials_dataset` subdirectories.

```bash
python3 -m unittest discover -s vsbtools/materials_dataset -t . -p "*_Test.py"
python3 -m unittest discover -s vsbtools/materials_dataset -t . -p "*_test.py"
```

Many tests require optional dependencies or local sample data.

## Development Notes

- Prefer the active `materials_dataset` API for new dataset-processing code.
- Many scripts assume an editable install with the repository root on `PYTHONPATH`.
- Generated artifacts such as `manifest.yaml`, `data.csv`, `POSCARS/`, cached database files, plots, and summary tables are expected outputs of normal workflows.
