# scenario_pipeline.py

from __future__ import annotations

import json
import hashlib
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List, MutableMapping, Optional, Tuple
from collections import defaultdict, deque

from ..crystal_dataset import CrystalDataset
from ..io.structures_dataset_io import StructureDatasetIO, get_batch_metadata
from ..io.yaml_csv_poscars import read as read_dataset_manifest, write as write_dataset_manifest
from .symmetry_tools import SymmetryToolkit
from ..scripts.poll_databases import poll_databases, CACHE_DIR as POLL_DB_CACHE_DIR
from .similarity_tools import SimilarityTools, describe_similarity_tool
from .structural_distance.dscribe_bridge import DScribeBridge
from ..infrastructure.repository import DatasetRepo
from ..io.mattergen_tools.parsers import input_parameters_to_dict, fname_friendly_serialize
from ..io.uspex_bridge import USPEXBridge
from ..energy_estimation import nn_estimator, mattersim_bridge, grace_bridge
from ..analysis.phase_diagram_tools import PhaseDiagramTools

from .pipeline_legacy import LEGACY_INDEX_TO_NAME, LEGACY_NAME_TO_INDEX, LEGACY_DICTIONARY

# --- global constants / toolkit registry ---------------------------

TOOLKIT_DICT: Dict[str, Any] = {
    "structure_parser": StructureDatasetIO,
    "symmetry":         SymmetryToolkit,
    "similarity":       SimilarityTools,
    "dscribe":          DScribeBridge,
    "uspex":            USPEXBridge,
    "phase_diag":       PhaseDiagramTools,
    "estimator":        nn_estimator.NNEstimator,
}

KNOWN_MODELS = {"mattersim": mattersim_bridge, "grace": grace_bridge}
MAX_EHULL_PA = 0.1
POLL_DB_OPERATION_CACHE_SCHEMA_VERSION = 2
LOG = logging.getLogger(__name__)


# ==================================================================
# 1. Context: toolkits, global settings, stage outputs
# ==================================================================

@dataclass
class Context:
    """Execution context for the pipeline."""
    toolkit_options: MutableMapping[str, Dict[str, Any]] = field(
        default_factory=lambda: defaultdict(dict)
    )
    toolkits: Dict[str, Any] = field(default_factory=dict)
    globals: Dict[str, Any] = field(default_factory=dict)
    outputs: Dict[str, CrystalDataset] = field(default_factory=dict)

    def get_tool(self, name: str):
        """Lazy initialization of a toolkit by name from TOOLKIT_DICT."""
        if name not in TOOLKIT_DICT:
            raise KeyError(f"Unknown toolkit '{name}'")

        if name not in self.toolkits:
            # special handling for some toolkits
            # Auto-fill structure-similarity bridge elements from ctx.globals if missing
            if name in {"dscribe", "uspex"}:
                opts = self.toolkit_options[name]
                if "elements" not in opts:
                    elems = self.globals.get("elements")
                    if elems is None:
                        raise RuntimeError(
                            f"{TOOLKIT_DICT[name].__name__} requires 'elements'; "
                            f"set ctx.globals['elements'] before using '{name}'"
                        )
                    opts["elements"] = elems

            if name == "similarity":
                opts = self.toolkit_options["similarity"]
                bridge_name = opts.pop("bridge", "dscribe")
                if "dist_fn" not in opts:
                    bridge = self.get_tool(bridge_name)
                    opts["dist_fn"] = bridge.fp_dist
                    opts.setdefault("tol_FP", getattr(bridge, "tol_FP", 0.08))
            elif name == "estimator":
                for label, module in KNOWN_MODELS.items():
                    TOOLKIT_DICT["estimator"].register_model(label, module)

            options = self.toolkit_options.get(name, {})
            self.toolkits[name] = TOOLKIT_DICT[name](**options)

        return self.toolkits[name]


# ==================================================================
# 2. Operations and registry
# ==================================================================

OperationFn = Callable[[Context, Dict[str, CrystalDataset], Dict[str, Any]],
                       CrystalDataset]

OP_REGISTRY: Dict[str, OperationFn] = {}


def op(name: str) -> Callable[[OperationFn], OperationFn]:
    """Register an operation in the global registry."""
    def _wrap(fn: OperationFn) -> OperationFn:
        if name in OP_REGISTRY:
            raise ValueError(f"Operation '{name}' already registered")
        OP_REGISTRY[name] = fn
        return fn
    return _wrap


