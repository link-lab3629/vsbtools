import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from ...io.zip_handling import exploded_zip_tree
from ...io.yaml_csv_poscars import read

from ..build_tables import (
    build_guidance_summary_for_processed_system,
    build_guidance_summary_table,
)


ZIPPED_PROCESSED_ROOT = (
    Path(__file__).resolve().parents[2]
    / "unittests_datasets" / "MG_postprocess_pipelines" / "PROCESSED"
)


class yaml_csv_poscars_Test(unittest.TestCase):

    def setUp(self):
        self._fixtures_context = exploded_zip_tree(ZIPPED_PROCESSED_ROOT)
        self.processed_root = self._fixtures_context.__enter__()
        self.environment_repo = (
            self.processed_root / "O-Si"
            / "O-Si__guidance_environment_mode_huber_Si-O_6__diffusion_loss_weight_1-1-True__algo_0_for_histograms_stable"
        )

        self.volume_pa_repo = (
            self.processed_root / "B" / "B__guidance_volume_pa_6.8__diffusion_loss_weight_1-1-True__algo_0"
        )

        self.environment_repo_multi = (
            self.processed_root / "Ca-Cu-P-Si"
            / "Ca-Cu-P-Si__guidance_environment_mode_huber_Cu-P_4-2.2_Cu-Cu_0-2.9__diffusion_loss_weight_1-1-False__algo_None"
        )

    def tearDown(self):
        self._fixtures_context.__exit__(None, None, None)

    def test_environment_repo(self):
        ds_dict = dict()
        for manifest_yaml in self.environment_repo_multi.rglob("manifest.yaml"):
            ds = read(manifest_yaml)
            ds_dict[ds.metadata["pipeline_stage"]] = ds
        self.assertIn("parse_raw", ds_dict)
        self.assertIn("poll_db", ds_dict)
        self.assertIn("deduplicate_all", ds_dict)

        callables = build_guidance_summary_table(ds_dict, max_pareto_front=2)
        self.assertIn("symmetry", callables)
        self.assertIn("e_hull/at", callables)
        self.assertTrue(any(name.startswith("loss_") for name in callables))

        output_path = ds_dict["deduplicate_all"].base_path
        self.assertTrue((output_path / "summary.csv").is_file())
        self.assertTrue((output_path / "table.txt").is_file())
        self.assertTrue(list(output_path.glob("*pf_1.csv")))
        self.assertTrue(list(output_path.glob("*pf_1_table.txt")))


class processed_system_summary_Test(unittest.TestCase):

    def test_summarizes_every_non_guided_repository_after_guided_repositories(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            system_root = Path(tmpdir)
            repo_names = (
                "guided_generation",
                "first__guidance_None__generation",
                "second__guidance_None__generation",
            )
            for repo_name in repo_names:
                (system_root / repo_name).mkdir()

            processed = []

            def build_repo(repo_path, *, callables=None, **_kwargs):
                repo_name = Path(repo_path).name
                processed.append(repo_name)
                updated = dict(callables or {})
                updated[repo_name] = repo_name
                return updated

            def collect_artifacts(repo_path, **_kwargs):
                return {"repo": Path(repo_path), "stages": []}

            with patch(
                "vsbtools.materials_dataset.scripts.build_tables."
                "build_guidance_summary_for_repo",
                side_effect=build_repo,
            ), patch(
                "vsbtools.materials_dataset.scripts.build_tables."
                "collect_guidance_summary_artifacts",
                side_effect=collect_artifacts,
            ):
                report = build_guidance_summary_for_processed_system(
                    system_root,
                    callables={},
                    return_report=True,
                )

            self.assertEqual(processed, list(repo_names))
            self.assertEqual(list(report), list(repo_names))
            self.assertEqual(
                [item["repo"].name for item in report.generation_reports],
                list(repo_names),
            )
