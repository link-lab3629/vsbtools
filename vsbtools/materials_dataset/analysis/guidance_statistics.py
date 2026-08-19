from __future__ import annotations

import re
import warnings
from pathlib import Path
from typing import Any, Callable, Dict, Mapping, Sequence

import numpy as np

import matplotlib.pyplot as plt
from matplotlib.lines import Line2D
from matplotlib.patches import Patch
from matplotlib.ticker import FuncFormatter

from ..genutils.misc import is_subtree
from ..plotting.formatting import cm2inch
from ..scripts.diffusion_analysis_scripts.pvalue_utils import get_p_value, get_two_proportion_z_test
from .pipeline_legacy import LEGACY_DICTIONARY, LEGACY_INDEX_TO_NAME, LEGACY_NAME_TO_INDEX

try:
    from pymatgen.core import Element as _Element
except ModuleNotFoundError as _pymatgen_error:
    _Element = None
    _PYMATGEN_ERROR = _pymatgen_error

plt.rcParams['xtick.major.pad'] = 4.
plt.rcParams['ytick.major.pad'] = 0.
plt.rcParams['xtick.labelsize'] = 7
plt.rcParams['ytick.labelsize'] = 7

DEFAULT_PLOT_PRIORITY = ['reference', 'Non-guided']
NOT_IMPLEMENTED_LOSSES = ["energy"]
DATASET_NAME_DETAIL_PRIORITY = ['algo', 'batch_size']
TICK_LABEL_SIZE = 10
MIN_VERTICAL_TICKS = 4
MAX_VERTICAL_TICKS = 5

__all__ = [
    "CANONICAL_GUIDANCE_NAMES",
    "CANONICAL_GUIDANCE_TO_TARGET_PROPERTY",
    "CANONICAL_TO_LEGACY_GUIDANCE",
    "DEFAULT_PLOT_PRIORITY",
    "LEGACY_TO_CANONICAL_GUIDANCE",
    "calculate_values",
    "callables_from_ds",
    "canonical_guidance_name",
    "clear_globals",
    "collect_stage_dataset_dict",
    "count_entries_around_target",
    "filter_dataset_dict",
    "fname_friendly_serialize",
    "get_coordination_gen_dirs",
    "get_environment_gen_dirs",
    "get_guidance_generation_dirs",
    "get_loss_fn",
    "get_mean_coordination_gen_dirs",
    "get_p_value",
    "get_target_coordination_gen_dirs",
    "get_target_coordination_share_gen_dirs",
    "get_target_value_fn",
    "get_two_proportion_z_test",
    "get_volume_pa_gen_dirs",
    "guidance_fraction_report",
    "guidance_vs_target_properties",
    "histo_data_collection",
    "load_yaml_recursively",
    "plot_av_env_guidance_results",
    "plot_mean_coordination_guidance_results",
    "plot_multi_kde",
    "plot_multihistogram",
    "plot_volume_pa_guidance_results",
    "plot_volume_pa_results_kde",
    "print_ds_dict_guidance_resume",
    "read",
    "values_2_histo_data",
]
LEGACY_TO_CANONICAL_GUIDANCE = {
    "environment": "mean_coordination",
    "dominant_environment": "target_coordination_share",
    "target_coordination": "target_coordination_share",
}
CANONICAL_TO_LEGACY_GUIDANCE = {
    "mean_coordination": "environment",
    "target_coordination_share": "dominant_environment",
}
CANONICAL_GUIDANCE_NAMES = {
    "mean_coordination",
    "target_coordination_share",
    "volume_pa",
    "energy",
}


def canonical_guidance_name(guidance_name: str) -> str:
    return LEGACY_TO_CANONICAL_GUIDANCE.get(guidance_name, guidance_name)


CANONICAL_GUIDANCE_TO_TARGET_PROPERTY = {
    "mean_coordination": "compute_mean_coordination",
    "target_coordination_share": "compute_target_coordination_share",
    "volume_pa": "volume_pa",
    "energy": "energy",
}
guidance_vs_target_properties = {
    name: CANONICAL_GUIDANCE_TO_TARGET_PROPERTY[canonical_guidance_name(name)]
    for name in (
        "mean_coordination",
        "target_coordination_share",
        "target_coordination",
        "environment",
        "dominant_environment",
        "volume_pa",
        "energy",
    )
}


def _atomic_number(symbol: str) -> int:
    if _Element is None:
        raise RuntimeError(
            "Element symbol conversion requires pymatgen. Install the `materials_dataset` extra."
        ) from _PYMATGEN_ERROR
    return _Element(symbol).Z


def _yaml_csv_poscars_io():
    try:
        from ..io.yaml_csv_poscars import load_yaml_recursively as _load_yaml_recursively
        from ..io.yaml_csv_poscars import read as _read
    except ModuleNotFoundError as exc:
        raise RuntimeError(
            "Dataset manifest loading requires pymatgen. Install the `materials_dataset` extra."
        ) from exc
    return _load_yaml_recursively, _read


def load_yaml_recursively(*args, **kwargs):
    loader, _ = _yaml_csv_poscars_io()
    return loader(*args, **kwargs)


def read(*args, **kwargs):
    _, reader = _yaml_csv_poscars_io()
    return reader(*args, **kwargs)


def fname_friendly_serialize(*args, **kwargs):
    from ..io.mattergen_tools.parsers import fname_friendly_serialize as _serialize

    return _serialize(*args, **kwargs)


def _mattergen_bridge():
    try:
        from ..scripts.diffusion_analysis_scripts import mattergen_bridge
    except ModuleNotFoundError as exc:
        raise RuntimeError(
            "MatterGen target/loss callables require torch and the MatterGen bridge dependencies."
        ) from exc
    return mattergen_bridge


def clear_globals():
    return _mattergen_bridge().clear_globals()


def get_target_value_fn(fn_name, force_gpu: int = 0, **params):
    return _mattergen_bridge().get_target_value_fn(fn_name, force_gpu=force_gpu, **params)


def get_loss_fn(fn_name, force_gpu: int = 0, **params):
    return _mattergen_bridge().get_loss_fn(fn_name, force_gpu=force_gpu, **params)


