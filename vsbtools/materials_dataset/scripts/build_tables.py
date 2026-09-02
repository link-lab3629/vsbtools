import logging
import os
from pathlib import Path
from typing import Any, Dict, Callable
from pymatgen.core import Composition

from ..genutils.pareto_tools import pareto_subdataframe_indices
from ..crystal_dataset import CrystalDataset
from ..io.yaml_csv_poscars import read
from ..analysis.guidance_statistics import callables_from_ds
from ..analysis import (
    phase_diagram_tools as pdt,
    symmetry_tools as st,
    summary
)


LOG = logging.getLogger(__name__)


def _as_list(value):
    return [value] if isinstance(value, str) else value


class GuidanceSummaryBuildReport(dict):
    """Dict-like callable registry with a readable artifact summary."""

    def __init__(
        self,
        callables: Dict[str, Callable],
        *,
        processed_system_repo: Path,
        generation_reports: list[dict[str, Any]],
    ):
        super().__init__(callables)
        self.callables = self
        self.processed_system_repo = processed_system_repo
        self.generation_reports = generation_reports

    def __repr__(self) -> str:
        lines = [
            "Guidance summary artifacts",
            "",
            f"Processed system: {self.processed_system_repo}",
            "",
            "Generation repositories:",
        ]
        for idx, report in enumerate(self.generation_reports):
            if idx:
                lines.append("")
            lines.append(f" - {report['repo'].name}")
            for stage in report["stages"]:
                lines.append(f"   stage {stage['stage']}: {stage['stage_dir']}")
                for key in ("summary_csv", "table_txt"):
                    path = stage.get(key)
                    if path is not None:
                        lines.append(f"     {key}: {path}")
                for key, label in (
                    ("pareto_csv", "pareto_csv"),
                    ("pareto_tables", "pareto_table"),
                    ("pareto_dirs", "pareto_poscars"),
                ):
                    paths = stage.get(key, [])
                    if paths:
                        lines.append(f"     {label}:")
                        lines.extend(f"       {path}" for path in paths)
        if self:
            lines.append("")
            lines.append("Summary columns/callables:")
            lines.extend(f" - {name}" for name in self.keys())
        return "\n".join(lines)

    def _repr_pretty_(self, printer, _cycle):
        printer.text(repr(self))


def collect_guidance_summary_artifacts(
    repo_path: str | Path,
    target_stages: list | str | None = "deduplicate_all",
) -> dict[str, Any]:
    """Collect paths produced by build_guidance_summary_for_repo."""
    repo_path = Path(repo_path)
    stage_names = _as_list(target_stages) or []
    datasets = stage_datasets_from_repo(repo_path)
    stages = []
    for stage_name in stage_names:
        dataset = datasets.get(stage_name)
        if dataset is None or dataset.base_path is None:
            continue
        stage_dir = Path(dataset.base_path)
        stage_report = {
            "stage": stage_name,
            "stage_dir": stage_dir,
            "summary_csv": stage_dir / "summary.csv",
            "table_txt": stage_dir / "table.txt",
            "pareto_csv": sorted(stage_dir.glob("*pf_*.csv")),
            "pareto_tables": sorted(stage_dir.glob("*pf_*_table.txt")),
            "pareto_dirs": sorted(path for path in stage_dir.glob("*pf_*") if path.is_dir()),
        }
        stages.append(stage_report)
    return {"repo": repo_path, "stages": stages}


