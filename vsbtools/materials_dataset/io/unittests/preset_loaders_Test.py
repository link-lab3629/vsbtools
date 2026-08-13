import unittest
import io
from contextlib import redirect_stderr
from pathlib import Path
from unittest.mock import MagicMock, Mock, patch
from ...io import preset_loaders as preset_loaders_module
from ...io.preset_loaders import (load_from_materials_project,
                                                                                load_from_oqmd,
                                                                                load_from_alexandria,
                                                                                load_from_optimade,
                                                                                load_from_uspex_goodstructures,
                                                                                load_from_uspex_calc_folders,
                                                                                load_mattersim_estimated_set)

PATH_WITH_TESTS = Path(__file__).parent
PATH_WITH_DATASETS = PATH_WITH_TESTS / "../../unittests_datasets"


class _FakeEntry:
    def __init__(self):
        self.metadata = {}


class DSLoaders_Test(unittest.TestCase):

    def setUp(self) -> None:
        self.poscars_folder = PATH_WITH_DATASETS / "POSCARS"
        self.uspex_calcfolders = PATH_WITH_DATASETS / 'uspex_folders/calcFolders'
        self.uspex_goodStructures = PATH_WITH_DATASETS / 'uspex_folders/results1/goodStructures'
        self.csv = PATH_WITH_TESTS / 'mattersim_res_for_POSCARS.csv'

    def test_loadMP(self):
        ds = load_from_materials_project({'Mo', 'Si'})
        self.assertEqual(len(ds), 58)

    def test_load_from_materials_project_interface(self):
        query_df = Mock(name="query_df")
        dataset = Mock(name="dataset")
        client = Mock()
        client.query.return_value = query_df

        with patch.object(preset_loaders_module, "mp_client", client), \
                patch.object(preset_loaders_module, "df2ds", return_value=dataset) as df2ds:
            result = load_from_materials_project.__wrapped__({'Mo', 'Si'})

        client.query.assert_called_once_with({'Mo', 'Si'})
        self.assertIn("Materials Project", df2ds.call_args.kwargs["message"])
        self.assertIs(result, dataset)

    def test_loadOQMD(self):
        ds = load_from_oqmd({'Mo', 'Si'})
        self.assertEqual(len(ds), 83)

    def test_load_from_oqmd_interface(self):
        query_df = Mock(name="query_df")
        dataset = Mock(name="dataset")
        client = Mock()
        client.query.return_value = query_df

        with patch.object(preset_loaders_module, "oqmd_client", client), \
                patch.object(preset_loaders_module, "df2ds", return_value=dataset) as df2ds:
            result = load_from_oqmd.__wrapped__({'Mo', 'Si'})

        client.query.assert_called_once_with({'Mo', 'Si'})
        self.assertIn("OQMD", df2ds.call_args.kwargs["message"])
        self.assertIs(result, dataset)

    def test_loadAlexandria(self):
        ds = load_from_alexandria({'Mo', 'Si'}, pattern='alexandria_00*.json')
        self.assertEqual(len(ds), 34)

    def test_load_from_alexandria_interface(self):
        query_df = Mock(name="query_df")
        dataset = Mock(name="dataset")
        client = Mock()
        client.query.return_value = query_df

        with patch.object(preset_loaders_module, "AlexandriaClient", return_value=client) as client_cls, \
                patch.object(preset_loaders_module, "df2ds", return_value=dataset) as df2ds:
            result = load_from_alexandria.__wrapped__({'Mo', 'Si'}, pattern="alexandria_00*.json")

        client_cls.assert_called_once_with(pattern="alexandria_00*.json")
        client.query.assert_called_once_with({'Mo', 'Si'})
        self.assertIn("Alexandria", df2ds.call_args.kwargs["message"])
        self.assertIs(result, dataset)

    def test_load_from_optimade_direct_interface(self):
        query_df = Mock(name="query_df")
        query_df.empty = False
        dataset = Mock(name="dataset")
        client = Mock()
        client.query.return_value = query_df

        with patch.object(preset_loaders_module, "OptimadeClient", return_value=client) as client_cls, \
                patch.object(preset_loaders_module, "df2ds", return_value=dataset) as df2ds:
            result = load_from_optimade.__wrapped__(
                {'Mo', 'Si'},
                providers=["oqmd"],
                page_limit=10,
                per_provider_cache=False,
            )

        client_cls.assert_called_once_with(providers=["oqmd"], page_limit=10)
        client.query.assert_called_once_with({'Mo', 'Si'})
        self.assertTrue(df2ds.call_args.kwargs["message"].startswith("Full "))
        self.assertIn("OPTIMADE", df2ds.call_args.kwargs["message"])
        self.assertIs(result, dataset)

    def test_load_from_optimade_uses_provider_cache_loaders(self):
        query_df = Mock(name="query_df")
        dataset = Mock(name="dataset")
        provider_datasets = [MagicMock(name="oqmd_dataset"), MagicMock(name="alexandria_dataset")]
        for provider_dataset in provider_datasets:
            provider_dataset.__len__.return_value = 1

        with patch.object(preset_loaders_module, "_load_from_optimade_provider",
                          side_effect=provider_datasets) as provider_loader, \
                patch.object(preset_loaders_module, "_optimade_provider_datasets_to_df",
                             return_value=query_df) as datasets_to_df, \
                patch.object(preset_loaders_module, "df2ds", return_value=dataset) as df2ds:
            result = load_from_optimade.__wrapped__(
                {'Mo', 'Si'},
                providers=["oqmd", "alexandria"],
                page_limit=10,
            )

        self.assertEqual(provider_loader.call_count, 2)
        self.assertEqual(provider_loader.call_args_list[0].kwargs["providers"], ["oqmd"])
        self.assertEqual(provider_loader.call_args_list[1].kwargs["providers"], ["alexandria"])
        self.assertEqual(provider_loader.call_args_list[0].kwargs["cache_label"], "optimade_oqmd")
        self.assertEqual(provider_loader.call_args_list[1].kwargs["cache_label"], "optimade_alexandria")
        self.assertEqual(provider_loader.call_args_list[0].kwargs["progress_provider_no"], 1)
        self.assertEqual(provider_loader.call_args_list[1].kwargs["progress_provider_no"], 2)
        self.assertEqual(provider_loader.call_args_list[0].kwargs["progress_total_providers"], 2)
        self.assertEqual(provider_loader.call_args_list[1].kwargs["progress_total_providers"], 2)
        self.assertFalse(provider_loader.call_args_list[0].kwargs["do_deduplication"])
        datasets_to_df.assert_called_once()
        self.assertEqual(datasets_to_df.call_args.args[1], ["oqmd", "alexandria"])
        self.assertEqual(datasets_to_df.call_args.args[2], provider_datasets)
        self.assertIs(df2ds.call_args.args[0], query_df)
        self.assertIs(result, dataset)

    def test_load_from_optimade_falls_back_to_local_loader_when_provider_fails(self):
        query_df = Mock(name="query_df")
        dataset = Mock(name="dataset")
        fallback_dataset = [_FakeEntry()]
        provider_error = RuntimeError("OPTIMADE request failed with HTTP 502: https://oqmd.org/optimade")

        err = io.StringIO()
        with patch.object(preset_loaders_module, "_load_from_optimade_provider",
                          side_effect=provider_error) as provider_loader, \
                patch.object(preset_loaders_module, "load_from_oqmd",
                             return_value=fallback_dataset) as oqmd_loader, \
                patch.object(preset_loaders_module, "_optimade_provider_datasets_to_df",
                             return_value=query_df) as datasets_to_df, \
                patch.object(preset_loaders_module, "df2ds", return_value=dataset), \
                redirect_stderr(err):
            result = load_from_optimade.__wrapped__(
                {'Mo', 'Si'},
                providers=["oqmd"],
                page_limit=10,
            )

        provider_loader.assert_called_once()
        oqmd_loader.assert_called_once()
        self.assertEqual(oqmd_loader.call_args.args[0], {'Mo', 'Si'})
        self.assertIn("local OQMD fallback", oqmd_loader.call_args.kwargs["message"])
        self.assertEqual(datasets_to_df.call_args.args[2], [fallback_dataset])
        self.assertEqual(
            fallback_dataset[0].metadata["optimade_fallback"]["provider"],
            "oqmd",
        )
        self.assertIn("\033[1;31m", err.getvalue())
        self.assertIn("WARNING", err.getvalue())
        self.assertIn("falling back to local OQMD loader", err.getvalue())
        self.assertIs(result, dataset)

    def test_load_from_optimade_falls_back_all_providers_to_one_energy_basis(self):
        query_df = Mock(name="query_df")
        dataset = Mock(name="dataset")
        alexandria_dataset = [_FakeEntry()]
        materials_project_dataset = [_FakeEntry()]
        oqmd_dataset = [_FakeEntry()]
        provider_error = RuntimeError("OPTIMADE request failed with HTTP 500")

        err = io.StringIO()
        with patch.object(preset_loaders_module, "_load_from_optimade_provider",
                          side_effect=provider_error) as provider_loader, \
                patch.object(preset_loaders_module, "load_from_alexandria",
                             return_value=alexandria_dataset) as alexandria_loader, \
                patch.object(preset_loaders_module, "load_from_materials_project",
                             return_value=materials_project_dataset) as mp_loader, \
                patch.object(preset_loaders_module, "load_from_oqmd",
                             return_value=oqmd_dataset) as oqmd_loader, \
                patch.object(preset_loaders_module, "_optimade_provider_datasets_to_df",
                             return_value=query_df) as datasets_to_df, \
                patch.object(preset_loaders_module, "df2ds", return_value=dataset), \
                redirect_stderr(err):
            result = load_from_optimade.__wrapped__(
                {'Mo', 'Si'},
                providers=["alexandria", "materials_project", "oqmd"],
            )

        provider_loader.assert_called_once()
        alexandria_loader.assert_called_once()
        mp_loader.assert_called_once()
        oqmd_loader.assert_called_once()
        self.assertEqual(
            datasets_to_df.call_args.args[2],
            [alexandria_dataset, materials_project_dataset, oqmd_dataset],
        )
        self.assertIn("loading every provider through its direct client", err.getvalue())
        self.assertIs(result, dataset)

    def test_load_from_optimade_treats_empty_provider_as_fallback_trigger(self):
        empty_dataset = []
        local_dataset = [_FakeEntry()]
        query_df = Mock(name="query_df")
        result_dataset = Mock(name="result_dataset")

        with patch.object(preset_loaders_module, "_load_from_optimade_provider",
                          return_value=empty_dataset), \
                patch.object(preset_loaders_module, "load_from_materials_project",
                             return_value=local_dataset) as mp_loader, \
                patch.object(preset_loaders_module, "_optimade_provider_datasets_to_df",
                             return_value=query_df), \
                patch.object(preset_loaders_module, "df2ds", return_value=result_dataset), \
                redirect_stderr(io.StringIO()):
            result = load_from_optimade.__wrapped__(
                {'Mo', 'Si'},
                providers=["materials_project"],
            )

        mp_loader.assert_called_once()
        self.assertEqual(
            local_dataset[0].metadata["optimade_fallback"]["provider"],
            "materials_project",
        )
        self.assertIs(result, result_dataset)

    def test_optimade_default_timeout_is_long(self):
        self.assertEqual(preset_loaders_module.OptimadeClient(show_progress=False).timeout, 1000.0)

    def test_load_from_uspex_goodstructures(self):
        ds = load_from_uspex_goodstructures(self.uspex_goodStructures)
        self.assertEqual(len(ds), 442)

    def test_load_from_uspex_calc_folders(self):
        ds = load_from_uspex_calc_folders(self.uspex_calcfolders)
        self.assertEqual(len(ds), 214)

    def test_load_mattersim_estimated_set(self):
        ds = load_mattersim_estimated_set(self.csv, self.poscars_folder)
        self.assertEqual(len(ds), 7142)


    # def test_elements(self):
    #     ds = CrystalDataset.from_struct_folder(self.poscars_folder, search_pattern='*.POSCAR', skip_dump=True)
    #     self.assertEqual(ds.elements, {'N', 'Na', 'Al', 'Ni', 'Fe'})
    #
    # def test_deduplication(self):
    #     ds = CrystalDataset.from_struct_folder(self.poscars_folder, search_pattern='*.POSCAR', skip_dump=True)
    #     assert len(ds) == 348, "Dataset should contain 348 entries before deduplication"
    #     ds.tol_FP = 0.07
    #     deduped_ds, _, _ = ds.deduplicated(enforce_compositions_separation=True,
    #                                         fitness_list=None,
    #                                         reset_entries=False, skip_dump=True)
    #     self.assertEqual(len(deduped_ds),300)
    #
    # def test_filtering(self):
    #     ds = CrystalDataset.from_client(OQMDClient(), elements=['Al', 'Fe', 'Ni'], skip_dump=True)
    #     fs = ds.filter(predicate_fn=lambda e: e.e_above_hull < 0.02, reset_entries=False, skip_dump=True)
    #     print(fs.metadata["message"])
    #
    # def test_rw(self):
    #     ds = CrystalDataset.from_struct_folder(self.poscars_folder, search_pattern='*.POSCAR', skip_dump=True)
    #     ds.dump()
    #     with open(ds.pkl_path, 'rb') as f:
    #         ds2 = pkl.load(f)
    #     print(f"ds1.id: {ds.id}, ds2.id: {ds2.id}")
    #     self.assertEqual(ds.id, ds2.id)
    #     Path(ds.pkl_path).unlink()
    #     Path(ds.regfile).unlink()
    #     Path(ds.treefile).unlink()