def callables_from_ds(ds,
                      force_gpu: int = 0,
                      include_losses: bool = True,
                      clear_global_state: bool = True) -> tuple[Dict[str, Callable], Dict[str, Any], str]:
    """
    Build guidance-related callables and corresponding target values from dataset metadata
    (usually parse_raw stage dataset).
    """
    if clear_global_state:
        clear_globals()

    callables = dict()
    targets = dict()
    guidance_descr = ds.metadata['batch_metadata']['guidance']
    guidance_names = list(guidance_descr.keys()) if isinstance(guidance_descr, dict) else [guidance_descr]
    assert len(guidance_names) == 1, "Only one guidance function per generation is supported"
    assert guidance_names[0] is not None, f"Invalid guidance name, check {ds.base_path}"

    guidance_name = guidance_names[0]
    canonical_name = canonical_guidance_name(guidance_name)
    fn_name = CANONICAL_GUIDANCE_TO_TARGET_PROPERTY[canonical_name]
    if canonical_name in ('mean_coordination', 'target_coordination_share'):
        for bond, target in ds.metadata['batch_metadata']['guidance'][guidance_name].items():
            if '-' not in bond:
                continue
            callable_name = bond
            params = dict(zip(('type_A', 'type_B'), [_atomic_number(e) for e in bond.split('-')]))
            if isinstance(target, list) and len(target) == 2:
                params['r_cut'] = target[1]
                callable_name += f"_{target[1]}"
            if canonical_name == "target_coordination_share":
                params['target'] = target[0] if isinstance(target, list) else target
                targets[callable_name] = 1
            else:
                targets[callable_name] = target[0] if isinstance(target, list) else target
            callables[callable_name] = get_target_value_fn(fn_name, force_gpu=force_gpu, **params)
    elif guidance_name == 'volume_pa':
        callables[guidance_name] = get_target_value_fn(fn_name, force_gpu=force_gpu, **{})
        targets[guidance_name] = ds.metadata['batch_metadata']['guidance'][guidance_name]

    if include_losses and guidance_name not in NOT_IMPLEMENTED_LOSSES:
        target = ds.metadata['batch_metadata']['guidance'][guidance_name]
        gl_name = f'loss_{guidance_name}_{fname_friendly_serialize(target, target.keys()) if isinstance(target, dict) else target}'
        callables[gl_name] = get_loss_fn(guidance_name, force_gpu=force_gpu, target=target)
        targets[gl_name] = 0

    return callables, targets, guidance_name


def _guidance_name_variants(guidance_name: str) -> list[str]:
    canonical = canonical_guidance_name(guidance_name)
    variants = [canonical]
    legacy = CANONICAL_TO_LEGACY_GUIDANCE.get(canonical)
    legacy_aliases = [
        old_name for old_name, canonical_name in LEGACY_TO_CANONICAL_GUIDANCE.items()
        if canonical_name == canonical
    ]
    for candidate in (legacy, *legacy_aliases, guidance_name):
        if candidate and candidate not in variants:
            variants.append(candidate)
    return variants


def _guidance_sub_dict_variants(guidance_sub_dict: Dict) -> list[Dict]:
    guidance = guidance_sub_dict.get("guidance")
    if not isinstance(guidance, dict) or len(guidance) != 1:
        return [guidance_sub_dict]
    guidance_name, guidance_value = next(iter(guidance.items()))
    return [{"guidance": {name: guidance_value}} for name in _guidance_name_variants(guidance_name)]


def get_guidance_generation_dirs(processed_repos_root: Path, system: str, guidance_sub_dict: Dict, include_non_guided: bool = True):
    """
    Get a list of directories containing postprocessing pipelines corresponding to a mattergen-generated structures
    with guidance corresponding to the guidance_sub_dict argument.

    Args:
        processed_repos_root: pathlib.Path -- root of processed repositories
        system: str -- dash('-') -separated elements (in any order), e.g. 'Ni-B-H'
        guidance_sub_dict: Dict[str, str|Dict] -- sub-dictionary looked upon in the dataset_info["metadata"]["batch_metadata"]
    Kwargs:
        include_non_guided: bool -- whether the non-guided generation is included
    sub_dict_examples:
        mean_coordination (legacy name: environment): {'guidance': {'mean_coordination': {'mode': 'huber', 'Si-O': 6}}}
        volume_pa: {'guidance': {'volume_pa': 6.8}}
    """
    normalized_system = '-'.join(sorted(system.split('-')))
    search_dir = processed_repos_root / normalized_system
    gen_paths = []
    for gen_path in search_dir.glob(f"{normalized_system}*"):
        for stage_yaml in gen_path.rglob("manifest.yaml"):
            dataset_info = load_yaml_recursively(stage_yaml)
            if dataset_info["metadata"]["pipeline_stage"] in [0, 'parse_raw']:
                break
        else:
            continue
        if (dataset_info["metadata"]["batch_metadata"]["guidance"] == 'None' and include_non_guided) or \
            any(is_subtree(dataset_info["metadata"]["batch_metadata"], variant)
                for variant in _guidance_sub_dict_variants(guidance_sub_dict)):
            gen_paths.append(gen_path)
        continue
    return gen_paths


def get_volume_pa_gen_dirs(processed_repos_root: Path, system: str, guidance_name: str, target: float | int | None = None):
    guidance_sub_dict = {'guidance': {guidance_name: target}}
    return get_guidance_generation_dirs(processed_repos_root, system, guidance_sub_dict=guidance_sub_dict)


def get_coordination_gen_dirs(processed_repos_root: Path, system: str, guidance_name: str = "mean_coordination",
                              bond: str = None, target: float | int | None = None):
    guidance_sub_dict = {'guidance': {guidance_name: {bond: target}}}
    return get_guidance_generation_dirs(processed_repos_root, system, guidance_sub_dict=guidance_sub_dict)


def get_environment_gen_dirs(processed_repos_root: Path, system: str, guidance_name: str = "environment",
                             bond: str = None, target: float | int | None = None):
    return get_coordination_gen_dirs(
        processed_repos_root,
        system,
        guidance_name=guidance_name,
        bond=bond,
        target=target,
    )


def get_mean_coordination_gen_dirs(processed_repos_root: Path, system: str,
                                   bond: str = None, target: float | int | None = None):
    return get_coordination_gen_dirs(
        processed_repos_root,
        system,
        guidance_name="mean_coordination",
        bond=bond,
        target=target,
    )


def get_target_coordination_gen_dirs(processed_repos_root: Path, system: str,
                                     bond: str = None, target: float | int | None = None):
    return get_target_coordination_share_gen_dirs(processed_repos_root, system, bond=bond, target=target)


def get_target_coordination_share_gen_dirs(processed_repos_root: Path, system: str,
                                           bond: str = None, target: float | int | None = None):
    return get_coordination_gen_dirs(
        processed_repos_root,
        system,
        guidance_name="target_coordination_share",
        bond=bond,
        target=target,
    )


def _dataset_base_name_from_bmd(bmd: Dict, add_guid_descr: bool = False) -> str:
    guidance = bmd.get('guidance') if isinstance(bmd, dict) else None
    if guidance in (None, 'None'):
        return 'Non-guided'

    dlw = bmd.get("diffusion_loss_weight", ['', ''])
    if isinstance(dlw, (list, tuple)):
        g = dlw[0] if len(dlw) > 0 else ''
        k = dlw[1] if len(dlw) > 1 else ''
    else:
        g = dlw
        k = ''
    name = f"$g$={g}, $k$={k}"
    if add_guid_descr:
        if isinstance(guidance, dict):
            guid_descr = "_".join(f"{k}_{v}" for k, v in guidance.items())
        else:
            guid_descr = str(guidance)
        name += f", {guid_descr}"
    return name


