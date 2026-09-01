import copy
import os
import sys
import types
from pathlib import Path

import torch
from ...external_paths import add_sys_path, resolve_external_path

_MATTERGEN_IMPORT_ERROR = None
mgen_path = None

ChemGraph = None
LOSS_REGISTRY = {}
_soft_neighbor_counts_per_A_single = None
_clear_globals_impl = None
compute_mean_coordination = None
compute_target_coordination_share = None
compute_target_share = None
volume = None
volume_pa = None
mattergen_chemgraph_fn_collection = {}
mattergen_cell_frac_types_fn_collection = {}


class _ChemGraphCompat:
    """Minimal ChemGraph-compatible container for MatterGen descriptor/loss functions."""

    def __init__(self, atomic_numbers=None, pos=None, cell=None, **kwargs):
        self.atomic_numbers = atomic_numbers
        self.pos = pos
        self.cell = cell
        for key, value in kwargs.items():
            setattr(self, key, value)


def _mattergen_source_tree_validator(path: Path) -> tuple[bool, str]:
    if not path.is_dir():
        return False, f"{path} is not a directory"
    missing = [
        rel_path for rel_path in (
            Path("mattergen/common/data/chemgraph.py"),
            Path("mattergen/diffusion/diffusion_loss.py"),
        )
        if not (path / rel_path).is_file()
    ]
    if missing:
        return False, f"missing MatterGen source file(s): {', '.join(p.as_posix() for p in missing)}"
    return True, ""


def _refresh_function_collections() -> None:
    global mattergen_chemgraph_fn_collection, mattergen_cell_frac_types_fn_collection
    mattergen_chemgraph_fn_collection = {"volume": volume, "volume_pa": volume_pa}
    mattergen_cell_frac_types_fn_collection = {
        "compute_mean_coordination": compute_mean_coordination,
        "compute_target_coordination_share": compute_target_coordination_share,
        "compute_target_share": compute_target_share,
        "_soft_neighbor_counts_per_A_single": _soft_neighbor_counts_per_A_single,
    }


def _import_soft_neighbor_counts():
    """Load the private coordination helper across MatterGen source layouts.

    Older MatterGen revisions re-exported this helper from ``diffusion_loss``;
    the current scout-matter checkout keeps the implementation in
    ``coordination_loss``.  The bridge only needs the function for the
    descriptor collection, so accept both layouts.
    """
    try:
        from mattergen.diffusion.diffusion_loss import (
            _soft_neighbor_counts_per_A_single as implementation,
        )
    except ImportError as diffusion_loss_error:
        try:
            from mattergen.diffusion.coordination_loss import (
                _soft_neighbor_counts_per_A_single as implementation,
            )
        except ImportError:
            raise diffusion_loss_error
    return implementation


def _configure_mattergen_path(*, prompt: bool) -> Path | None:
    global mgen_path
    if mgen_path is not None:
        return Path(mgen_path)

    resolved_path = resolve_external_path(
        name="MatterGen source tree",
        config_key="mattergen_python_path",
        env_var="MATTERGEN_PYTHON_PATH",
        validator=_mattergen_source_tree_validator,
        prompt=prompt,
        required=prompt,
        prompt_text="Enter path to MatterGen source tree (ex.: /home/user/scout-matter): ",
    )
    if resolved_path is not None:
        add_sys_path(resolved_path, prepend=False)
        scout_site_packages = os.environ.get("SCOUT_MATTER_SITE_PACKAGES")
        if scout_site_packages:
            dependency_path = Path(scout_site_packages).expanduser()
            if not dependency_path.is_dir():
                raise FileNotFoundError(
                    "SCOUT_MATTER_SITE_PACKAGES is not a directory: "
                    f"{dependency_path}"
                )
            add_sys_path(dependency_path, prepend=False)
        mgen_path = resolved_path
    return resolved_path