# ==================================================================
# 3. Scenario model and topological ordering
# ==================================================================

@dataclass
class StageSpec:
    """Specification of a single stage from the scenario."""
    name: str
    op: str
    needs: List[str] = field(default_factory=list)
    params: Dict[str, Any] = field(default_factory=dict)
    description: Optional[str] = None
    legacy_index: Optional[int] = None


@dataclass
class Scenario:
    version: int
    globals: Dict[str, Any] = field(default_factory=dict)
    stages: Dict[str, StageSpec] = field(default_factory=dict)

    # Legacy mapping: numeric index <-> stage name
    legacy_index_to_name: Dict[int, str] = field(init=False, default_factory=dict)
    legacy_name_to_index: Dict[str, int] = field(init=False, default_factory=dict)
    legacy_name_dictionary: Dict[str, str] = field(init=False, default_factory=dict)

    @staticmethod
    def from_mapping(cfg: Dict[str, Any]) -> "Scenario":
        if "version" not in cfg:
            raise ValueError("Scenario must have a 'version' field")

        g = cfg.get("globals", {}) or {}
        raw_stages = cfg.get("stages", {}) or {}
        stages: Dict[str, StageSpec] = {}

        for name, sc in raw_stages.items():
            stages[name] = StageSpec(
                name=name,
                op=sc["op"],
                needs=list(sc.get("needs", []) or []),
                params=dict(sc.get("params", {}) or {}),
                description=sc.get("description"),
                # legacy_index=int(sc["legacy_index"]) if "legacy_index" in sc else None,
            )

        scenario = Scenario(version=int(cfg["version"]), globals=g, stages=stages)
        scenario._build_legacy_mappings()
        return scenario

    def _build_legacy_mappings(self) -> None:
        """Initialize legacy index/name mappings from legacy module and scenario."""
        # Base mapping from legacy module
        self.legacy_index_to_name.update(LEGACY_INDEX_TO_NAME)
        self.legacy_name_to_index.update(LEGACY_NAME_TO_INDEX)
        self.legacy_name_dictionary.update(LEGACY_DICTIONARY)

        # Optional overrides from scenario (if you decide to use legacy_index in StageSpec)
        for name, spec in self.stages.items():
            legacy_idx = getattr(spec, "legacy_index", None)
            if legacy_idx is None:
                continue
            idx = int(legacy_idx)
            if idx in self.legacy_index_to_name and self.legacy_index_to_name[idx] != name:
                raise ValueError(
                    f"Legacy index {idx} is assigned to both "
                    f"'{self.legacy_index_to_name[idx]}' and '{name}'"
                )
            self.legacy_index_to_name[idx] = name
            self.legacy_name_to_index[name] = idx


    def resolve_stage_name_from_metadata(self, ds: CrystalDataset) -> str:
        """Resolve canonical stage name from dataset metadata.

        Supports:
        - legacy int in metadata["pipeline_stage"] (0, 1, 2, ...)
        - string stage name in metadata["pipeline_stage"]
        - stringified int in metadata["pipeline_stage"]
        """
        meta: Dict[str, Any] = getattr(ds, "metadata", None) or {}
        raw = meta.get("pipeline_stage")

        # Case 1: direct string name
        if isinstance(raw, str):
            if raw in self.stages:
                return raw
            elif raw in self.legacy_name_dictionary:
                return self.legacy_name_dictionary[raw]
            # maybe it's a stringified integer; try legacy mapping
            try:
                idx = int(raw)
            except ValueError:
                idx = None
            if idx is not None and idx in self.legacy_index_to_name:
                return self.legacy_index_to_name[idx]
            raise KeyError(f"Cannot resolve stage name from string '{raw}'")

        # Case 2: direct int (legacy index)
        if isinstance(raw, int):
            if raw in self.legacy_index_to_name:
                return self.legacy_index_to_name[raw]
            raise KeyError(f"Unknown legacy stage index: {raw}")

        raise KeyError(f"Cannot resolve stage name from metadata: {raw!r}")