def _dataset_name(record: dict, detail_keys: list[str]) -> str:
    if not detail_keys:
        return record['base_name']
    details = ", ".join(f"{key}={record['bmd'].get(key, 'NA')}" for key in detail_keys)
    return f"{record['base_name']}, {details}"


def _assign_dataset_names(records: list[dict]) -> list[tuple[str, Any]]:
    records_by_base_name = dict()
    for record in records:
        records_by_base_name.setdefault(record['base_name'], []).append(record)

    named_records = []
    for base_name, same_base_records in records_by_base_name.items():
        detail_keys = []
        names = [_dataset_name(record, detail_keys) for record in same_base_records]
        if len(same_base_records) > 1:
            for detail_key in DATASET_NAME_DETAIL_PRIORITY:
                values = {repr(record['bmd'].get(detail_key, 'NA')) for record in same_base_records}
                if len(values) == 1:
                    continue
                detail_keys.append(detail_key)
                names = [_dataset_name(record, detail_keys) for record in same_base_records]
                if len(set(names)) == len(names):
                    break
            if len(set(names)) != len(names):
                warnings.warn(
                    f"Dataset name collision for {base_name!r} could not be resolved with "
                    f"batch metadata fields {DATASET_NAME_DETAIL_PRIORITY}; adding source suffixes."
                )
                sources = [record['gen_dir'].name for record in same_base_records]
                if len(set(sources)) != len(sources):
                    sources = [f"{source}:{i}" for i, source in enumerate(sources)]
                names = [f"{name}, source={source}" for name, source in zip(names, sources)]

        named_records.extend((name, record['ds']) for name, record in zip(names, same_base_records))
    return named_records


def _stage_values(stage):
    legacy_stage = LEGACY_DICTIONARY.get(stage, stage)
    values = {stage, legacy_stage, LEGACY_NAME_TO_INDEX.get(stage), LEGACY_NAME_TO_INDEX.get(legacy_stage)}
    return {value for value in values if value is not None}


def collect_stage_dataset_dict(gen_dirs, stage, ref_stage, add_guid_descr=False):
    gen_dirs = [Path(gen_dir) for gen_dir in gen_dirs]
    ds_dict = dict()
    if not gen_dirs:
        warnings.warn(f"No generation directories were provided for stage {stage!r}.")
        return ds_dict

    stage_values = _stage_values(stage)
    ref_stage_values = _stage_values(ref_stage)
    for stage_yml in gen_dirs[0].rglob("manifest.yaml"):
        stage_desc = load_yaml_recursively(stage_yml)
        if stage_desc["metadata"]["pipeline_stage"] in ref_stage_values:
            ds_dict["reference"] = read(stage_yml)

    dataset_records = []
    for gen_dir in gen_dirs:
        ds = None
        bmd = None
        for stage_yml in gen_dir.rglob("manifest.yaml"):
            stage_desc = load_yaml_recursively(stage_yml)
            if stage_desc["metadata"]["pipeline_stage"] in stage_values:
                ds = read(stage_yml)
            if stage_desc["metadata"]["pipeline_stage"] in (0, 'parse_raw'):
                bmd = stage_desc["metadata"]["batch_metadata"]

        if ds is None:
            warnings.warn(f"Stage {stage!r} was not found in {gen_dir}")
        if bmd is not None and ds is not None:
            dataset_records.append({
                'base_name': _dataset_base_name_from_bmd(bmd, add_guid_descr=add_guid_descr),
                'bmd': bmd,
                'ds': ds,
                'gen_dir': Path(gen_dir),
            })

    for name, ds in _assign_dataset_names(dataset_records):
        ds_dict[name] = ds
    return ds_dict


def calculate_values(
    ds_dict: Mapping[str, Any],
    callable_name: str | None = None,
    callable_params: Mapping[str, Any] | None = None,
    fn: Callable | None = None,
    filter_max_el: bool = True,
    force_gpu: int = 0,
    **kwargs,
) -> dict[str, np.ndarray]:
    values_dict = {}
    if callable_params is None:
        callable_params = {}
    if fn is None and callable_name:
        predicate = get_target_value_fn(callable_name, force_gpu=force_gpu, **callable_params)
    elif fn is not None and callable_name is None:
        predicate = fn
    else:
        raise RuntimeError("Provide either `fn` or `callable_name`, but not both.")
    for name, ds in ds_dict.items():
        if filter_max_el:
            values_dict[name] = np.array([predicate(entry) for entry in ds if len(entry.composition) == len(ds.elements)])
        else:
            values_dict[name] = np.array([predicate(entry) for entry in ds])
    return values_dict


def count_entries_around_target(
    ds,
    function: Callable,
    target_value: float,
    half_width: float = 0.2,
    profile: str = "rect",
    filter_max_el: bool = False,
    **kwargs,
) -> int:
    if not profile.startswith("rect"):
        raise RuntimeError(f"profile: {profile} not implemented")

    left = target_value - half_width
    right = target_value + half_width

    def is_selected(entry) -> bool:
        if filter_max_el and len(entry.composition) != len(ds.elements):
            return False
        return left <= function(entry) <= right

    return sum(1 for entry in ds if is_selected(entry))


def guidance_fraction_report(
    ds_dict: Mapping[str, Any],
    function: Callable,
    target: float,
    half_width: float,
    filter_max_el: bool = False,
    **kwargs,
) -> dict[str, float]:
    fractions = {}
    for name, ds in ds_dict.items():
        if filter_max_el:
            total = sum(1 for entry in ds if len(entry.composition) == len(ds.elements))
        else:
            total = len(ds)
        if total == 0:
            fractions[name] = np.nan
            continue
        selected = count_entries_around_target(
            ds,
            function,
            target,
            half_width,
            filter_max_el=filter_max_el,
            **kwargs,
        )
        fractions[name] = selected / total
    return fractions


def print_ds_dict_guidance_resume(
    ds_dict: Mapping[str, Any],
    function: Callable,
    target: float,
    half_width: float,
    filter_max_el: bool = False,
    **kwargs,
) -> dict[str, float]:
    fractions = guidance_fraction_report(
        ds_dict,
        function,
        target,
        half_width,
        filter_max_el=filter_max_el,
        **kwargs,
    )
    for name, fraction in fractions.items():
        if np.isnan(fraction):
            fraction_label = "No data"
        else:
            fraction_label = f"{fraction:1%}"
        print(f"{fraction_label} of {name} in ({target:.2f}+/-{half_width:.2f})")
    return fractions


def _matching_labels(labels: Sequence[str], patterns: Sequence[str] | None) -> set[str]:
    if patterns is None:
        return set(labels)
    return {label for label in labels if any(pattern in label for pattern in patterns)}