def build_guidance_summary_table(name_ds_dict: Dict[str, CrystalDataset],
                                 raw_stage: str = 'parse_raw',
                                 target_stages: list | str | None = 'deduplicate_all',
                                 ref_stages: dict | None = None,
                                 auto_ref_stages: bool = False,
                                 callables: Dict[str, Callable] | None = None,
                                 max_pareto_front: int | None = None):
    """
    For given dict builds tables containing the values of target property
    """
    # gl_name = 'placeholder'

    target_stages = _as_list(target_stages)

    if callables is None:
        callables, _targets, _ = callables_from_ds(name_ds_dict[raw_stage])

    stk = st.SymmetryToolkit(a_sym_prec=1e-3)
    callables["symmetry"] = stk.sym_group_symbol

    for stage in target_stages:

        assert ref_stages is None or not auto_ref_stages, \
            "Either ref_stages or auto_ref_stages should be specified (not both)"
        if ref_stages is None:
            ref_stage = 'poll_db_grace' if 'grace' in stage else 'poll_db'
        else:
            ref_stage = ref_stages[stage]
        pd_tk = pdt.PhaseDiagramTools(name_ds_dict[ref_stage])
        callables["e_hull/at"] = pd_tk.height_above_hull_pa

        summary_df = summary.collect_summary_df(name_ds_dict[stage], native_columns=("id", "composition", "energy"),
                                                callables=callables)
        summary.print_pretty_df(summary_df, name_ds_dict[stage].base_path / 'table.txt', sort_by='e_hull/at')

        summary_df.to_csv(name_ds_dict[stage].base_path / "summary.csv")

        losses = [call_name for call_name in callables.keys() if 'loss' in call_name]

        losses_prefixes = ['']
        if len(losses) > 1:
            losses_prefixes = [loss.replace('loss_', '') + '_' for loss in losses]

        if max_pareto_front is not None:
            entries_by_id = {str(entry.id): entry for entry in name_ds_dict[stage]}
            for j, gl_name in enumerate(losses):
                max_el_db = summary_df[summary_df['composition'].apply(lambda x: len(Composition(x))) == len(name_ds_dict[stage].elements)].sort_values('e_hull/at')
                fronts_idx, rank = pareto_subdataframe_indices(max_el_db, ['e_hull/at', gl_name],  max_pareto_front)
                for i, idx_pf in enumerate(fronts_idx):
                    max_el_db.iloc[idx_pf].to_csv(name_ds_dict[stage].base_path / f"{losses_prefixes[j]}pf_{i+1}.csv")
                    summary.print_pretty_df(max_el_db.iloc[idx_pf], name_ds_dict[stage].base_path / f"{losses_prefixes[j]}pf_{i+1}_table.txt",
                                            sort_by='e_hull/at')
                    pf_dir = name_ds_dict[stage].base_path / f"{losses_prefixes[j]}pf_{i+1}"
                    os.makedirs(pf_dir, exist_ok=True)
                    for k, idx in enumerate(idx_pf):
                        entry_id = str(max_el_db.iloc[idx].id)
                        entry = entries_by_id.get(entry_id)
                        if entry is None:
                            LOG.warning("Skipping missing Pareto POSCAR export for %s", entry_id)
                            continue
                        entry.structure.to(fmt="poscar", filename=pf_dir / f"{k+1}_{entry_id}POSCAR", comment=entry_id)



    return callables

def stage_datasets_from_repo(repo_path: str | Path) -> Dict[str, CrystalDataset]:
    """Load all dataset manifests under a processed generation repo by stage name."""
    ds_dict: Dict[str, CrystalDataset] = {}
    for manifest_yaml in Path(repo_path).rglob("manifest.yaml"):
        dataset = read(manifest_yaml)
        ds_dict[dataset.metadata["pipeline_stage"]] = dataset
    return ds_dict


def build_guidance_summary_for_repo(
    repo_path: str | Path,
    *,
    raw_stage: str = "parse_raw",
    target_stages: list | str | None = "deduplicate_all",
    ref_stages: dict | None = None,
    auto_ref_stages: bool = False,
    callables: Dict[str, Callable] | None = None,
    max_pareto_front: int | None = None,
) -> Dict[str, Callable]:
    """Build summary tables and Pareto-front exports for one generation repo."""
    summary_callables = None if callables is None else dict(callables)
    return build_guidance_summary_table(
        stage_datasets_from_repo(repo_path),
        raw_stage=raw_stage,
        target_stages=target_stages,
        ref_stages=ref_stages,
        auto_ref_stages=auto_ref_stages,
        callables=summary_callables,
        max_pareto_front=max_pareto_front,
    )