def load_scenario_file(path: Path) -> Scenario:
    """Load scenario from YAML or JSON."""
    text = path.read_text(encoding="utf-8")
    suffix = path.suffix.lower()

    if suffix in {".yml", ".yaml"}:
        import yaml  # PyYAML
        data = yaml.safe_load(text)
    elif suffix == ".json":
        data = json.loads(text)
    else:
        raise ValueError(f"Unsupported scenario format: '{suffix}'")

    if not isinstance(data, dict):
        raise TypeError("Scenario root must be a mapping (dict)")
    return Scenario.from_mapping(data)


def topo_order(stages: Dict[str, StageSpec]) -> List[str]:
    """Topological sort of stage DAG.

    Returns a list of stage names such that each stage appears after all its
    dependencies. Raises RuntimeError if a cycle is detected.
    """
    indeg: Dict[str, int] = {k: 0 for k in stages}
    graph: Dict[str, List[str]] = {k: [] for k in stages}

    for name, spec in stages.items():
        for parent in spec.needs:
            if parent not in stages:
                raise KeyError(f"Unknown parent '{parent}' for stage '{name}'")
            indeg[name] += 1
            graph[parent].append(name)

    q = deque([k for k, d in indeg.items() if d == 0])
    order: List[str] = []

    while q:
        u = q.popleft()
        order.append(u)
        for v in graph[u]:
            indeg[v] -= 1
            if indeg[v] == 0:
                q.append(v)

    if len(order) != len(stages):
        raise RuntimeError("Cycle detected in scenario stages")

    return order


# ==================================================================
# 4. Scenario executor
# ==================================================================

class ScenarioPipeline:
    def __init__(self, scenario: Scenario):
        self.scenario = scenario
        self.ctx = Context()

        # clear USPEX cache as in original PPPipeline.__post_init__
        USPEXBridge.uspex_entry_from_de.cache_clear()

        # merge globals.toolkit_options into context
        tk_opts = scenario.globals.get("toolkit_options", {}) or {}
        if not isinstance(self.ctx.toolkit_options, defaultdict):
            self.ctx.toolkit_options = defaultdict(dict, tk_opts)
        else:
            self.ctx.toolkit_options.update(tk_opts)

        # other globals
        self.ctx.globals = {
            k: v for k, v in scenario.globals.items()
            if k != "toolkit_options"
        }

    @classmethod
    def from_file(cls, path: Path) -> "ScenarioPipeline":
        return cls(load_scenario_file(path))

    def _stage_sequence(
        self,
        targets: Optional[Iterable[str]],
        skip: Optional[Iterable[str]],
    ) -> List[str]:
        order = topo_order(self.scenario.stages)
        all_names = set(order)

        if targets is None:
            # By default, run only stages that are not already in outputs
            targets_set = all_names - set(self.ctx.outputs.keys())
        else:
            targets_set = set(targets)
            unknown_targets = targets_set - all_names
            if unknown_targets:
                raise KeyError(f"Unknown target stages: {sorted(unknown_targets)}")

        skip_set = set(skip) if skip else set()
        return [name for name in order if name in targets_set and name not in skip_set]

    def run(
        self,
        targets: Optional[Iterable[str]] = None,
        skip: Optional[Iterable[str]] = None,
    ) -> Iterable[Tuple[str, CrystalDataset]]:
        """
        Execute the scenario.

        Yields pairs (stage_name, CrystalDataset).
        """
        for name in self._stage_sequence(targets, skip):
            spec = self.scenario.stages[name]
            inputs = {p: self.ctx.outputs[p] for p in spec.needs}

            if spec.op not in OP_REGISTRY:
                raise KeyError(f"Operation '{spec.op}' not registered")

            params = dict(spec.params)  # copy to avoid mutating original scenario
            print(f"Start of stage {name} applied to inputs {inputs}")
            ds = OP_REGISTRY[spec.op](self.ctx, inputs, params)

            # minimal provenance
            if ds.metadata is None:
                ds.metadata = {}
            else:
                ds.metadata = dict(ds.metadata)

            ds.metadata["pipeline_stage"] = name

            ds.parent_ids = [
                getattr(inp, "dataset_id", None)
                for inp in inputs.values()
                if hasattr(inp, "dataset_id")
            ]

            idx = self.scenario.legacy_name_to_index.get(name)
            if idx is not None:
                ds.metadata.setdefault("pipeline_stage_index", str(idx))

            self.ctx.outputs[name] = ds
            yield name, ds


