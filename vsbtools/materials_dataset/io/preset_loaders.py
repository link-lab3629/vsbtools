from pathlib import Path
import json
import hashlib
import sys
from typing import Callable, Any, Dict
import pandas as pd
from ..cache_paths import database_cache_dir, safe_cache_component
from ..io.yaml_csv_poscars import read, write
from ..converters import df2ds
from .sources.matproj_parser import MPClient
from .sources.alexandria_parser import AlexandriaClient
from .sources.oqmd_parser import OQMDClient
from .sources.optimade_parser import OptimadeClient
from .sources.structure_and_energy_files_reader import CSV_and_POSCARS_client

mp_client = MPClient()
oqmd_client = OQMDClient()
CACHE_DIR = database_cache_dir()
LOADER_CACHE_SCHEMA_VERSION = 2
_RED = "\033[1;31m"
_RESET = "\033[0m"


# --------------------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------------------
def _normalize_elements(elements) -> str:
    """
    Canonical, hyphen-joined (sorted) element key.
    E.g., 'Si-O', ['O','Si'] -> 'O-Si'
    """
    if isinstance(elements, str):
        s = elements.strip().replace(",", "-").replace("_", "-")
        parts = [t for t in s.split("-") if t]
    else:
        try:
            parts = [str(x).strip() for x in elements]
        except TypeError:
            parts = [str(elements)]
    parts = sorted({p for p in parts if p})
    return "-".join(parts) if parts else "UNSPEC"

def _kwargs_hash(kwargs: Dict[str, Any]) -> str:
    """
    Stable short hash of kwargs, excluding non-semantic controls.
    """
    filtered = {
        k: v
        for k, v in kwargs.items()
        if k not in (
            "force_refresh",
            "message",
            "per_provider_cache",
            "force_provider_refresh",
            "cache_label",
            "show_progress",
            "progress_provider_no",
            "progress_total_providers",
        )
    }
    filtered["loader_cache_schema_version"] = LOADER_CACHE_SCHEMA_VERSION
    payload = json.dumps(filtered, sort_keys=True, default=repr).encode("utf-8")
    return hashlib.sha1(payload).hexdigest()[:10]


# --------------------------------------------------------------------------------------
# Decorator: uses your read(dir/manifest.yaml) and write(dataset, enforce_base_path=dir, ...)
# --------------------------------------------------------------------------------------
def cache_loader(read_fn, write_fn, *, cache_root: Path = CACHE_DIR, manifest_name: str = "manifest.yaml"):
    """
    Decorator for loaders returning a CrystalDataset.
    - read_fn(manifest_path: str) -> CrystalDataset
    - write_fn(dataset: CrystalDataset, enforce_base_path: str|Path|None = None, comment=None, **kwargs) -> None

    Special kwarg on wrapped loader:
      force_refresh=True -> bypass cache
    """
    def decorator(fn):
        source = fn.__name__.split("load_from_", 1)[-1] if "load_from_" in fn.__name__ else fn.__name__

        def wrapper(elements, message=None, **kwargs):
            force_refresh = bool(kwargs.get("force_refresh", False))
            cache_label = kwargs.get("cache_label")
            elements_key = _normalize_elements(elements)
            kw_hash = _kwargs_hash(kwargs)
            folder_name = safe_cache_component(
                f"{cache_label or source}_{elements_key}_{kw_hash}",
                max_length=120,
            )
            folder = Path(cache_root) / folder_name
            manifest_path = folder / manifest_name

            # 1) Try cache
            if not force_refresh and manifest_path.exists():
                return read_fn(str(manifest_path))

            # 2) Miss: compute dataset via underlying loader
            #    (Do not pass control-only kwarg to the client)
            client_kwargs = {k: v for k, v in kwargs.items() if k not in ("force_refresh", "cache_label")}
            if source == "optimade" and force_refresh:
                client_kwargs["force_provider_refresh"] = True
            dataset = fn(elements, message=message, **client_kwargs)

            # 3) Persist using your writer into the cache folder
            folder.mkdir(parents=True, exist_ok=True)
            write_fn(dataset, enforce_base_path=folder, comment=message)

            return dataset

        wrapper.__name__  = fn.__name__
        wrapper.__doc__   = fn.__doc__
        wrapper.__module__= fn.__module__
        wrapper.__wrapped__ = fn
        return wrapper
    return decorator


@cache_loader(read, write)
def load_from_materials_project(elements, message=None, **kwargs):
    api_key = kwargs.pop("api_key", None)
    client = mp_client if api_key is None else MPClient(api_key=api_key)
    df = client.query(elements)
    message = message or f"Full {elements} system from Materials Project"
    return df2ds(df, message=message)

@cache_loader(read, write)
def load_from_alexandria(elements, message=None, **kwargs):
    alex_client = AlexandriaClient(**kwargs)
    df = alex_client.query(elements)
    message = message or f"Full {elements} system from Alexandria database"
    return df2ds(df, message=message)

@cache_loader(read, write)
def load_from_oqmd(elements, message=None, **kwargs):
    df = oqmd_client.query(elements)
    message = message or f"Full {elements} system from OQMD"
    return df2ds(df, message=message)

