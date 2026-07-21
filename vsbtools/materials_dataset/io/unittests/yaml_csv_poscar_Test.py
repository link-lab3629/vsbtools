import unittest
import tempfile
import zipfile
from pathlib import Path
from ..yaml_csv_poscars import read, write, load_yaml_recursively
from ..preset_loaders import load_mattersim_estimated_set

PATH_WITH_TESTS = Path(__file__).parent


class yaml_csv_poscars_Test(unittest.TestCase):

    def setUp(self) -> None:
        self.csv = PATH_WITH_TESTS / 'mattersim_res_for_POSCARS.csv'
        PATH_WITH_DATASETS = PATH_WITH_TESTS / "../../unittests_datasets"
        self.poscars_folder = PATH_WITH_DATASETS / "POSCARS"
        self.ref_dump_results = PATH_WITH_DATASETS / "ref_yaml_csv_poscars"


    def test_write_read(self):
        ds = load_mattersim_estimated_set(self.csv, self.poscars_folder)
        ds.metadata = {}
        ds.dataset_id = '0'
        with tempfile.TemporaryDirectory() as tmpdir:
            res_path_1 = Path(tmpdir) / "tmp1"
            ds.override_base_path(res_path_1)
            write(ds)
            self.assertTrue((res_path_1 / "POSCARS.zip").is_file())
            self.assertFalse((res_path_1 / "POSCARS").exists())
            with zipfile.ZipFile(res_path_1 / "POSCARS.zip") as archive:
                self.assertIn(ds[0].poscarname, archive.namelist())
                self.assertEqual(archive.read(ds[0].poscarname).decode().splitlines()[0], ds[0].id)
            res_path_2 = Path(tmpdir) / "tmp2"
            ds2 = read(ds.base_path / f"manifest.yaml")
            self.assertEqual(len(ds2), len(ds))
            self.assertEqual(ds2[0].metadata.get("source"), "ALIGNN")
            ds2.override_base_path(res_path_2)
            write(ds2)
            ds3 = read(res_path_2 / f"manifest.yaml")
            self.assertEqual(len(ds3), len(ds))
            self.assertEqual(ds3[0].metadata, ds2[0].metadata)

    def test_recursive_yaml_read(self):
        meta_dict = load_yaml_recursively(yaml_fname=PATH_WITH_TESTS / "manifest_batch_meta.yaml")
        self.assertEqual(meta_dict["dataset_id"], "x682a99d91d2d8da2")
        self.assertEqual(meta_dict["metadata"]["pipeline_stage"], "parse_raw")
        self.assertEqual(meta_dict["metadata"]["batch_metadata"]["batch_size"], 12)
        self.assertEqual(
            meta_dict["metadata"]["batch_metadata"]["guidance"],
            {"environment": {"mode": "huber", "B-Fe": 3}},
        )
