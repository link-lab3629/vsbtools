import hashlib
from typing import Dict
from collections import defaultdict
from pathlib import Path
from ..genutils.misc import serialize_structure, is_substructure
from ..cache_paths import database_cache_dir, safe_cache_component
from ..crystal_dataset import CrystalDataset
from ..io.yaml_csv_poscars import read, write
from ..io.preset_loaders import (
    load_from_alexandria,
    load_from_oqmd,
    load_from_materials_project,
    load_from_optimade,
)
from ..analysis.phase_diagram_tools import PhaseDiagramTools
from ..analysis.similarity_tools import SimilarityTools, describe_similarity_tool
from ..analysis.structural_distance.dscribe_bridge import DScribeBridge

CACHE_DIR = database_cache_dir()
POLL_DB_CACHE_SCHEMA_VERSION = 2
MAX_EHULL = 0.5  # Maximum energy above hull in eV/atom for filtering
TOL_FP = 0.008
LOADERS = {
    "al": load_from_alexandria,
    "oq": load_from_oqmd,
    "mp": load_from_materials_project,
    "ma": load_from_materials_project,
    "op": load_from_optimade,
}  # List of database clients to fetch data from
OPTIMADE_FALLBACK_PROVIDERS = {
    "al": "alexandria",
    "oq": "oqmd",
    "mp": "materials_project",
    "ma": "materials_project",
}
# ------------------------------------------------------------------ #

