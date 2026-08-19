import unittest
import os
import shutil
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import Mock, patch
from ...io.yaml_csv_poscars import write, read
from .. import poll_databases as poll_databases_module
from ..poll_databases import poll_databases
from ...analysis.summary import collect_summary_df, print_pretty_df


PATH_WITH_TESTS = Path(__file__).resolve().parent


def _repo_root() -> Path:
    for path in (PATH_WITH_TESTS, *PATH_WITH_TESTS.parents):
        if (path / ".git").exists():
            return path
    return PATH_WITH_TESTS.parents[4]


REPO_ROOT = _repo_root()


def _uspex_db_files() -> set[Path]:
    return set(REPO_ROOT.rglob("uspex.db"))


def _remove_paths(*paths: Path):
    for path in paths:
        if path.is_dir():
            shutil.rmtree(path)
        elif path.exists():
            path.unlink()


class _FakeEntry:
    def __init__(self, entry_id, energy=-1.0):
        self.id = entry_id
        self.energy = energy

    def copy_with(self, **kw):
        return _FakeEntry(self.id, energy=kw.get("energy", self.energy))


class _FakeDataset:
    def __init__(self, entries):
        self.entries = list(entries)
        self.metadata = {}

    def __iter__(self):
        return iter(self.entries)

    def __len__(self):
        return len(self.entries)

    def filter(self, predicate):
        return _FakeDataset(entry for entry in self.entries if predicate(entry))

    def merge(self, other):
        return _FakeDataset([*self.entries, *other.entries])