def _import_diffusion_loss_with_chemgraph_compat(*, restore_modules: bool = False):
    chemgraph_module_name = "mattergen.common.data.chemgraph"
    diffusion_loss_module_name = "mattergen.diffusion.diffusion_loss"
    coordination_loss_module_name = "mattergen.diffusion.coordination_loss"
    previous_chemgraph_module = sys.modules.get(chemgraph_module_name)
    previous_diffusion_loss_module = sys.modules.pop(diffusion_loss_module_name, None)
    # coordination_loss binds ChemGraph at import time.  Reload it under the
    # compatibility ChemGraph as well, otherwise its isinstance checks keep
    # referring to the real MatterGen class cached by an earlier import.
    previous_coordination_loss_module = sys.modules.pop(coordination_loss_module_name, None)

    compat_module = types.ModuleType(chemgraph_module_name)
    compat_module.ChemGraph = _ChemGraphCompat
    compat_module.ChemGraphBatch = _ChemGraphCompat
    sys.modules[chemgraph_module_name] = compat_module
    try:
        from mattergen.diffusion.diffusion_loss import (
            LOSS_REGISTRY as _LOSS_REGISTRY,
            clear_globals as _clear_globals_impl_imported,
            compute_mean_coordination as _compute_mean_coordination,
            volume as _volume,
            volume_pa as _volume_pa,
        )
        _soft_neighbor_counts_per_A_single_impl = _import_soft_neighbor_counts()
        try:
            from mattergen.diffusion.diffusion_loss import (
                compute_target_coordination_share as _compute_target_coordination_share,
            )
        except ImportError:
            from mattergen.diffusion.diffusion_loss import (
                compute_target_share as _compute_target_coordination_share,
            )
    except ImportError:
        if previous_chemgraph_module is None:
            sys.modules.pop(chemgraph_module_name, None)
        else:
            sys.modules[chemgraph_module_name] = previous_chemgraph_module
        if previous_diffusion_loss_module is None:
            sys.modules.pop(diffusion_loss_module_name, None)
        else:
            sys.modules[diffusion_loss_module_name] = previous_diffusion_loss_module
        if previous_coordination_loss_module is None:
            sys.modules.pop(coordination_loss_module_name, None)
        else:
            sys.modules[coordination_loss_module_name] = previous_coordination_loss_module
        raise

    if restore_modules:
        if previous_chemgraph_module is None:
            sys.modules.pop(chemgraph_module_name, None)
        else:
            sys.modules[chemgraph_module_name] = previous_chemgraph_module
        if previous_diffusion_loss_module is None:
            sys.modules.pop(diffusion_loss_module_name, None)
        else:
            sys.modules[diffusion_loss_module_name] = previous_diffusion_loss_module
        if previous_coordination_loss_module is None:
            sys.modules.pop(coordination_loss_module_name, None)
        else:
            sys.modules[coordination_loss_module_name] = previous_coordination_loss_module

    return (
        _ChemGraphCompat,
        _LOSS_REGISTRY,
        _soft_neighbor_counts_per_A_single_impl,
        _clear_globals_impl_imported,
        _compute_mean_coordination,
        _compute_target_coordination_share,
        _volume,
        _volume_pa,
    )


def _import_mattergen() -> None:
    global ChemGraph, LOSS_REGISTRY, _soft_neighbor_counts_per_A_single, _clear_globals_impl
    global compute_mean_coordination, compute_target_coordination_share, compute_target_share, volume, volume_pa
    global _MATTERGEN_IMPORT_ERROR

    try:
        from mattergen.common.data.chemgraph import ChemGraph as _ChemGraph
        from mattergen.diffusion.diffusion_loss import (
            LOSS_REGISTRY as _LOSS_REGISTRY,
            clear_globals as _clear_globals_impl_imported,
            compute_mean_coordination as _compute_mean_coordination,
            volume as _volume,
            volume_pa as _volume_pa,
        )
        _soft_neighbor_counts_per_A_single_impl = _import_soft_neighbor_counts()
        try:
            from mattergen.diffusion.diffusion_loss import (
                compute_target_coordination_share as _compute_target_coordination_share,
            )
        except ImportError:
            from mattergen.diffusion.diffusion_loss import (
                compute_target_share as _compute_target_coordination_share,
            )
    except ImportError as exc:
        if getattr(exc, "name", None) != "torch_geometric":
            _MATTERGEN_IMPORT_ERROR = exc
            return
        try:
            (
                _ChemGraph,
                _LOSS_REGISTRY,
                _soft_neighbor_counts_per_A_single_impl,
                _clear_globals_impl_imported,
                _compute_mean_coordination,
                _compute_target_coordination_share,
                _volume,
                _volume_pa,
            ) = _import_diffusion_loss_with_chemgraph_compat()
        except ImportError as compat_exc:
            _MATTERGEN_IMPORT_ERROR = compat_exc
            return

    ChemGraph = _ChemGraph
    LOSS_REGISTRY = _LOSS_REGISTRY
    _soft_neighbor_counts_per_A_single = _soft_neighbor_counts_per_A_single_impl
    _clear_globals_impl = _clear_globals_impl_imported
    compute_mean_coordination = _compute_mean_coordination
    compute_target_coordination_share = _compute_target_coordination_share
    compute_target_share = _compute_target_coordination_share
    volume = _volume
    volume_pa = _volume_pa
    _MATTERGEN_IMPORT_ERROR = None
    _refresh_function_collections()