@cache_loader(read, write)
def load_from_optimade(elements, message=None, **kwargs):
    per_provider_cache = kwargs.pop("per_provider_cache", True)
    force_provider_refresh = kwargs.pop("force_provider_refresh", False)
    if not per_provider_cache:
        try:
            optimade_client = OptimadeClient(**kwargs)
            df = optimade_client.query(elements)
            if df.empty:
                provider_names = _optimade_provider_names(kwargs)
                raise RuntimeError(
                    f"OPTIMADE provider '{provider_names[0]}' returned no usable entries"
                )
        except RuntimeError as err:
            provider_names = _optimade_provider_names(kwargs)
            if len(provider_names) != 1:
                raise
            return _load_from_optimade_fallback_provider(
                elements,
                provider_names[0],
                err,
                message=message,
            )
        message = message or f"Full {elements} system from OPTIMADE"
        return df2ds(df, message=message)

    provider_names = _optimade_provider_names(kwargs)
    provider_datasets = []
    fallback_trigger = None
    for provider_no, provider_name in enumerate(provider_names, start=1):
        provider_kwargs = dict(kwargs)
        provider_kwargs["providers"] = [provider_name]
        provider_kwargs["do_deduplication"] = False
        provider_kwargs["cache_label"] = f"optimade_{provider_name}"
        provider_kwargs["force_refresh"] = force_provider_refresh
        provider_kwargs["progress_provider_no"] = provider_no
        provider_kwargs["progress_total_providers"] = len(provider_names)
        provider_message = f"Full {elements} system from OPTIMADE provider {provider_name}"
        try:
            provider_dataset = _load_from_optimade_provider(
                elements,
                message=provider_message,
                **provider_kwargs,
            )
            if len(provider_dataset) == 0:
                raise RuntimeError(
                    f"OPTIMADE provider '{provider_name}' returned no usable entries"
                )
            provider_datasets.append(provider_dataset)
        except RuntimeError as err:
            fallback_trigger = (provider_name, err)
            provider_datasets = _load_all_providers_locally(
                elements,
                provider_names,
                trigger_provider=provider_name,
                err=err,
            )
            break

    show_progress = kwargs.get("show_progress", True)
    status_len = 0

    def progress(status: str):
        nonlocal status_len
        if not show_progress:
            return
        print(f"\r{status}{' ' * max(0, status_len - len(status))}", end="", flush=True)
        status_len = len(status)

    df = _optimade_provider_datasets_to_df(elements, provider_names, provider_datasets, kwargs, progress=progress)
    if show_progress and status_len:
        print()
    if message is None and fallback_trigger is not None:
        trigger_provider, _ = fallback_trigger
        message = (
            f"Full {elements} system from direct database clients; all providers "
            f"loaded locally after OPTIMADE fallback was triggered by {trigger_provider}"
        )
    message = message or f"Full {elements} system from OPTIMADE"
    return df2ds(df, message=message)


@cache_loader(read, write)
def _load_from_optimade_provider(elements, message=None, **kwargs):
    optimade_client = OptimadeClient(**kwargs)
    df = optimade_client.query(elements)
    message = message or f"Full {elements} system from OPTIMADE"
    return df2ds(df, message=message)


def _optimade_provider_names(kwargs: Dict[str, Any]) -> list[str]:
    names = []
    for provider in OptimadeClient(**kwargs)._providers():
        if provider.name not in names:
            names.append(provider.name)
    return names


def _load_from_optimade_fallback_provider(elements, provider_name: str, err: RuntimeError, message=None):
    loader, label, loader_kwargs = _optimade_fallback_loader(provider_name)
    _warn_optimade_fallback(provider_name, label, err)
    if message:
        fallback_message = (
            f"{message}; local {label} fallback used because OPTIMADE provider "
            f"{provider_name} failed"
        )
    else:
        fallback_message = f"Full {elements} system from local {label} fallback"
    dataset = loader(elements, message=fallback_message, **loader_kwargs)
    _mark_optimade_fallback(dataset, provider_name, label, err)
    return dataset


def _load_all_providers_locally(elements, provider_names, trigger_provider: str, err: RuntimeError):
    """Load one compatible total-energy dataset when any OPTIMADE provider fails.

    OPTIMADE exposes formation energies for these providers, while the direct
    loaders expose absolute total energies. Mixing the two conventions in one
    phase diagram silently removes valid entries, so fallback must be atomic
    across the complete provider set.
    """
    provider_names = list(provider_names)
    if len(provider_names) == 1:
        provider_name = provider_names[0]
        return [
            _load_from_optimade_fallback_provider(
                elements,
                provider_name,
                err,
                message=f"Full {elements} system from OPTIMADE provider {provider_name}",
            )
        ]

    _warn_all_local_fallback(trigger_provider, err)
    datasets = []
    for provider_name in provider_names:
        loader, label, loader_kwargs = _optimade_fallback_loader(provider_name)
        provider_reason = err if provider_name == trigger_provider else RuntimeError(
            f"Direct {label} loader selected to keep a consistent total-energy basis "
            f"after OPTIMADE provider '{trigger_provider}' required fallback"
        )
        fallback_message = (
            f"Full {elements} system from direct {label} loader; consistent local "
            f"fallback triggered by OPTIMADE provider {trigger_provider}"
        )
        dataset = loader(elements, message=fallback_message, **loader_kwargs)
        _mark_optimade_fallback(dataset, provider_name, label, provider_reason)
        datasets.append(dataset)
    return datasets