class yaml_csv_poscars_Test(unittest.TestCase):

    def setUp(self) -> None:
        self.elements = {'La', 'Te', 'C'} # , 'P'}
        self._existing_uspex_dbs = _uspex_db_files()

    def tearDown(self) -> None:
        for path in _uspex_db_files() - self._existing_uspex_dbs:
            path.unlink()

    def test_scrape(self):
        if os.getenv("VSBTOOLS_RUN_EXTERNAL_DB_TESTS") != "1":
            self.skipTest("Set VSBTOOLS_RUN_EXTERNAL_DB_TESTS=1 to run live database scrape test")
        ds = poll_databases(self.elements, do_ehull_filtering=True,
                            loader_kwargs={"alexandria": {'pattern': 'alexandria_00*.json'}})
        write(ds, enforce_base_path=PATH_WITH_TESTS / "ds3")
        print_pretty_df(collect_summary_df(ds, native_columns=("id", "composition", "energy", "metadata.duplicates")), PATH_WITH_TESTS / 'table.txt')
        ds_read = read(PATH_WITH_TESTS / 'ds3/manifest.yaml')
        print_pretty_df(collect_summary_df(ds_read, native_columns=("id", "composition", "energy", "metadata.duplicates")),
                        PATH_WITH_TESTS / 'table2.txt')
        write(ds_read, enforce_base_path=PATH_WITH_TESTS / "ds2")
        self.assertEqual(len(ds), 146)
        _remove_paths(
            PATH_WITH_TESTS / "ds2",
            PATH_WITH_TESTS / "ds3",
            PATH_WITH_TESTS / "table.txt",
            PATH_WITH_TESTS / "table2.txt",
        )

    def test_default_sources_are_hull_filtered_independently(self):
        datasets = {
            "al": _FakeDataset([_FakeEntry("al1")]),
            "oq": _FakeDataset([_FakeEntry("oq1")]),
            "ma": _FakeDataset([_FakeEntry("mp1")]),
            "op": _FakeDataset([_FakeEntry("op1")]),
        }

        def optimade_loader(elements, **kwargs):
            if kwargs.get("providers"):
                raise RuntimeError("optimade unavailable")
            return datasets["op"]

        loaders = {name: Mock(return_value=dataset) for name, dataset in datasets.items()}
        loaders["op"] = Mock(side_effect=optimade_loader)

        with TemporaryDirectory() as tmpdir, \
                patch.object(poll_databases_module, "LOADERS", loaders), \
                patch.object(poll_databases_module, "load_from_optimade", loaders["op"]), \
                patch.object(poll_databases_module, "PhaseDiagramTools") as phase_diagram_tools, \
                patch.object(poll_databases_module, "write"):
            phase_diagram_tools.return_value.height_above_hull_pa.return_value = 0.0
            ds = poll_databases(
                {"Si"},
                pref_db="op",
                do_deduplication=False,
                cache_root_path=Path(tmpdir),
            )

        self.assertEqual(phase_diagram_tools.call_count, 4)
        self.assertEqual({entry.id for entry in ds}, {"al1", "oq1", "mp1", "op1"})
        self.assertEqual(
            ds.metadata["database_names"],
            ["alexandria", "oqmd", "MatProj", "optimade"],
        )
        self.assertEqual(ds.metadata["preferred_database"], "op")

    def test_poll_databases_accepts_optimade_source(self):
        optimade_loader = Mock(return_value=_FakeDataset([_FakeEntry("op1")]))

        with TemporaryDirectory() as tmpdir, \
                patch.object(poll_databases_module, "LOADERS", {"op": optimade_loader}), \
                patch.object(poll_databases_module, "write") as write_mock:
            ds = poll_databases(
                {"Si"},
                database_names=["optimade"],
                pref_db="op",
                do_ehull_filtering=False,
                do_deduplication=False,
                loader_kwargs={"optimade": {"providers": ["oqmd"], "page_limit": 3}},
                cache_root_path=Path(tmpdir),
            )

        optimade_loader.assert_called_once_with({"Si"}, providers=["oqmd"], page_limit=3)
        write_mock.assert_called_once()
        self.assertEqual(len(ds), 1)
        self.assertIsNone(ds[0].energy)

    def test_poll_databases_uses_optimade_before_local_supported_source(self):
        local_loader = Mock(return_value=_FakeDataset([_FakeEntry("local1")]))
        optimade_loader = Mock(return_value=_FakeDataset([_FakeEntry("op1")]))

        with TemporaryDirectory() as tmpdir, \
                patch.object(poll_databases_module, "LOADERS", {"al": local_loader, "op": optimade_loader}), \
                patch.object(poll_databases_module, "load_from_optimade", optimade_loader), \
                patch.object(poll_databases_module, "write"):
            ds = poll_databases(
                {"Si"},
                database_names=["alexandria"],
                pref_db="al",
                do_ehull_filtering=False,
                do_deduplication=False,
                loader_kwargs={"op": {"page_limit": 2}},
                cache_root_path=Path(tmpdir),
            )

        optimade_loader.assert_called_once_with({"Si"}, page_limit=2, providers=["alexandria"])
        local_loader.assert_not_called()
        self.assertEqual(len(ds), 1)
        self.assertIsNone(ds[0].energy)

    def test_poll_databases_falls_back_to_local_when_optimade_fails(self):
        local_loader = Mock(return_value=_FakeDataset([_FakeEntry("local1")]))
        optimade_loader = Mock(side_effect=RuntimeError("optimade unavailable"))

        with TemporaryDirectory() as tmpdir, \
                patch.object(poll_databases_module, "LOADERS", {"al": local_loader, "op": optimade_loader}), \
                patch.object(poll_databases_module, "load_from_optimade", optimade_loader), \
                patch.object(poll_databases_module, "write"):
            ds = poll_databases(
                {"Si"},
                database_names=["alexandria"],
                pref_db="al",
                do_ehull_filtering=False,
                do_deduplication=False,
                loader_kwargs={"op": {"page_limit": 2}},
                cache_root_path=Path(tmpdir),
            )

        optimade_loader.assert_called_once_with({"Si"}, page_limit=2, providers=["alexandria"])
        local_loader.assert_called_once_with({"Si"}, prompt=False)
        self.assertEqual(len(ds), 1)
        self.assertIsNone(ds[0].energy)
