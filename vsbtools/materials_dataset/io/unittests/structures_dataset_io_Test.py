import tempfile
import unittest
from pathlib import Path
from .. import structures_dataset_io
from ..structures_dataset_io import StructureDatasetIO, exploded_zip_tree, get_batch_metadata

PATH_WITH_TESTS = Path(__file__).parent
PATH_TEST_DATASET = PATH_WITH_TESTS / "../../unittests_datasets"


class zipped_poscar_dir_read_Test(unittest.TestCase):

    def setUp(self) -> None:
        self.zipped_cifs = PATH_TEST_DATASET / 'zipped_cifs'

    def test_unzip(self):
        with exploded_zip_tree(self.zipped_cifs) as tmp_path:
            self.utils = StructureDatasetIO(tmp_path, pattern="*.cif")
            ds = self.utils.load_from_directory()
            self.assertEqual(len(ds), 696)


class extxyz_Test(unittest.TestCase):

    def setUp(self) -> None:
        self.extxyz_file = (PATH_WITH_TESTS /
                            "../../unittests_datasets/Cu-Si-P-Ca_guided.extxyz").resolve()

    def test_extxyz_to_poscars(self):
        utils = StructureDatasetIO(PATH_WITH_TESTS)
        ds = utils.load_from_extxyz(self.extxyz_file)
        self.assertGreater(len(ds), 0)
        self.assertEqual(ds[0].natoms, 15)

        with tempfile.TemporaryDirectory() as tmpdir:
            out_dir = Path(tmpdir)
            utils.dump_poscar_files(ds, out_dir)
            poscars = list(out_dir.rglob("*POSCAR"))
            self.assertEqual(len(poscars), len(ds))

    def test_load_from_directory_extxyz_batches(self):
        extxyz_root = (PATH_WITH_TESTS / "../../unittests_datasets/cifs").resolve()
        utils = StructureDatasetIO(extxyz_root, pattern="*.extxyz")
        ds = utils.load_from_directory()
        extxyz_files = list(extxyz_root.rglob("*.extxyz"))
        expected = sum(len(utils.load_from_extxyz(file)) for file in extxyz_files)
        self.assertGreater(len(ds), 0)
        self.assertEqual(len(ds), expected)
        self.assertEqual(ds.metadata["source_file_count"], len(extxyz_files))
        self.assertEqual(ds.metadata["parsed_structure_count"], expected)
        self.assertEqual(ds.metadata["retained_structure_count"], expected)
        self.assertEqual(ds.metadata["failed_file_count"], 0)
        self.assertIn(f"{expected} parsed structures", ds.metadata["message"])

    def test_patterns_priority_fallback(self):
        extxyz_root = (PATH_WITH_TESTS / "../../unittests_datasets/cifs").resolve()
        utils = StructureDatasetIO(extxyz_root, patterns_priority=("*POSCARS", "*.extxyz"))
        ds = utils.load_from_directory()
        self.assertGreater(len(ds), 0)

    def test_warn_on_mixed_types(self):
        mixed_root = (PATH_WITH_TESTS / "../../unittests_datasets/cifs").resolve()
        utils = StructureDatasetIO(mixed_root, patterns_priority=("*.cif", "*.extxyz"))
        with self.assertLogs(structures_dataset_io.LOG, level="WARNING") as logs:
            _ = utils.load_from_directory()
        joined_logs = "\n".join(logs.output)
        self.assertIn("Mixed structure sources detected", joined_logs)

    def test_invalid_pattern_rejected(self):
        with self.assertRaises(ValueError):
            _ = StructureDatasetIO(PATH_WITH_TESTS, pattern="*.foo")


class batch_metadata_Test(unittest.TestCase):

    def test_allows_known_runtime_parameter_differences(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            (root / "run_1").mkdir()
            (root / "run_2").mkdir()
            (root / "run_1" / "input_parameters.txt").write_text(
                "\n".join((
                    "output_path: results/run_1",
                    "batch_size: 12",
                    "num_batches: 2",
                    "gpu_memory_gb: 11.25",
                    "force_gpu: 0",
                    "print_loss: False",
                    "properties_to_condition_on: {'chemical_system': 'Cu-Si-P'}",
                    "guidance: {'environment': {'mode': 'huber', 'Cu-P': [3, 2.9]}}",
                    "algo: False",
                    "",
                )),
                encoding="utf-8",
            )
            (root / "run_2" / "input_parameters.txt").write_text(
                "\n".join((
                    "output_path: results/run_2",
                    "batch_size: 24",
                    "num_batches: 5",
                    "gpu_memory_gb: 80",
                    "force_gpu: 1",
                    "print_loss: True",
                    "properties_to_condition_on: {'chemical_system': 'Cu-Si-P'}",
                    "guidance: {'environment': {'mode': 'huber', 'Cu-P': [3, 2.9]}}",
                    "algo: False",
                    "",
                )),
                encoding="utf-8",
            )

            batch_metadata = get_batch_metadata(root, "input_parameters.txt")

            self.assertIn("output_path: results/run_1", batch_metadata)

    def test_raises_for_non_allowed_metadata_differences(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            (root / "run_1").mkdir()
            (root / "run_2").mkdir()
            (root / "run_1" / "input_parameters.txt").write_text(
                "output_path: results/run_1\nbatch_size: 12\nalgo: False\n",
                encoding="utf-8",
            )
            (root / "run_2" / "input_parameters.txt").write_text(
                "output_path: results/run_2\nbatch_size: 24\nalgo: True\n",
                encoding="utf-8",
            )

            with self.assertRaisesRegex(ValueError, "differ outside allowed batch metadata keys"):
                get_batch_metadata(root, "input_parameters.txt")