def _optimade_fallback_loader(provider_name: str):
    if provider_name == "materials_project":
        return load_from_materials_project, "Materials Project", {}
    if provider_name == "oqmd":
        return load_from_oqmd, "OQMD", {}
    if provider_name == "alexandria":
        return load_from_alexandria, "Alexandria", {"prompt": False}
    raise RuntimeError(f"No local fallback loader is designated for OPTIMADE provider '{provider_name}'")


def _warn_optimade_fallback(provider_name: str, fallback_label: str, err: Exception):
    banner = "!" * 88
    print(
        f"{_RED}{banner}\n"
        f"WARNING: OPTIMADE provider '{provider_name}' is unavailable; "
        f"falling back to local {fallback_label} loader.\n"
        f"Reason: {err}\n"
        f"{banner}{_RESET}",
        file=sys.stderr,
    )


def _warn_all_local_fallback(provider_name: str, err: Exception):
    banner = "!" * 88
    print(
        f"{_RED}{banner}\n"
        f"WARNING: OPTIMADE provider '{provider_name}' is unavailable or empty; "
        f"loading every provider through its direct client to preserve one "
        f"total-energy basis.\n"
        f"Reason: {err}\n"
        f"{banner}{_RESET}",
        file=sys.stderr,
    )


def _mark_optimade_fallback(dataset, provider_name: str, fallback_label: str, err: Exception):
    for entry in dataset:
        metadata = entry.metadata if entry.metadata is not None else {}
        metadata["optimade_fallback"] = {
            "provider": provider_name,
            "loader": fallback_label,
            "reason": str(err),
        }
        if entry.metadata is None:
            object.__setattr__(entry, "metadata", metadata)


def _optimade_provider_datasets_to_df(
        elements,
        provider_names,
        provider_datasets,
        kwargs: Dict[str, Any],
        progress: Callable[[str], None] | None = None,
):
    rows = []
    do_deduplication = kwargs.get("do_deduplication", True)
    optimade_client = OptimadeClient(**kwargs)
    similarity_tk = optimade_client._similarity_tools(elements) if do_deduplication else None

    for provider_no, (provider_name, dataset) in enumerate(zip(provider_names, provider_datasets), start=1):
        provider_rows = _dataset_to_rows(dataset)

        if similarity_tk is not None and rows:
            def mark_duplicate(row: dict, duplicate_of: dict):
                metadata = dict(row.get("metadata") or {})
                metadata["duplicate_of"] = duplicate_of.get("id")
                row["metadata"] = metadata

            provider_rows = similarity_tk.get_unseen_successively(
                provider_rows,
                rows,
                entry_factory=OptimadeClient._entry_from_row,
                progress=progress,
                progress_prefix=(
                    f"OPTIMADE compiling with deduplication:  "
                    f"{provider_no}/{len(provider_datasets)} {provider_name}"
                ),
                on_duplicate=mark_duplicate,
                skip_errors=True,
            )
        rows.extend(provider_rows)

    if not rows:
        return pd.DataFrame(columns=["id", "formula", "energy", "structure", "metadata"])
    return pd.DataFrame(rows).reset_index(drop=True)


def _dataset_to_rows(dataset):
    return [
        {
            "id": entry.id,
            "formula": entry.formula,
            "energy": entry.energy,
            "structure": entry.structure,
            "metadata": entry.metadata,
        }
        for entry in dataset
    ]


def load_from_uspex_calc_folders(calcfolds_path: Path, stage=None, message=None, elements=None):
    from .sources.uspex_output_parser import USPEXOutputClient

    uspex_client = USPEXOutputClient(calcfolds_path, stage=stage, mode='calcFolds')
    df = uspex_client.query(elements=elements)
    message = message or f"CalcFolds" +  (f' with elements={elements}' if elements else '.')
    return df2ds(df, message=message)

def load_from_uspex_goodstructures(goodstructures_path: Path, message=None, elements=None):
    from .sources.uspex_output_parser import USPEXOutputClient

    uspex_client = USPEXOutputClient(goodstructures_path, mode='goodStructures')
    df = uspex_client.query(elements=elements)
    message = message or f"goodStructures" +  (f' with elements={elements}' if elements else '.')
    return df2ds(df, message=message)

def load_mattersim_estimated_set(csv_path: Path, poscars_base_path: Path, message=None):
    energy_struct_client = CSV_and_POSCARS_client(results_csv=csv_path, poscars_parent_path=poscars_base_path)
    df = energy_struct_client.query()
    message = message or f"Mattersim-estimated structures from {poscars_base_path.resolve()}"
    return df2ds(df, message=message)