# ==================================================================
# 5. Generation-directory processing
# ==================================================================

def process_generation_dir(
    dir_path: str | Path,
    repo_root: str | Path,
    scenario_file: str | Path,
    *,
    repo_name: str | None = None,
    batch_metadata_file: str | Path = "input_parameters.txt",
    ignore_unknown_existing_stages: bool = True,
) -> DatasetRepo | None:
    """Run a scenario pipeline for one generated-structures directory.

    The repository location is derived from MatterGen batch metadata as
    ``<repo_root>/<chemical-system>/<serialized-input-parameters>``. Existing
    repository nodes are loaded into the pipeline context first, so only missing
    scenario stages are executed and committed.

    Returns the repository used for the generation, or ``None`` when the
    directory does not contain the requested batch metadata file.
    """
    dir_path = Path(dir_path)
    repo_root = Path(repo_root)
    scenario_file = Path(scenario_file)

    batch_meta = get_batch_metadata(dir_path, batch_metadata_file)
    if batch_meta is None:
        LOG.info("%s has no metadata file matching %s. Skipping.", dir_path, batch_metadata_file)
        return None

    param_dict = input_parameters_to_dict(raw=batch_meta)
    try:
        raw_system = param_dict["properties_to_condition_on"]["chemical_system"]
    except KeyError as exc:
        raise KeyError(
            f"Batch metadata in {dir_path} does not define "
            "properties_to_condition_on.chemical_system"
        ) from exc

    system_elements = sorted(str(raw_system).split("-"))
    system = "-".join(system_elements)
    if repo_name is None:
        repo_path = repo_root / system / fname_friendly_serialize(param_dict)
    else:
        repo_path = repo_root / repo_name
    elements = sorted(set(system_elements))

    repo = DatasetRepo(root=repo_path)
    pipeline = ScenarioPipeline.from_file(scenario_file)
    ctx = pipeline.ctx

    ctx.globals["elements"] = elements
    ctx.toolkit_options["structure_parser"]["root"] = dir_path
    ctx.toolkit_options["structure_parser"].setdefault("batch_metadata_file", batch_metadata_file)

    for node in repo.list_nodes():
        ds = repo.load_node(node)
        try:
            stage_name = pipeline.scenario.resolve_stage_name_from_metadata(ds)
        except KeyError:
            if not ignore_unknown_existing_stages:
                raise
            LOG.warning(
                "Stage in %s exists in repo, but is not described in %s. Skipping.",
                getattr(ds, "base_path", repo_path),
                scenario_file,
            )
            continue
        ctx.outputs[stage_name] = ds

    for stage_name, ds in pipeline.run():
        idx = pipeline.scenario.legacy_name_to_index.get(stage_name)
        prefix = str(idx) if idx is not None else stage_name
        repo.commit_node(ds, prefix=prefix)

    return repo


# ==================================================================
# 6. Operations implementing the original PPPipeline stages
# ==================================================================

def _normalize_cache_payload(obj: Any):
    if isinstance(obj, Path):
        return obj.as_posix()
    if isinstance(obj, dict):
        return {str(k): _normalize_cache_payload(obj[k]) for k in sorted(obj)}
    if isinstance(obj, (list, tuple)):
        return [_normalize_cache_payload(v) for v in obj]
    if isinstance(obj, set):
        normalized = [_normalize_cache_payload(v) for v in obj]
        return sorted(normalized, key=lambda x: json.dumps(x, sort_keys=True, default=str))
    if isinstance(obj, (str, int, float, bool)) or obj is None:
        return obj
    if callable(obj):
        return f"{getattr(obj, '__module__', '')}.{getattr(obj, '__qualname__', repr(obj))}"
    return repr(obj)


def _poll_db_cache_dir(elements: Iterable[str], params: Dict[str, Any]) -> Path:
    normalized_elements = sorted(str(el) for el in elements)
    normalized_params = _normalize_cache_payload(params)
    payload = {
        "cache_schema_version": POLL_DB_OPERATION_CACHE_SCHEMA_VERSION,
        "elements": normalized_elements,
        "params": normalized_params,
    }
    digest = hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("utf-8")
    ).hexdigest()[:16]
    system = "-".join(normalized_elements)
    cache_root = Path(POLL_DB_CACHE_DIR)
    return cache_root / f"poll_db__{system}__{digest}"