def filter_dataset_dict(
    ds_dict: Mapping[str, Any],
    skip_labels: Sequence[str] | None = None,
    keep_labels: Sequence[str] | None = None,
) -> dict[str, Any]:
    labels = list(ds_dict.keys())
    skipped = set() if skip_labels is None else _matching_labels(labels, skip_labels)
    kept = set(labels) if keep_labels is None else _matching_labels(labels, keep_labels)

    overlap = skipped & kept
    if skip_labels is not None and keep_labels is not None and overlap:
        warnings.warn(f"skip_labels and keep_labels overlap: {overlap}")

    return {name: ds for name, ds in ds_dict.items() if name in kept - skipped}


def _environment_callable_params_from_parse_raw(gen_dirs, bond: str) -> dict[str, Any]:
    params_by_dir = []
    for gen_dir in gen_dirs:
        for stage_yml in Path(gen_dir).rglob("manifest.yaml"):
            stage_desc = load_yaml_recursively(stage_yml)
            metadata = stage_desc.get("metadata", {})
            if metadata.get("pipeline_stage") not in (0, "parse_raw"):
                continue
            guidance = metadata.get("batch_metadata", {}).get("guidance")
            if not isinstance(guidance, dict):
                continue
            environment_guidance = guidance.get("environment") or guidance.get("mean_coordination")
            if not isinstance(environment_guidance, dict):
                continue
            encoded_target = environment_guidance.get(bond)
            if not isinstance(encoded_target, list) or len(encoded_target) < 2:
                continue
            params_by_dir.append((Path(gen_dir).name, {"r_cut": encoded_target[1]}))

    if not params_by_dir:
        return {}

    unique_params = {tuple(sorted(params.items())) for _, params in params_by_dir}
    if len(unique_params) > 1:
        warnings.warn(f"Multiple {bond} r_cut values found in parse_raw metadata: {params_by_dir}. Using {params_by_dir[0][1]}.")
    return params_by_dir[0][1].copy()


def _format_article_axes(ax, yticks=None, yticklabels=None) -> None:
    ax.tick_params(axis="both", which="major", labelsize=TICK_LABEL_SIZE)

    ymin, ymax = ax.get_ylim()
    if not (np.isfinite(ymin) and np.isfinite(ymax)):
        return

    if ymax <= ymin:
        delta = max(abs(ymin) * 0.01, 1e-6)
        ymin, ymax = ymin - delta, ymax + delta
        ax.set_ylim(ymin, ymax)

    if yticks is not None or yticklabels is not None:
        if yticks is None:
            yticks = ax.get_yticks()
        ax.set_yticks(yticks)
        if yticklabels is not None:
            ax.set_yticklabels(yticklabels)
        return

    n_ticks_target = max(MIN_VERTICAL_TICKS, min(MAX_VERTICAL_TICKS, 5))
    use_percent_scale = (ymin >= -1e-12) and (ymax <= 1.0 + 1e-12)

    if use_percent_scale:
        data_ymax = ax.dataLim.y1 if np.isfinite(ax.dataLim.y1) else ymax
        data_ymin = ax.dataLim.y0 if np.isfinite(ax.dataLim.y0) else ymin

        pmin = 0.0 if data_ymin >= -1e-12 else 100.0 * data_ymin
        pmax_data = max(100.0 * data_ymax, pmin)
        pspan = pmax_data - pmin

        if pspan < 5.0:
            if np.isclose(pspan, 0.0):
                pmax_data = pmin + 1.0
                pspan = 1.0
            pticks = np.linspace(pmin, pmax_data, n_ticks_target)
            decimals = 2 if pspan < 1.0 else 1
            labels = [f"{p:.{decimals}f}".rstrip("0").rstrip(".") for p in pticks]
        else:
            step_candidates = [1, 2, 3, 4, 5, 6, 8, 10, 12, 15, 20, 25, 30, 40, 50]
            best = None

            for step in step_candidates:
                start = 0.0 if pmin >= 0 else np.floor(pmin / step) * step
                top = np.ceil(pmax_data / step) * step
                ticks = np.arange(start, top + 0.5 * step, step)
                n = len(ticks)
                if n < MIN_VERTICAL_TICKS or n > MAX_VERTICAL_TICKS:
                    continue

                overhead = top - pmax_data
                score = (overhead, abs(n - 4), step)
                if best is None or score < best[0]:
                    best = (score, ticks)

            if best is None:
                pticks = np.linspace(pmin, pmax_data, n_ticks_target)
                pticks = np.unique(np.round(pticks))
                if len(pticks) < MIN_VERTICAL_TICKS:
                    pticks = np.arange(0, MIN_VERTICAL_TICKS, 1.0)
            else:
                pticks = best[1]

            labels = [f"{int(round(p))}" for p in pticks]

        yticks = pticks / 100.0
        ax.set_yticks(yticks)
        ax.set_ylim(yticks[0], yticks[-1])
        labels[-1] = "%"
        ax.set_yticklabels(labels)
    else:
        yticks = np.linspace(ymin, ymax, n_ticks_target)
        ax.set_yticks(yticks)


def _format_density_axes(ax) -> None:
    ax.tick_params(axis="both", which="major", labelsize=TICK_LABEL_SIZE)

    ymin, ymax = ax.get_ylim()
    if not (np.isfinite(ymin) and np.isfinite(ymax)):
        return

    data_ymax = ax.dataLim.y1 if np.isfinite(ax.dataLim.y1) else ymax
    top = max(ymax, data_ymax, 0.0)
    if top <= 0.0:
        top = 1e-3

    lower_pad = 0.06 * top
    ax.set_ylim(-lower_pad, top)

    step_candidates = []
    for exp in range(-2, 4):
        scale = 10.0 ** exp
        for multiplier in (1.0, 2.0, 5.0):
            step_candidates.append(multiplier * scale)
    step_candidates = sorted(set(step_candidates))

    best_ticks = None
    best_score = None
    for step in step_candidates:
        top_tick = np.ceil(top / step) * step
        ticks = np.arange(0.0, top_tick + 0.5 * step, step)
        n = len(ticks)
        if n < MIN_VERTICAL_TICKS or n > MAX_VERTICAL_TICKS:
            continue

        overhead = top_tick - top
        score = (overhead, abs(n - 4), step)
        if best_score is None or score < best_score:
            best_score = score
            best_ticks = ticks

    if best_ticks is None:
        step = 0.01
        top_tick = max(np.ceil(top / step) * step, step * (MIN_VERTICAL_TICKS - 1))
        best_ticks = np.arange(0.0, top_tick + 0.5 * step, step)

    best_ticks = np.round(best_ticks, 12)
    ax.set_yticks(best_ticks)

    lower_pad_final = 0.06 * float(best_ticks[-1])
    ax.set_ylim(-lower_pad_final, float(best_ticks[-1]))
    ax.yaxis.set_major_formatter(FuncFormatter(lambda y, _: f"{y:.2f}".rstrip("0").rstrip(".")))