_configure_mattergen_path(prompt=False)
_import_mattergen()


def _require_mattergen():
    if ChemGraph is None:
        _configure_mattergen_path(prompt=True)
        _import_mattergen()
    if ChemGraph is None:
        if mgen_path is None:
            raise ModuleNotFoundError(
                "mattergen is not configured. Set MATTERGEN_PYTHON_PATH, configure external_paths.json, "
                "or enter the path when prompted."
            ) from _MATTERGEN_IMPORT_ERROR
        raise ModuleNotFoundError(
            f"MatterGen source tree is configured at '{mgen_path}', but importing MatterGen failed. "
            "This usually means the active Python environment is missing a MatterGen dependency. "
            f"Original error: {_MATTERGEN_IMPORT_ERROR}"
        ) from _MATTERGEN_IMPORT_ERROR


def _device_from_force_gpu(force_gpu: int) -> torch.device:
    if not isinstance(force_gpu, int):
        raise TypeError(f"force_gpu must be int, got {type(force_gpu).__name__}")
    if torch.cuda.is_available():
        cuda_count = torch.cuda.device_count()
        if force_gpu < 0 or force_gpu >= cuda_count:
            raise ValueError(f"force_gpu={force_gpu} is out of range for {cuda_count} visible CUDA device(s)")
        return torch.device(f"cuda:{force_gpu}")
    return torch.device("cpu")


def structure_to_tensors(struct, force_gpu: int):
    _require_mattergen()
    device = _device_from_force_gpu(force_gpu)

    cell = torch.tensor(
        struct.lattice.matrix.tolist(),
        dtype=torch.float32,
        device=device,
    )

    # fractional coordinates
    pos = torch.tensor(
        struct.frac_coords.tolist(),
        dtype=torch.float32,
        requires_grad=True,
        device=device,
    )

    # atomic numbers
    atomic_numbers = torch.tensor(
        [site.specie.number for site in struct],
        dtype=torch.int64,
        device=device,
    )

    return cell, pos, atomic_numbers


def structure_to_single_chemgraph(struct, force_gpu: int):
    _require_mattergen()
    cell, pos, atomic_numbers = structure_to_tensors(struct, force_gpu=force_gpu)
    return ChemGraph(
        cell=cell,
        atomic_numbers=atomic_numbers,
        pos=pos,
        num_atoms=torch.tensor([len(atomic_numbers)], device=cell.device),
    )


def entry2tensors(entry, force_gpu: int):
    return structure_to_tensors(entry.structure, force_gpu=force_gpu)


def entry2chemgraph(entry, force_gpu: int):
    return structure_to_single_chemgraph(entry.structure, force_gpu=force_gpu)


def clear_globals():
    _require_mattergen()
    _clear_globals_impl()


def _tensor_to_python(value):
    """Convert a tensor without using Torch's optional NumPy bridge."""
    value = value.detach().cpu()
    return value.item() if value.numel() == 1 else value.tolist()


def get_target_value_fn(fn_name, force_gpu: int = 0, **params):
    _require_mattergen()
    fn = lambda x: None

    if fn_name in mattergen_chemgraph_fn_collection:
        def fn(entry):
            x = entry2chemgraph(entry, force_gpu=force_gpu)
            value = mattergen_chemgraph_fn_collection[fn_name](x, t=None, **params)
            return _tensor_to_python(value[0])
    elif fn_name in mattergen_cell_frac_types_fn_collection:
        def fn(entry):
            cell, frac, types = structure_to_tensors(entry.structure, force_gpu=force_gpu)
            return _tensor_to_python(mattergen_cell_frac_types_fn_collection[fn_name](
                cell,
                frac,
                types,
                num_atoms=torch.tensor([len(types)], device=cell.device),
                **params,
            ))
    return fn


def get_loss_fn(fn_name, force_gpu: int = 0, **params):
    _require_mattergen()
    assert fn_name in LOSS_REGISTRY, f"Loss function: {fn_name} not implemented"

    def fn(entry):
        assert "target" in params, "{target: target_dict} is required for loss calculation"
        clear_globals()
        x = entry2chemgraph(entry, force_gpu=force_gpu)
        call_params = copy.deepcopy(params)
        return _tensor_to_python(LOSS_REGISTRY[fn_name](x, t=None, **call_params))

    return fn
