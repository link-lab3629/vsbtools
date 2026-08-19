import copy
import importlib
import os
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import numpy as np
import torch
from pymatgen.core import Structure

from ....crystal_entry import CrystalEntry
from ....io.zip_handling import exploded_zip_tree
from .. import mattergen_bridge
from ..mattergen_bridge import get_loss_fn, get_target_value_fn, clear_globals

FIXTURES_ROOT = Path(__file__).resolve().parents[3] / "unittests_datasets"
ZIPPED_PROCESSED_PATH = (
    FIXTURES_ROOT / "MG_postprocess_pipelines" / "PROCESSED"
)


class MattergenPathConfiguration_Test(unittest.TestCase):
    def test_editable_environment_source_and_dependencies_are_added(self):
        previous_mgen_path = mattergen_bridge.mgen_path
        previous_sys_path = list(sys.path)
        try:
            with tempfile.TemporaryDirectory() as tmp_dir:
                tmp_path = Path(tmp_dir)
                source_root = tmp_path / "scout-matter"
                dependency_root = tmp_path / "site-packages"
                for relative_path in (
                    Path("mattergen/common/data/chemgraph.py"),
                    Path("mattergen/diffusion/diffusion_loss.py"),
                ):
                    path = source_root / relative_path
                    path.parent.mkdir(parents=True, exist_ok=True)
                    path.touch()
                dependency_root.mkdir()

                with patch.dict(
                    os.environ,
                    {
                        "MATTERGEN_PYTHON_PATH": source_root.as_posix(),
                        "SCOUT_MATTER_SITE_PACKAGES": dependency_root.as_posix(),
                    },
                ):
                    mattergen_bridge.mgen_path = None
                    resolved = mattergen_bridge._configure_mattergen_path(prompt=False)

                self.assertEqual(resolved, source_root)
                self.assertIn(source_root.as_posix(), sys.path)
                self.assertIn(dependency_root.as_posix(), sys.path)
        finally:
            mattergen_bridge.mgen_path = previous_mgen_path
            sys.path[:] = previous_sys_path


class MattergenTensorConversion_Test(unittest.TestCase):
    def test_tensor_results_are_converted_without_numpy(self):
        self.assertEqual(mattergen_bridge._tensor_to_python(torch.tensor(2.5)), 2.5)
        self.assertEqual(
            mattergen_bridge._tensor_to_python(torch.tensor([1.0, 2.0])),
            [1.0, 2.0],
        )

    def test_structure_arrays_are_converted_through_python_lists(self):
        structure = MagicMock()
        structure.lattice.matrix.tolist.return_value = [
            [3.0, 0.0, 0.0],
            [0.0, 3.0, 0.0],
            [0.0, 0.0, 3.0],
        ]
        structure.frac_coords.tolist.return_value = [
            [0.0, 0.0, 0.0],
            [0.5, 0.5, 0.5],
        ]
        structure.__iter__.return_value = iter([
            SimpleNamespace(specie=SimpleNamespace(number=29)),
            SimpleNamespace(specie=SimpleNamespace(number=15)),
        ])

        with patch.object(mattergen_bridge, "_require_mattergen"):
            cell, positions, atomic_numbers = mattergen_bridge.structure_to_tensors(
                structure,
                force_gpu=0,
            )

        self.assertEqual(cell.shape, (3, 3))
        self.assertEqual(positions.shape, (2, 3))
        self.assertEqual(atomic_numbers.tolist(), [29, 15])
        structure.lattice.matrix.tolist.assert_called_once_with()
        structure.frac_coords.tolist.assert_called_once_with()