def _save_current_figure(ds_dict: Mapping[str, Any], filename: str) -> None:
    if not ds_dict:
        warnings.warn(f"Cannot save {filename!r}: dataset dictionary is empty.")
        return

    fig_base = None
    for ds in ds_dict.values():
        base_path = getattr(ds, "base_path", None)
        if base_path is not None:
            fig_base = Path(base_path).parents[1]
            break
    if fig_base is None:
        warnings.warn(f"Cannot save {filename!r}: datasets do not expose base_path.")
        return

    ax = plt.gca()
    legend = ax.get_legend()
    extra_artists = [legend] if legend is not None else None
    plt.savefig(
        fig_base / filename,
        bbox_inches="tight",
        pad_inches=0.1,
        bbox_extra_artists=extra_artists,
    )


def values_2_histo_data(values, name=None, bin_centers=None, bins=None, integer_bins=True, n_bins=10, norm=True, **kwargs):
    values = np.asarray(values, dtype=float)
    if values.size == 0:
        return bin_centers, None

    if bin_centers is None:
        if bins is not None:
            warnings.warn("bin_centers will be calculated automatically, provided bins will be discarded")
            bins = None
        if integer_bins:
            bin_centers = np.arange(np.floor(values.min()), np.ceil(values.max()) + 1)
        else:
            bin_centers = np.linspace(values.min(), values.max(), n_bins)

    if bins is None:
        half_shift = 0.5 * (bin_centers[1] - bin_centers[0]) if len(bin_centers) > 1 else 0.5
        bins = np.hstack((bin_centers - half_shift, [bin_centers[-1] + half_shift]))
        if bins[0] > values.min():
            warnings.warn(f"Dataset {name}: values outside leftmost bin edge ({values[values < bins[0]]})")
        if bins[-1] < values.max():
            warnings.warn(f"Dataset {name}: values outside rightmost bin edge ({values[values > bins[-1]]})")

    # cap by max_bincenter but keep an overflow bin
    counts, _ = np.histogram(values, bins=bins)
    if norm:
        total = counts.sum()
        counts = counts / total if total else counts
    return bin_centers, counts


def histo_data_collection(ds_dict, callable_name, callable_params=None, auto_adjust_bins=False, n_bins=None,
                          force_gpu: int = 0, filter_max_el: bool = True, **kwargs):
    """
    Returns list of dictionaries: [{'label': str, 'bin_centers': iterable[floats], 'counts': iterable[floats]}]
    """
    histo_collection = []
    values_dict = calculate_values(
        ds_dict,
        callable_name,
        callable_params=callable_params,
        filter_max_el=filter_max_el,
        force_gpu=force_gpu,
    )
    if auto_adjust_bins:
        non_empty_values = [values for values in values_dict.values() if len(values) > 0]
        if non_empty_values:
            n_bins = 10 if n_bins is None else n_bins
            extremities = np.unique(np.concatenate([np.asarray([v.min(), v.max()]) for v in non_empty_values]))
            bin_centers = np.linspace(extremities.min(), extremities.max(), n_bins)
            shift = (bin_centers[1] - bin_centers[0]) if len(bin_centers) > 1 else 1.0
            bins = np.hstack((bin_centers - shift, [bin_centers[-1] + shift]))
            kwargs['bins'] = bins
            kwargs['bin_centers'] = bin_centers
    for name, values in values_dict.items():
        if len(values) > 0:
            hist_data = dict(zip(("bin_centers", "counts"), values_2_histo_data(values, name, **kwargs)))
            hist_data['label'] = name
        else:
            hist_data = {'label': name, "bin_centers": None, "counts": None}
        histo_collection.append(hist_data)
    return histo_collection


