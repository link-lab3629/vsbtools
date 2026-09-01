# Reproducibility Notebook Setup

This folder contains a self-contained reproducibility notebook for processing
packaged MatterGen outputs and generating the downstream analysis artifacts.

Notebook:

```text
mg_generation_postprocessing_pipeline.ipynb
```

Setup script:

```text
setup_reproducibility_envs.sh
```

This script is dedicated to reproducing the packaged notebook in a contained
workspace. For persistent editable environments used across projects, run the
repository-root [`install_vsbtools_mattergen.sh`](../../../install_vsbtools_mattergen.sh)
instead.

The notebook needs three Python environments:

- `vsbtools`: the Jupyter/kernel environment.
- `scout-matter`: the MatterGen fork used for guidance descriptors and losses.
- `grace`: a `tensorpotential` environment used by the GRACE bridge.

## Recommended Contained Setup

From a machine with `git`, Python, and internet access:

```bash
# Debian/Ubuntu example.
sudo apt install git build-essential python3 python3-venv python3-dev
```

```bash
bash setup_reproducibility_envs.sh \
  --root ./vsbtools_reproducibility_env \
  --run-root ./vsbtools_reproducibility_run
```

The script clones the default branch of each repository unless refs are passed
explicitly. In an interactive terminal it asks whether to reuse existing virtual
environments for `vsbtools`, `scout-matter`, and GRACE. Press Enter at a prompt
to create that environment under `./vsbtools_reproducibility_env`.

MatterGen environment creation and reuse are both supported:

- Press Enter at the `scout-matter/MatterGen` prompt to create and install a
  contained environment.
- Enter an existing venv root to reuse either a regular or editable MatterGen
  installation. The installer resolves the actual MatterGen source/import root
  and exposes that venv's dependencies inside the reproducibility launcher.

The `vsbtools` and MatterGen environments share MatterGen Python packages in one
kernel, so they must use the same Python major/minor and PyTorch versions. If one
is reused and the other is created, the installer automatically uses the reused
environment's Python. If both are reused, the installer validates their Python
and PyTorch versions before launching. GRACE runs through its own Python
subprocess and may use a different version.

`scout-matter` currently pins a CUDA PyTorch wheel (`torch==2.2.1+cu118`), so
the setup script uses the PyTorch CUDA wheel index for that environment and pins
the contained VSBTools and scout-matter environments to `numpy==1.26.4`. This
keeps PyTorch's compiled NumPy bridge on the NumPy 1.x ABI it expects. The script
also preinstalls matching PyTorch Geometric binary wheels for packages such as
`torch_cluster`, because those packages can fail if pip tries to build them from
source before `torch` is importable. The reproducibility virtual environments
use Python 3.9-3.11. After considering any reused environment, the script uses a
compatible local Python when available. Otherwise, for example on a system where
`python3` is Python 3.12, it bootstraps `uv` and installs a managed Python 3.11
under `state/` inside the contained workspace.

With no existing venvs supplied, the script creates the environment workspace
under `./vsbtools_reproducibility_env`:

```text
src/vsbtools
src/scout-matter
venvs/vsbtools
venvs/scout-matter
venvs/grace
state/
work/mg_generation_postprocessing_pipeline.ipynb
```

Notebook outputs are written separately under `./vsbtools_reproducibility_run`
by default. It also keeps local runtime state inside `state/`, including
Jupyter, IPython, matplotlib, pip cache, and `vsbtools` external-path
configuration. It does not install a user/global Jupyter kernel and does not
write to `~/.config/vsbtools`.

After installation, the script launches JupyterLab automatically. To install
without launching:

```bash
bash setup_reproducibility_envs.sh \
  --root ./vsbtools_reproducibility_env \
  --run-root ./vsbtools_reproducibility_run \
  --no-launch
```

Launch later with:

```bash
./vsbtools_reproducibility_env/run_reproducibility_notebook.sh
```

Run the notebook headlessly as a reproducibility test with:

```bash
./vsbtools_reproducibility_env/test_reproducibility_notebook.sh
```

The test runner writes notebook outputs under `./vsbtools_reproducibility_run`
and preserves them after the run. On failure, inspect that directory together
with the executed notebook copy in `work/`.

For a fixed reproducibility run, pin repository refs:

```bash
bash setup_reproducibility_envs.sh \
  --root ./vsbtools_reproducibility_env \
  --run-root ./vsbtools_reproducibility_run \
  --vsbtools-ref VSBTOOLS_COMMIT_OR_TAG \
  --scout-matter-ref SCOUT_MATTER_COMMIT_OR_TAG
```

If an older copy of this script failed while checking out a missing branch, rerun
with `--force` after updating the script, or pass the branch explicitly:

```bash
bash setup_reproducibility_envs.sh \
  --root ./vsbtools_reproducibility_env \
  --run-root ./vsbtools_reproducibility_run \
  --vsbtools-ref master
```

If installation failed with `No matching distribution found for
torch==2.2.1+cu118` or failed while building `torch_cluster`, update to this
script and rerun with `--force`:

```bash
bash setup_reproducibility_envs.sh \
  --root ./vsbtools_reproducibility_env \
  --run-root ./vsbtools_reproducibility_run \
  --force
```

Use `--force` to recreate the contained workspace:

```bash
bash setup_reproducibility_envs.sh \
  --root ./vsbtools_reproducibility_env \
  --run-root ./vsbtools_reproducibility_run \
  --force
```

## External environment discovery

The notebook has no environment-path fields to edit. When its kernel comes from
the installer-managed `venvs/vsbtools` environment, VSBTools automatically
discovers the sibling `venvs/scout-matter` and `venvs/grace` environments. The
generated launcher also exports their exact paths.

For a custom installation layout, set these variables in the environment that
launches Jupyter:

```text
MATTERGEN_PYTHON_PATH
SCOUT_MATTER_SITE_PACKAGES
GRACE_PYTHON
```

Persistent custom paths may instead be stored in
`~/.config/vsbtools/external_paths.json`.

## Expected Outputs

The notebook writes derived files under:

```text
vsbtools_reproducibility_run/
```

when launched through the contained setup. The contained setup copies the
notebook itself to:

```text
vsbtools_reproducibility_env/work/
```

so editable notebooks and generated artifacts stay separate. If the notebook is
opened manually outside the contained setup, it falls back to writing
`reproducibility_run/` next to the notebook.