def poll_databases(elements,
                   database_names=None,
                   pref_db: str = 'al',
                   do_ehull_filtering=True,
                   max_ehull=None,
                   do_deduplication=True,
                   similarity_tk=None,
                   tol_FP: float | None = None,
                   loader_kwargs: Dict | None =None,
                   cache_root_path: Path | None = None,
                   optimade_fallback: bool = True,
                   **kwargs):
    """
    Fetch data from OPTIMADE gate or Alexandria, OQMD, and Materials Project databases.
    Data is first taken from the reference database (pref_db) then only the structures unseen in the reference DB
    are added.
    """

    if loader_kwargs is None:
        loader_kwargs = {}
    if isinstance(database_names, str):
        database_names = [database_names]
    else:
        database_names = list(database_names or ['alexandria', 'oqmd', 'MatProj'])
    pref_db = pref_db[:2].casefold()

    parameters_dict: Dict[str, object] = {
        'cache_schema_version': POLL_DB_CACHE_SCHEMA_VERSION,
        'database_names': database_names,
        'preferred_database': pref_db,
        'loader_kwargs': serialize_structure(loader_kwargs),
        'e_hull_filtering': do_ehull_filtering,
        'deduplication': do_deduplication,
        'optimade_fallback': optimade_fallback,
    }
    if do_deduplication:
        if similarity_tk is None:
            bridge_kwargs = {"tol_FP": tol_FP} if tol_FP is not None else {}
            bridge = DScribeBridge(elements, **bridge_kwargs)
            similarity_tk = SimilarityTools(bridge.fp_dist, bridge.tol_FP)
        parameters_dict["similarity_bridge"] = kwargs.get("similarity_bridge") or describe_similarity_tool(similarity_tk)
        parameters_dict['tol_FP'] = similarity_tk.tol_FP if tol_FP is None else tol_FP

    if do_ehull_filtering:
        max_ehull = MAX_EHULL if max_ehull is None else max_ehull
        parameters_dict['max_ehull'] = max_ehull

    cache_root_path = Path(cache_root_path) if cache_root_path is not None else CACHE_DIR
    serialized_parameters = serialize_structure(parameters_dict)
    parameters_digest = hashlib.sha256(serialized_parameters.encode("utf-8")).hexdigest()[:16]
    system = safe_cache_component("-".join(sorted(elements)), max_length=80)
    cache_name = f"{system}__{parameters_digest}"
    cache_base_path = cache_root_path / cache_name

    if cache_base_path is not None and (cache_base_path / "manifest.yaml").exists():
        polled_db = read(cache_base_path / "manifest.yaml")
        try:
            if set(polled_db.elements) == set(elements) and \
                is_substructure(polled_db.metadata, parameters_dict):
                print(f"Data for elements {' '.join(elements)} read from cache")
                return polled_db
        except (AssertionError, KeyError):
            print("Incorrect db file")
        print("Failed to read cached DB")
    short_names_dict = {name[:2].casefold(): name for name in database_names}
    loader_kw = defaultdict(dict, {k.casefold()[:2]: v for k, v in loader_kwargs.items()})
    for db in short_names_dict:
        assert isinstance(db, str), "Database names must be strings."
        assert db in LOADERS, f"Database '{short_names_dict[db]}' is not recognized. Available databases: {list(LOADERS.keys())}."
    # other_loaders = [LOADERS[short_name] for short_name in short_names_dict if not short_name.startswith(ref_db)]

    def load_db(short_name):
        local_kwargs = dict(loader_kw[short_name])
        loader = LOADERS[short_name]
        if optimade_fallback and short_name == "al":
            local_kwargs.setdefault("prompt", False)
        provider = OPTIMADE_FALLBACK_PROVIDERS.get(short_name)
        if optimade_fallback and short_name != "op" and provider is not None:
            optimade_kwargs = dict(loader_kw["op"])
            optimade_kwargs.setdefault("providers", [provider])
            try:
                print(f"Fetching from OPTIMADE provider '{provider}' for {short_names_dict.get(short_name, short_name)}.")
                return load_from_optimade(elements, **optimade_kwargs)
            except Exception:
                print(f"OPTIMADE provider '{provider}' failed; falling back to local {short_names_dict.get(short_name, short_name)}.")
        try:
            return loader(elements, **local_kwargs)
        except Exception:
            if not optimade_fallback or short_name == "op":
                raise
            if provider is None:
                raise
            fallback_kwargs = dict(loader_kw["op"])
            fallback_kwargs.setdefault("providers", [provider])
            print(f"Falling back to OPTIMADE provider '{provider}' for {short_names_dict.get(short_name, short_name)}.")
            return load_from_optimade(elements, **fallback_kwargs)

    print(f"Fetching data from preferred DB: {short_names_dict.pop(pref_db)}...")
    reference_data = load_db(pref_db)

    if do_ehull_filtering:
        max_ehull = max_ehull or MAX_EHULL
        pd_tools = PhaseDiagramTools(reference_data)
        reference_data = reference_data.filter(lambda e: pd_tools.height_above_hull_pa(e) < max_ehull)

    for loader in short_names_dict: # Skip the first loader as it's already processed
        print(f"Fetching data from {short_names_dict[loader]}...")
        loaded_ds = load_db(loader)
        pd_tools = PhaseDiagramTools(loaded_ds)
        if do_ehull_filtering:
            loaded_ds = loaded_ds.filter(lambda e: pd_tools.height_above_hull_pa(e) < max_ehull)
        if do_deduplication:
            unseen = similarity_tk.get_unseen_in_ref(loaded_ds, reference_data, tol_FP=tol_FP)
            loaded_ds = unseen
        reference_data = reference_data.merge(loaded_ds)

    if do_deduplication:
        cache_base_path.mkdir(parents=True, exist_ok=True)
        reference_data.override_base_path(cache_base_path)
        reference_data, _, _ = similarity_tk.deduplicate(reference_data, tol_FP=tol_FP)

    msg = (f"Gathered from {', '.join(database_names)} databases "
           f"with elements: {', '.join(elements)}")
    ds = CrystalDataset([e.copy_with(**{'energy': None}) for e in reference_data], message=msg)
    ds.metadata = {**ds.metadata, **parameters_dict}
    write(ds, enforce_base_path=cache_base_path)
    return ds