def plot_multihistogram(multidata, target=None, title='', max_bincenter=None,
                        show_gaussian=False, gaussian_fill_alpha=0.2, gaussian_edge_lw=2.5,
                        apply_standard_order=True,
                        custom_priority=None,
                        group_width=0.8,
                        shift_xticks=True,
                        print_mu=False,
                        simplified_legend=False,
                        **kwargs):
    """
    Plot side-by-side histograms for multidata:
    multidata:: list of dicts:
      {'label': str, 'bin_centers': iterable[float] | None, 'counts': iterable[float] | None}

    Missing datasets (bin_centers or counts is None) are still shown in the legend
    using proxy handles with the intended color.

    Color grouping:
      Labels matching any of special_label_patterns use special_cmap; others use other_cmap.
      (Configured via kwargs; see below.)
    """

    special_label_patterns = kwargs.pop("special_label_patterns", ("Non-guided", "reference"))
    special_cmap_name = kwargs.pop("special_cmap", "berlin_r")
    other_cmap_name = kwargs.pop("other_cmap", "berlin")
    pattern_case_sensitive = kwargs.pop("pattern_case_sensitive", False)
    missing_suffix = kwargs.pop("missing_suffix", ": No data")
    bar_kwargs = kwargs.pop("bar_kwargs", {})
    legend_kwargs = kwargs.pop("legend_kwargs", {})
    ncolor = kwargs.pop("ncolor", 4)

    def sort_key_with_priority(item):
        priority = DEFAULT_PLOT_PRIORITY if custom_priority is None else custom_priority
        order = {lab: i for i, lab in enumerate(priority)}
        label = item.get("label")
        if label in order:
            return 0, order[label]
        return 1, 0

    if apply_standard_order:
        multidata = sorted(multidata, key=sort_key_with_priority)

    flags = 0 if pattern_case_sensitive else re.IGNORECASE
    pattern = "|".join(re.escape(p) for p in special_label_patterns if p)
    special_re = re.compile(pattern, flags=flags) if pattern else None

    def is_special(label):
        return special_re is not None and special_re.search(label or "") is not None

    special_indices = [i for i, d in enumerate(multidata) if is_special(d.get("label", ""))]
    special_set = set(special_indices)
    other_indices = [i for i in range(len(multidata)) if i not in special_set]

    def discrete_palette(cmap, n=ncolor):
        return [cmap(k / n) for k in range(n)]

    pal_special = discrete_palette(plt.get_cmap(special_cmap_name), ncolor)
    pal_other = discrete_palette(plt.get_cmap(other_cmap_name), ncolor)
    colors = [None] * len(multidata)
    for k, i in enumerate(special_indices):
        colors[i] = pal_special[k % ncolor]
    for k, i in enumerate(other_indices):
        colors[i] = pal_other[k % ncolor]

    valid_indices = []
    for i, d in enumerate(multidata):
        bc = d.get("bin_centers")
        ct = d.get("counts")
        if bc is None or ct is None:
            continue
        if np.asarray(bc, dtype=float).size == 0 or np.asarray(ct, dtype=float).size == 0:
            continue
        valid_indices.append(i)

    fig, ax = plt.subplots(figsize=cm2inch((8.1, 10)))
    legend_handles, legend_labels = [], []

    def add_missing_dataset_legend(i):
        label = multidata[i].get("label", f"#{i}")
        legend_handles.append(Patch(facecolor=colors[i], edgecolor='black', alpha=0.8))
        legend_labels.append(f"{label}{missing_suffix}" if missing_suffix else label)

    def finalize_and_return():
        if title:
            ax.set_title(title)
        if not legend_kwargs.get("loc", False):
            legend_kwargs["loc"] = "upper left"
        if simplified_legend:
            guid_idx = None
            if len(other_indices) == 1:
                for i, l in enumerate(legend_labels):
                    if '$=' in l:
                        guid_idx = i
            if guid_idx is not None:
                legend_labels[guid_idx] = 'Guided'

        ax.legend(legend_handles, legend_labels, fontsize='small', **legend_kwargs)
        fig.tight_layout()
        return fig, ax

    if not valid_indices:
        for i, d in enumerate(multidata):
            add_missing_dataset_legend(i)
        return finalize_and_return()

    max_center = np.inf if max_bincenter is None else float(max_bincenter)
    first_bc = np.asarray(multidata[valid_indices[0]]["bin_centers"], dtype=float)
    delta = float(first_bc[1] - first_bc[0]) if first_bc.size >= 2 else 1.0
    delta = 1.0 if delta == 0 else delta

    index_to_position = {idx: pos for pos, idx in enumerate(valid_indices)}
    n_valid = len(valid_indices)
    width = group_width * delta / max(n_valid, 1)
    offsets = np.linspace(-0.5 * group_width * delta + width / 2, 0.5 * group_width * delta - width / 2, n_valid)

    all_bincenters = np.unique(np.concatenate([
        np.asarray(multidata[i]["bin_centers"], dtype=float) for i in valid_indices
    ]))
    all_bincenters = all_bincenters[np.isfinite(all_bincenters)]
    all_bincenters.sort()
    all_bincenters = all_bincenters[all_bincenters <= max_center]

    if all_bincenters.size == 0:
        for i in range(len(multidata)):
            add_missing_dataset_legend(i)
        if "loc" not in legend_kwargs:
            legend_kwargs["loc"] = "upper left"
        return finalize_and_return()

    x_min, x_max = all_bincenters.min() - 0.5 * delta, all_bincenters.max() + 0.5 * delta
    x_line = np.linspace(x_min, x_max, 800)
    last_tick_with_plus = False

    for i, dataset in enumerate(multidata):
        label = dataset.get("label", f"#{i}")
        color = colors[i]

        if i not in index_to_position:
            add_missing_dataset_legend(i)
            continue

        pos = index_to_position[i]
        bin_centers = np.asarray(dataset["bin_centers"], dtype=float)
        counts_raw = np.asarray(dataset["counts"], dtype=float)

        if np.isfinite(max_center) and bin_centers.size > 0 and max_center <= bin_centers.max():
            mask = bin_centers <= max_center
            if np.any(mask):
                extra = counts_raw[~mask]
                bin_centers = bin_centers[mask]
                counts_raw = counts_raw[mask]
                if extra.size > 0:
                    counts_raw[-1] += extra.sum()
                    last_tick_with_plus = True
            else:
                add_missing_dataset_legend(i)
                continue

        total = counts_raw.sum()
        counts = counts_raw / total if total > 0 else counts_raw
        mu = float(np.sum(bin_centers * counts)) if counts.sum() > 0 else float("nan")

        bars = ax.bar(
            bin_centers + offsets[pos], counts, width=width,
            align="center",
            edgecolor="black", linewidth=0.5,
            color=color, alpha=0.8, zorder=2, label="_nolegend_",
            **bar_kwargs
        )
        legend_handles.append(bars[0])
        if print_mu and np.isfinite(mu):
            legend_labels.append(f"{label}, $\\mu$={mu:.2f}")
        else:
            legend_labels.append(label)

        if show_gaussian and counts.sum() > 0:
            var = float(np.sum((bin_centers - mu) ** 2 * counts))
            sigma = float(np.sqrt(max(var, 0.0)))

            if sigma > 0:
                y = (1.0 / (sigma * np.sqrt(2*np.pi))) * np.exp(-0.5 * ((x_line - mu) / sigma) ** 2)
                ax.fill_between(
                    x_line, y, 0,
                    facecolor=color, edgecolor="none",
                    alpha=gaussian_fill_alpha, zorder=1, label="_nolegend_"
                )
                ax.plot(
                    x_line, y,
                    color=color, linewidth=gaussian_edge_lw,
                    alpha=1.0, zorder=3, label="_nolegend_"
                )
            else:
                eps = 0.15
                ax.axvspan(mu - eps, mu + eps, facecolor=color, edgecolor="none",
                           alpha=gaussian_fill_alpha, zorder=1, label="_nolegend_")
                ax.axvline(mu, color=color, linewidth=gaussian_edge_lw,
                           alpha=1.0, zorder=3, label="_nolegend_")

    if target is not None and all_bincenters.min() <= target <= all_bincenters.max():
        span = ax.axvspan(target - 0.5 * delta, target + 0.5 * delta,
                          color="#4287f5", alpha=0.3, zorder=0)
        legend_handles.append(span)
        legend_labels.append(f"Target={target}")

    are_integer_ticks = np.all(np.isclose(all_bincenters, np.round(all_bincenters)))
    xtick_labels = [f"{int(x)}" for x in all_bincenters] if are_integer_ticks else \
        [f"{x:.2f}".rstrip('0').rstrip('.') for x in all_bincenters]
    if last_tick_with_plus and xtick_labels:
        xtick_labels[-1] += "+"

    current_yticks = ax.get_yticks()
    current_yticks = current_yticks[(current_yticks <= 1.0) | (current_yticks == max(current_yticks))]
    ytick_labels = [f"{y * 100:.0f}" for y in current_yticks]
    max_tick_idx = int(np.argmax(current_yticks))
    ytick_labels[max_tick_idx] = '%'

    ax.set_xticks(all_bincenters)
    ax.set_xticklabels(xtick_labels)
    ax.set_yticks(current_yticks)
    ax.set_yticklabels(ytick_labels)

    if shift_xticks and len(all_bincenters) > 1:
        xt = ax.get_xticks()
        mid = 0.5 * (xt[:-1] + xt[1:])
        ax.set_xticks(xt)
        ax.tick_params(axis='x', which='major', length=0)
        ax.set_xticks(mid, minor=True)
        ax.tick_params(axis='x', which='minor', length=6)

    return finalize_and_return()