# --- parse_raw ----------------------------------------------------

@op("parse_raw")
def op_parse_raw(
    ctx: Context,
    inputs: Dict[str, CrystalDataset],
    params: Dict[str, Any],
) -> CrystalDataset:
    if inputs:
        raise AssertionError("parse_raw must have no parents")

    # elements can come from params or from globals
    elements = params.get("elements", ctx.globals.get("elements"))
    if elements is None:
        raise AssertionError("elements must be specified (in params or globals)")

    parser: StructureDatasetIO = ctx.get_tool("structure_parser")
    ds = parser.load_from_directory(elements=elements)  # TODO implicit requirement that toolkit has a method

    if len(ds) == 0:
        raise AssertionError("parse_raw produced an empty dataset")

    # if ds.metadata is None:
    #     ds.metadata = {}
    # ds.metadata["message"] = f"loaded {len(ds)} structures"

    return ds


# --- discard_bad_density -----------------------------------------
@op("discard_bad_density")
def op_discard_bad_density(ctx: Context,
                        inputs: Dict[str, CrystalDataset],
                        params: Dict[str, Any]) -> CrystalDataset:
    from ..geom_utils.structure_checks import check_density_sanity_pmg
    def is_structure_ok(entry):
        return check_density_sanity_pmg(entry.structure)[0]
    parent: CrystalDataset = next(iter(inputs.values()))
    ds = parent.filter(is_structure_ok)
    ds.metadata["message"] = f"Dataset {parent.dataset_id} cleared from {len(parent) - len(ds)} pathological structures"
    return ds


# --- discard_bad_density -----------------------------------------
@op("discard_close_atoms")
def op_discard_close_atoms(ctx: Context,
                        inputs: Dict[str, CrystalDataset],
                        params: Dict[str, Any]) -> CrystalDataset:
    from ..geom_utils.structure_checks import check_min_dist_pmg
    def is_structure_ok(entry):
        return check_min_dist_pmg(entry.structure)[0]
    parent: CrystalDataset = next(iter(inputs.values()))
    ds = parent.filter(is_structure_ok)
    ds.metadata["message"] = (
        f"Min distance check passed for {len(ds)}/{len(parent)} structures; "
        f"removed {len(parent) - len(ds)} pathological structures"
    )
    print(ds.metadata["message"])
    return ds


# --- symmetrize_raw ----------------------------------------------
@op("symmetrize")
def op_symmetrize(
    ctx: Context,
    inputs: Dict[str, CrystalDataset],
    params: Dict[str, Any],
) -> CrystalDataset:
    if len(inputs) != 1:
        raise AssertionError("symmetrize_raw expects exactly one parent")
    parent = next(iter(inputs.values()))

    symtool: SymmetryToolkit = ctx.get_tool("symmetry")
    ds = symtool.get_symmetrized_dataset(parent)
    print(ds.metadata["message"])
    return ds


# --- poll_db ------------------------------------------------------