class MattergenBridge_Test(unittest.TestCase):
    def setUp(self) -> None:
        self._fixtures_context = exploded_zip_tree(ZIPPED_PROCESSED_PATH)
        self.processed_path = self._fixtures_context.__enter__()
        self.poscars_path = (
            self.processed_path / "B-Fe-Nd"
            / "B-Fe-Nd__guidance_environment_mode_huber_B-Fe_3__diffusion_loss_weight_0.5-0.5-True__algo_0"
            / "2_x204f1f3d5ffe2c98" / "POSCARS"
        )

    def tearDown(self) -> None:
        self._fixtures_context.__exit__(None, None, None)

    def test_environment_loss_target_stability(self):
        entry1 = CrystalEntry(id="agm003592845", structure=Structure.from_file(self.poscars_path / "agm003592845POSCAR"))
        mean_cn_fn = get_target_value_fn(
            "compute_mean_coordination", force_gpu=0, type_A=5, type_B=26
        )
        mean_cn = float(mean_cn_fn(entry1))
        self.assertAlmostEqual(mean_cn, 4.876739978790283, places=6)
        clear_globals()

        loss_fn_target6 = get_loss_fn('environment', force_gpu=0, target={'B-Fe': 6, 'mode': 'l1'})
        loss_target6 = float(loss_fn_target6(entry1))
        self.assertAlmostEqual(loss_target6, 1.1232600212097168, places=6)

        loss_fn_target3 = get_loss_fn('environment', force_gpu=0, target={'B-Fe': 3, 'mode': 'l1'})
        loss_target3 = float(loss_fn_target3(entry1))
        self.assertAlmostEqual(loss_target3, 1.8767399787902832, places=6)
        self.assertNotAlmostEqual(loss_target3, loss_target6, places=6)

    def test_chemgraph_compat_matches_real_chemgraph_for_descriptors(self):
        try:
            importlib.import_module("torch_geometric")
            real_chemgraph_module = importlib.import_module("mattergen.common.data.chemgraph")
            real_diffusion_loss = importlib.import_module("mattergen.diffusion.diffusion_loss")
        except ImportError as exc:
            self.skipTest(f"Real MatterGen ChemGraph is unavailable: {exc}")

        compat_import = mattergen_bridge._import_diffusion_loss_with_chemgraph_compat(restore_modules=True)
        (
            CompatChemGraph,
            compat_loss_registry,
            _compat_soft_counts,
            compat_clear_globals,
            compat_compute_mean_coordination,
            _compat_compute_target_coordination_share,
            _compat_volume,
            compat_volume_pa,
        ) = compat_import

        struct = Structure.from_file(self.poscars_path / "agm003592845POSCAR")
        cell = torch.tensor(struct.lattice.matrix.tolist(), dtype=torch.float32)
        frac = torch.tensor(struct.frac_coords.tolist(), dtype=torch.float32, requires_grad=True)
        atomic_numbers = torch.tensor([site.specie.number for site in struct], dtype=torch.int64)
        num_atoms = torch.tensor([len(atomic_numbers)])

        real_x = real_chemgraph_module.ChemGraph(
            cell=cell, atomic_numbers=atomic_numbers, pos=frac, num_atoms=num_atoms
        )
        compat_x = CompatChemGraph(
            cell=cell, atomic_numbers=atomic_numbers, pos=frac, num_atoms=num_atoms
        )

        np.testing.assert_allclose(
            real_diffusion_loss.volume_pa(real_x, t=None).detach().cpu().tolist(),
            compat_volume_pa(compat_x, t=None).detach().cpu().tolist(),
            rtol=1e-6,
            atol=1e-7,
        )

        np.testing.assert_allclose(
            real_diffusion_loss.compute_mean_coordination(
                cell, frac, atomic_numbers, num_atoms, type_A=5, type_B=26
            ).detach().cpu().tolist(),
            compat_compute_mean_coordination(
                cell, frac, atomic_numbers, num_atoms, type_A=5, type_B=26
            ).detach().cpu().tolist(),
            rtol=1e-6,
            atol=1e-7,
        )

        target = {"B-Fe": 3, "mode": "l1"}
        real_diffusion_loss.clear_globals()
        compat_clear_globals()
        np.testing.assert_allclose(
            real_diffusion_loss.LOSS_REGISTRY["environment"](
                real_x, t=None, target=copy.deepcopy(target)
            ).detach().cpu().tolist(),
            compat_loss_registry["environment"](
                compat_x, t=None, target=copy.deepcopy(target)
            ).detach().cpu().tolist(),
            rtol=1e-6,
            atol=1e-7,
        )