def plot_multi_kde(values_dict, target=None, title='', max_value=None,
                   bandwidth=None, grid_size=800,
                   kde_fill_alpha=0.2, kde_edge_lw=2.5,
                   apply_standard_order=True,
                   custom_priority=None,
                   kernel=None,
                   print_mu=False,
                   simplified_legend=False,
                   **kwargs):
    """
    Plot KDE-smoothed curves (sum of Gaussian kernels over values) for each item in values_dict.

    values_dict: dict[str, iterable[float]]
      - each key is the dataset label
      - each value is raw scalar samples
    """
    special_label_patterns = kwargs.pop("special_label_patterns", ("Non-guided", "reference"))
    special_cmap_name = kwargs.pop("special_cmap", "berlin_r")
    other_cmap_name = kwargs.pop("other_cmap", "berlin")
    pattern_case_sensitive = kwargs.pop("pattern_case_sensitive", False)
    missing_suffix = kwargs.pop("missing_suffix", ": No data")
    legend_kwargs = kwargs.pop("legend_kwargs", {})
    ncolor = kwargs.pop("ncolor", 4)
    legacy_max = kwargs.pop("max_bincenter", None)
    if legacy_max is not None:
        warnings.warn("`max_bincenter` is deprecated for KDE; use `max_value`.", DeprecationWarning)
        if max_value is None:
            max_value = legacy_max

    def gaussian_kernel(u):
        return np.exp(-0.5 * u * u) / np.sqrt(2.0 * np.pi)

    kernel_fn = gaussian_kernel if kernel is None else kernel

    multidata = [{"label": label, "values": values} for label, values in values_dict.items()]

    if apply_standard_order:
        priority = DEFAULT_PLOT_PRIORITY if custom_priority is None else custom_priority
        order = {lab: i for i, lab in enumerate(priority)}

        def sort_key(d):
            lab = d.get("label")
            if lab in order:
                return 0, order[lab]
            return 1, 0

        multidata = sorted(multidata, key=sort_key)

    flags = 0 if pattern_case_sensitive else re.IGNORECASE
    pat = "|".join(re.escape(p) for p in special_label_patterns if p)
    special_re = re.compile(pat, flags=flags) if pat else None

    def is_special(label: str) -> bool:
        if special_re is None:
            return False
        return special_re.search(label or "") is not None

    special_idx = [i for i, d in enumerate(multidata) if is_special(d.get("label", ""))]
    special_set = set(special_idx)
    other_idx = [i for i in range(len(multidata)) if i not in special_set]

    def discrete_palette(cmap, n=ncolor):
        return [cmap(k / n) for k in range(n)]

    pal_special = discrete_palette(plt.get_cmap(special_cmap_name), ncolor)
    pal_other = discrete_palette(plt.get_cmap(other_cmap_name), ncolor)

    color_list = [None] * len(multidata)
    for k, i in enumerate(special_idx):
        color_list[i] = pal_special[k % ncolor]
    for k, i in enumerate(other_idx):
        color_list[i] = pal_other[k % ncolor]

    processed = []
    max_val = np.inf if max_value is None else float(max_value)
    for i, d in enumerate(multidata):
        vals = np.asarray(d.get("values", []), dtype=float)
        vals = vals[np.isfinite(vals)]
        if np.isfinite(max_val):
            vals = vals[vals <= max_val]
        processed.append(vals)

    keep = [i for i, vals in enumerate(processed) if vals.size > 0]

    fig, ax = plt.subplots(figsize=cm2inch((8.1, 10)))
    legend_handles, legend_labels = [], []

    if len(keep) == 0:
        for i, d in enumerate(multidata):
            label = d.get("label", f"#{i}")
            color = color_list[i]
            legend_handles.append(Patch(facecolor=color, edgecolor='black', alpha=0.8))
            legend_labels.append(f"{label}{missing_suffix}" if missing_suffix else label)
        if title:
            ax.set_title(title)
        if not legend_kwargs.get("loc", False):
            legend_kwargs["loc"] = "upper left"
        ax.legend(legend_handles, legend_labels, fontsize='small', **legend_kwargs)
        fig.tight_layout()
        return fig, ax

    all_values = np.concatenate([processed[i] for i in keep])
    x_min = float(all_values.min())
    x_max = float(all_values.max())
    if target is not None:
        x_min = min(x_min, float(target))
        x_max = max(x_max, float(target))
    if x_max == x_min:
        x_min -= 0.5
        x_max += 0.5
    x_pad = 0.1 * (x_max - x_min)
    x_line = np.linspace(x_min - x_pad, x_max + x_pad, int(grid_size))

    for i, dataset in enumerate(multidata):
        label = dataset.get("label", f"#{i}")
        color = color_list[i]
        vals = processed[i]

        if vals.size == 0:
            legend_handles.append(Patch(facecolor=color, edgecolor='black', alpha=0.8))
            legend_labels.append(f"{label}{missing_suffix}" if missing_suffix else label)
            continue

        n = vals.size
        sigma = float(np.std(vals, ddof=1)) if n > 1 else 0.0
        q75, q25 = np.percentile(vals, [75, 25])
        iqr = float(q75 - q25)
        scale = sigma
        if iqr > 0:
            scale = min(sigma, iqr / 1.34) if sigma > 0 else iqr / 1.34
        if scale <= 0:
            data_span = float(np.max(vals) - np.min(vals))
            scale = data_span / 10.0 if data_span > 0 else 1.0
        bw = float(bandwidth) if bandwidth is not None else 0.9 * scale * (n ** (-1.0 / 5.0))
        bw = max(bw, 1e-8)

        z = (x_line[:, None] - vals[None, :]) / bw
        kernel_vals = np.asarray(kernel_fn(z), dtype=float)
        if kernel_vals.shape != z.shape:
            raise ValueError("`kernel` must support array input and return an array of the same shape.")
        density = kernel_vals.sum(axis=1) / (n * bw)

        ax.fill_between(
            x_line, density, 0,
            facecolor=color, edgecolor="none",
            alpha=kde_fill_alpha, zorder=1, label="_nolegend_"
        )
        line, = ax.plot(
            x_line, density,
            color=color, linewidth=kde_edge_lw,
            alpha=1.0, zorder=2, label="_nolegend_"
        )

        legend_handles.append(line)
        if print_mu:
            mu = float(np.mean(vals))
            legend_labels.append(f"{label}, $\\mu$={mu:.2f}")
        else:
            legend_labels.append(label)

    if target is not None:
        ymax = ax.get_ylim()[1]
        target_line = ax.vlines(target, ymin=0.0, ymax=ymax, color="#424242", alpha=0.8, linewidth=2.0, zorder=0)
        legend_handles.append(Line2D([0], [0], color=target_line.get_colors()[0], linewidth=target_line.get_linewidths()[0]))
        legend_labels.append(f"Target={target}")

    if title:
        ax.set_title(title)
    if not legend_kwargs.get("loc", False):
        legend_kwargs["loc"] = "upper left"
    if simplified_legend:
        guided_count = 0
        for i in range(len(legend_labels)):
            if '$=' in legend_labels[i]:
                legend_labels[i] = 'Guided' if guided_count == 0 else f'Guided({guided_count})'
                guided_count += 1
    ax.legend(legend_handles, legend_labels, fontsize='small', **legend_kwargs)
    fig.tight_layout()
    return fig, ax