@op("poll_db")
def op_poll_db(
    ctx: Context,
    inputs: Dict[str, CrystalDataset], # needs parse_raw to get elements list
    params: Dict[str, Any],
) -> CrystalDataset:
    if len(inputs) != 1:
        raise AssertionError("poll_db expects exactly one parent (parse_raw)")

    parse_ds = next(iter(inputs.values()))
    elements = getattr(parse_ds, "elements", None)
    if elements is None:
        raise AssertionError("parse_raw dataset must expose 'elements'")

    op_params = dict(params)
    # default max_ehull as in the original code
    op_params.setdefault("max_ehull", MAX_EHULL_PA)
    similarity_tk = None
    if op_params.get("do_deduplication", False):
        similarity_tk = ctx.get_tool("similarity")
        op_params.setdefault("similarity_bridge", describe_similarity_tool(similarity_tk))
    cache_params_signature = dict(op_params)
    cache_base_path = op_params.get("cache_base_path")
    op_cache_dir = Path(cache_base_path) if cache_base_path else _poll_db_cache_dir(elements, cache_params_signature)
    op_cache_manifest = op_cache_dir / "manifest.yaml"
    if op_cache_manifest.exists():
        try:
            cached = read_dataset_manifest(op_cache_manifest)
            if set(cached.elements) == set(elements):
                print(f"poll_db: reusing cached dataset from {op_cache_dir}")
                return cached
        except Exception as exc:
            LOG.warning("poll_db: failed to read cached dataset from %s: %s", op_cache_dir, exc)

    # optional additional estimation

    if similarity_tk is not None:
        op_params["similarity_tk"] = similarity_tk # Must have methods get_unseen_in_ref() and deduplicate()

    # remaining parameters are passed directly to poll_databases
    db = poll_databases(elements, **op_params)

    do_relax = bool(op_params.get("do_relaxation", False))
    estimate_energies = bool(op_params.get("estimate_energies", False))

    if do_relax or estimate_energies:
        estimator = ctx.get_tool("estimator")
    else:
        try:
            write_dataset_manifest(db, enforce_base_path=op_cache_dir)
        except Exception as exc:
            LOG.warning("poll_db: failed to write cache into %s: %s", op_cache_dir, exc)
        return db

    estimated = db
    estimator_params = dict(op_params)
    estimator_params.pop("do_relaxation", None)
    estimator_params.pop("estimate_energies", None)
    msg = estimated.metadata["message"]
    if do_relax:
        estimated = estimator.relax_dataset(estimated, **estimator_params)
        msg += f'. {estimated.metadata["message"]}'
    if estimate_energies:
        estimated = estimator.estimate_dataset_energies(estimated, **estimator_params)
        msg += f'. {estimated.metadata["message"]}'

    # parent_ids is empty as in the original code
    estimated.parent_ids = []
    estimated.metadata = dict(estimated.metadata or {})
    estimated.metadata["message"] = msg
    try:
        write_dataset_manifest(estimated, enforce_base_path=op_cache_dir)
    except Exception as exc:
        LOG.warning("poll_db: failed to write cache into %s: %s", op_cache_dir, exc)

    return estimated


# --- augment_raw_by_db -------------------------------------------

@op("merge_base_into_ref")
def op_merge_ref(
    ctx: Context,
    inputs: Dict[str, CrystalDataset],
    params: Dict[str, Any],
) -> CrystalDataset:
    if len(inputs) != 2:
        raise AssertionError("augment_raw_by_db expects exactly two parents")

    """
    params:
        base_parent -- name of base parent
        ref_parent -- name of reference parent
        merge -- if True, base entry is removed if it reproduces an entry from reference  
    """

    parent_names = list(inputs.keys())

    # By default, use the order from 'needs' in the scenario:
    # first parent -> symmetrized dataset, second -> reference DB.
    base_name = params.get("base_parent", parent_names[0])
    ref_name = params.get("ref_parent", parent_names[1])

    try:
        base_ds = inputs[base_name]
    except KeyError as e:
        raise KeyError(f"base_parent '{base_name}' not found among inputs {parent_names}") from e

    try:
        ref_ds = inputs[ref_name]
    except KeyError as e:
        raise KeyError(f"ref_parent '{ref_name}' not found among inputs {parent_names}") from e

    similarity_tk: SimilarityTools = ctx.get_tool("similarity")
    augmentation = similarity_tk.get_unseen_in_ref(base_ds, ref_ds=ref_ds)

    print(augmentation.metadata.get("message", ""))

    # Mark DB entries with reproduced=True
    reproduced = augmentation.metadata.get("reproduced", {})
    labeled_entries = []
    for e in ref_ds:
        if str(e.id) in reproduced:
            new_metadata = {**(e.metadata or {}), "reproduced": True}
            labeled_entries.append(e.copy_with(metadata=new_metadata))
        else:
            labeled_entries.append(e)

    # Reconstruct CrystalDataset parameters
    ref_parameters = ref_ds.__dict__.copy()
    meta = ref_parameters.pop("metadata", {})
    base_path = ref_parameters.pop("_base_path", None)
    if base_path is not None:
        ref_parameters["base_path"] = base_path
    for k in list(ref_parameters):
        if k.startswith("_"):
            ref_parameters.pop(k, None)

    labeled_db = CrystalDataset(labeled_entries, **ref_parameters)
    labeled_db.metadata = meta

    if params.get("merge", False):
        merged = labeled_db.merge(augmentation)
        action_str = "merged into"
    else:
        merged = labeled_db.merge(base_ds)
        action_str = "added to"
    merged.metadata = dict(merged.metadata or {})
    merged.metadata["message"] = f"Base dataset {action_str} reference set. {augmentation.metadata['message']}"
    merged.metadata["reproducibility"] = augmentation.metadata.get("reproducibility")

    merged.parent_ids = [
        getattr(base_ds, "dataset_id", None),
        getattr(ref_ds, "dataset_id", None),
    ]

    return merged