def build_guidance_summary_for_processed_system(
    processed_system_repo: str | Path,
    *,
    raw_stage: str = "parse_raw",
    target_stages: list | str | None = "deduplicate_all",
    ref_stages: dict | None = None,
    auto_ref_stages: bool = False,
    callables: Dict[str, Callable] | None = None,
    max_pareto_front: int | None = None,
    non_guided_marker: str = "guidance_None",
    return_report: bool = False,
) -> Dict[str, Callable]:
    """Build comparable summary artifacts for all generation repos in one system.

    Guided repos are summarized first. Their inferred callables are merged and
    then reused for every non-guided repo, which keeps the summary columns and
    Pareto-front exports aligned across the system.
    """
    processed_system_repo = Path(processed_system_repo)
    if not processed_system_repo.is_dir():
        raise NotADirectoryError(processed_system_repo)

    system_callables: Dict[str, Callable] = dict(callables or {})
    non_guided_repos: list[Path] = []
    generation_reports: list[dict[str, Any]] = []

    for generation_repo in sorted(processed_system_repo.iterdir()):
        if not generation_repo.is_dir():
            continue
        if non_guided_marker in generation_repo.as_posix():
            non_guided_repos.append(generation_repo)
            continue

        repo_callables = build_guidance_summary_for_repo(
            generation_repo,
            raw_stage=raw_stage,
            target_stages=target_stages,
            ref_stages=ref_stages,
            auto_ref_stages=auto_ref_stages,
            callables=None if callables is None else system_callables,
            max_pareto_front=max_pareto_front,
        )
        system_callables.update(repo_callables)
        generation_reports.append(
            collect_guidance_summary_artifacts(generation_repo, target_stages=target_stages)
        )

    if not non_guided_repos:
        LOG.warning(
            "Non-guided generation repo not found for processed system %s",
            processed_system_repo,
        )
        if return_report:
            return GuidanceSummaryBuildReport(
                system_callables,
                processed_system_repo=processed_system_repo,
                generation_reports=generation_reports,
            )
        return system_callables

    for non_guided_repo in non_guided_repos:
        system_callables = build_guidance_summary_for_repo(
            non_guided_repo,
            raw_stage=raw_stage,
            target_stages=target_stages,
            ref_stages=ref_stages,
            auto_ref_stages=auto_ref_stages,
            callables=system_callables,
            max_pareto_front=max_pareto_front,
        )
        generation_reports.append(
            collect_guidance_summary_artifacts(non_guided_repo, target_stages=target_stages)
        )
    if return_report:
        return GuidanceSummaryBuildReport(
            system_callables,
            processed_system_repo=processed_system_repo,
            generation_reports=generation_reports,
        )
    return system_callables


if __name__ == "__main__":
    from pathlib import Path
    from vsbtools.materials_dataset.analysis.scenario_pipeline import Scenario
    from vsbtools.materials_dataset.analysis.guidance_statistics import get_guidance_generation_dirs

    repo = Path("/home/vsbat/SYNC/00__WORK/2025-2026_MOLTEN_SALTS/"
                "MG_postprocess_pipelines/PROCESSED/Ca-Cu-P-Si/"
                "Ca-Cu-P-Si__guidance_environment_mode_huber_Cu-P_4-2.2_Cu-Cu_0-2.9__diffusion_loss_weight_1-1-False__algo_None",
                )

    ds_dict = dict()

    for manifest_yaml in repo.rglob("manifest.yaml"):
        ds = read(manifest_yaml)
        ds_dict[ds.metadata["pipeline_stage"]] = ds
        print(ds_dict.keys())