def plot_av_env_guidance_results(
    processed_path: Path | str,
    system: str,
    bond: str,
    target: float,
    stage: str = "check_min_dist",
    skip_ds: Sequence[str] | None = None,
    keep_ds: Sequence[str] | None = None,
    save: bool = True,
    square_box: bool = True,
    filter_max_el: bool = False,
    other_callable_params: Mapping[str, Any] | None = None,
    yticks=None,
    yticklabels=None,
    guidance_name: str = "environment",
    ref_stage: str = "poll_db",
    force_gpu: int = 0,
    **kwargs,
) -> dict[str, float]:
    gen_dirs = get_environment_gen_dirs(
        Path(processed_path),
        system,
        guidance_name=guidance_name,
        bond=bond,
        target=target,
    )
    ds_dict = collect_stage_dataset_dict(gen_dirs, stage=stage, ref_stage=ref_stage)
    ds_dict = filter_dataset_dict(ds_dict, skip_labels=skip_ds, keep_labels=keep_ds)

    type_A, type_B = (_atomic_number(el) for el in bond.split("-"))
    callable_name = "compute_mean_coordination"
    callable_params = {
        "type_A": type_A,
        "type_B": type_B,
        **_environment_callable_params_from_parse_raw(gen_dirs, bond),
    }
    if other_callable_params:
        callable_params.update(other_callable_params)

    hist_data = histo_data_collection(
        ds_dict,
        callable_name=callable_name,
        callable_params=callable_params,
        filter_max_el=filter_max_el,
        force_gpu=force_gpu,
        **kwargs,
    )
    plot_multihistogram(
        multidata=hist_data,
        target=target,
        legend_kwargs={"labelspacing": 0.2, "loc": "upper center", "bbox_to_anchor": (0.5, -0.12)},
        simplified_legend=True,
        **kwargs,
    )
    function = get_target_value_fn(callable_name, force_gpu=force_gpu, **callable_params)
    fractions = print_ds_dict_guidance_resume(
        ds_dict,
        function,
        target=target,
        filter_max_el=filter_max_el,
        half_width=kwargs.get("half_width", 0.5),
    )

    ax = plt.gca()
    ax.set_xlabel(f"{bond} CN")
    if square_box:
        ax.set_box_aspect(1)
    _format_article_axes(ax, yticks=yticks, yticklabels=yticklabels)

    if save or kwargs.get("save", False):
        prefix = "" if filter_max_el else "no_filter_"
        _save_current_figure(ds_dict, f"{prefix}hist_env_{bond}_{target}_{stage}_{len(ds_dict)}_el.pdf")
    return fractions


def plot_mean_coordination_guidance_results(*args, **kwargs) -> dict[str, float]:
    kwargs.setdefault("guidance_name", "mean_coordination")
    return plot_av_env_guidance_results(*args, **kwargs)


def plot_volume_pa_guidance_results(
    processed_path: Path | str,
    system: str,
    target: float,
    stage: str = "symmetrize_raw",
    show_gaussian: bool = True,
    skip_ds: Sequence[str] | None = None,
    keep_ds: Sequence[str] | None = None,
    half_width: float = 0.1,
    save: bool = True,
    square_box: bool = True,
    ref_stage: str = "poll_db",
    force_gpu: int = 0,
    **kwargs,
) -> dict[str, float]:
    callable_name = "volume_pa"
    gen_dirs = get_volume_pa_gen_dirs(Path(processed_path), system, callable_name, target=target)
    ds_dict = collect_stage_dataset_dict(gen_dirs, stage, ref_stage=ref_stage)
    ds_dict = filter_dataset_dict(ds_dict, skip_labels=skip_ds, keep_labels=keep_ds)

    plot_kwargs = dict(kwargs)
    n_bins = plot_kwargs.pop("n_bins", 10)
    hist_data = histo_data_collection(
        ds_dict,
        callable_name=callable_name,
        callable_params={},
        n_bins=n_bins,
        integer_bins=False,
        force_gpu=force_gpu,
        **plot_kwargs,
    )
    plot_multihistogram(
        multidata=hist_data,
        target=target,
        show_gaussian=show_gaussian,
        legend_kwargs={"labelspacing": 0.2, "loc": "upper center", "bbox_to_anchor": (0.5, -0.21)},
        **plot_kwargs,
    )

    function = get_target_value_fn(callable_name, force_gpu=force_gpu)
    fractions = print_ds_dict_guidance_resume(ds_dict, function, target=target, half_width=half_width)

    ax = plt.gca()
    ax.set_xlabel(r"$v_\mathrm{a}/\mathrm{\AA}^3$")
    ax.set_ylim((0, 1))
    if square_box:
        ax.set_box_aspect(1)
    _format_article_axes(ax)

    if save or kwargs.get("save", False):
        _save_current_figure(ds_dict, f"hist_vol_pa_{target}_{stage}_{len(ds_dict)}_el.pdf")
    return fractions


def plot_volume_pa_results_kde(
    processed_path: Path | str,
    system: str,
    target: float,
    max_value: float | None = None,
    stage: str = "symmetrize_raw",
    skip_ds: Sequence[str] | None = None,
    keep_ds: Sequence[str] | None = None,
    save: bool = True,
    square_box: bool = True,
    ref_stage: str = "poll_db",
    force_gpu: int = 0,
    **kwargs,
) -> tuple:
    callable_name = "volume_pa"
    gen_dirs = get_volume_pa_gen_dirs(Path(processed_path), system, callable_name, target=target)
    ds_dict = collect_stage_dataset_dict(gen_dirs, stage, ref_stage=ref_stage)
    ds_dict = filter_dataset_dict(ds_dict, skip_labels=skip_ds, keep_labels=keep_ds)

    values_dict = calculate_values(ds_dict, callable_name=callable_name, force_gpu=force_gpu)
    plot_kwargs = dict(kwargs)
    plot_kwargs.setdefault("other_cmap", "tab20c")
    plot_kwargs.setdefault("simplified_legend", True)
    fig, ax = plot_multi_kde(values_dict=values_dict, target=target, max_value=max_value, **plot_kwargs)

    ax.set_xlabel(r"$v_\mathrm{a}/\mathrm{\AA}^3$")
    if square_box:
        ax.set_box_aspect(1)
    _format_density_axes(ax)
    ax.grid(True)

    if save or kwargs.get("save", False):
        _save_current_figure(ds_dict, f"kde_vol_pa_{target}_{stage}_{len(ds_dict)}_el.pdf")
    return fig, ax