# --- estimate -----------------------------------------------------

@op("estimate")
def op_estimate(
    ctx: Context,
    inputs: Dict[str, CrystalDataset],
    params: Dict[str, Any],
) -> CrystalDataset:
    if len(inputs) != 1:
        raise AssertionError("estimate expects exactly one parent (augment_raw_by_db)")
    parent = next(iter(inputs.values()))

    estimator = ctx.get_tool("estimator")
    return estimator.estimate_dataset_energies(parent, **params)


# --- relax ---------------------------------------------------------

@op("relax")
def op_relax(
    ctx: Context,
    inputs: Dict[str, CrystalDataset],
    params: Dict[str, Any],
) -> CrystalDataset:
    if len(inputs) != 1:
        raise AssertionError("relax expects exactly one parent (augment_raw_by_db)")
    parent = next(iter(inputs.values()))

    estimator = ctx.get_tool("estimator")
    return estimator.relax_dataset(parent, **params)


# --- filter_hull --------------------------------------------------

@op("filter_hull")
def op_filter_hull(
    ctx: Context,
    inputs: Dict[str, CrystalDataset],
    params: Dict[str, Any],
) -> CrystalDataset:
    if not inputs:
        raise AssertionError("filter_hull requires at least one parent")

    max_ehull = params.get("max_ehull", MAX_EHULL_PA)

    parent_names = list(inputs.keys())

    # Dataset used to build the phase diagram
    pd_source_name = params.get("pd_source")
    if pd_source_name is None:
        # Default: first parent in 'needs' order
        base_ds = next(iter(inputs.values()))
    else:
        try:
            base_ds = inputs[pd_source_name]
        except KeyError as e:
            raise KeyError(f"pd_source '{pd_source_name}' not found among inputs {parent_names}") from e

    ctx.toolkit_options["phase_diag"] = {"dataset": base_ds}
    pd_tk: PhaseDiagramTools = ctx.get_tool("phase_diag")

    # Dataset to be filtered
    filter_from_name = params.get("filter_from")
    if filter_from_name is None:
        select_from = base_ds
    else:
        try:
            select_from = inputs[filter_from_name]
        except KeyError as e:
            raise KeyError(f"filter_from '{filter_from_name}' not found among inputs {parent_names}") from e

    filtered = select_from.filter(
        lambda entry: pd_tk.height_above_hull_pa(entry) < max_ehull
    )
    filtered.metadata = dict(filtered.metadata or {})
    filtered.metadata["message"] = f"Selected entries with e_hull < {max_ehull:.3f}"

    return filtered


# --- deduplicate --------------------------------------------------

@op("deduplicate")
def op_deduplicate(
    ctx: Context,
    inputs: Dict[str, CrystalDataset],
    params: Dict[str, Any],
) -> CrystalDataset:
    if len(inputs) != 1:
        raise AssertionError("deduplicate expects exactly one parent (filter_hull)")
    parent = next(iter(inputs.values()))

    tol_FP = params.pop("tol_FP", None)

    similarity_tk: SimilarityTools = ctx.get_tool("similarity")
    ds, _, _ = similarity_tk.deduplicate(
        parent,
        check_clusters_file=bool(params.get("check_clusters_file", False)),
        check_dist_matrix_file=bool(params.get("check_dist_matrix_file", False)),
        save_clusters_file=bool(params.get("save_clusters_file", False)),
        save_dist_matrix_file=bool(params.get("save_dist_matrix_file", False)),
        tol_FP=tol_FP
    )

    ds.parent_ids = [getattr(parent, "dataset_id", None)]
    ds.metadata = dict(ds.metadata or {})
    ds.metadata["message"] = f"Deduplicated version of {getattr(parent, 'dataset_id', 'unknown')}"

    return ds


# --- postprocess_dft (placeholder) --------------------------------

@op("postprocess_dft")
def op_postprocess_dft(
    ctx: Context,
    inputs: Dict[str, CrystalDataset],
    params: Dict[str, Any],
) -> CrystalDataset:
    raise NotImplementedError("Implement DFT post-processing when needed")
