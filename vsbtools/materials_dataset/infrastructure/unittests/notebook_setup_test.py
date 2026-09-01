import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from vsbtools.materials_dataset.notebook_setup import (
    configure_notebook_external_environments,
)


class NotebookSetupTest(unittest.TestCase):
    def test_accepts_mattergen_source_tree_and_grace_venv(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            mattergen_root = root / "scout-matter"
            (mattergen_root / "mattergen").mkdir(parents=True)
            grace_venv = root / "grace"
            grace_python = grace_venv / "bin" / "python"
            grace_python.parent.mkdir(parents=True)
            grace_python.touch()

            with patch.dict(os.environ, {}, clear=True):
                result = configure_notebook_external_environments(
                    mattergen=mattergen_root,
                    grace=grace_venv,
                    quiet_optional_imports=False,
                )

                self.assertEqual(result.mattergen_import_root, mattergen_root)
                self.assertIsNone(result.mattergen_site_packages)
                self.assertEqual(result.grace_python, grace_python)
                self.assertEqual(os.environ["MATTERGEN_PYTHON_PATH"], mattergen_root.as_posix())
                self.assertEqual(os.environ["GRACE_PYTHON"], grace_python.as_posix())

    def test_resolves_editable_mattergen_venv(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            mattergen_venv = root / "mattergen-venv"
            mattergen_python = mattergen_venv / "bin" / "python"
            mattergen_python.parent.mkdir(parents=True)
            mattergen_python.touch()
            (mattergen_venv / "pyvenv.cfg").touch()

            import_root = root / "mattergen-source"
            (import_root / "mattergen").mkdir(parents=True)
            site_packages = mattergen_venv / "lib" / "python3.11" / "site-packages"
            site_packages.mkdir(parents=True)

            completed = [
                Mock(returncode=0, stdout=f"{import_root}\n", stderr=""),
                Mock(returncode=0, stdout=f"{site_packages}\n", stderr=""),
            ]
            with patch.dict(os.environ, {}, clear=True), patch(
                "vsbtools.materials_dataset.notebook_setup.subprocess.run",
                side_effect=completed,
            ) as run:
                result = configure_notebook_external_environments(
                    mattergen=mattergen_venv,
                    quiet_optional_imports=False,
                )

                self.assertEqual(run.call_count, 2)
                self.assertEqual(result.mattergen_import_root, import_root)
                self.assertEqual(result.mattergen_site_packages, site_packages)
                self.assertEqual(os.environ["MATTERGEN_PYTHON_PATH"], import_root.as_posix())
                self.assertEqual(os.environ["SCOUT_MATTER_SITE_PACKAGES"], site_packages.as_posix())

    def test_none_uses_existing_environment_variables(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            mattergen_root = root / "mattergen-source"
            mattergen_root.mkdir()
            site_packages = root / "site-packages"
            site_packages.mkdir()
            grace_python = root / "grace-python"
            grace_python.touch()
            environment = {
                "MATTERGEN_PYTHON_PATH": mattergen_root.as_posix(),
                "SCOUT_MATTER_SITE_PACKAGES": site_packages.as_posix(),
                "GRACE_PYTHON": grace_python.as_posix(),
            }

            with patch.dict(os.environ, environment, clear=True):
                result = configure_notebook_external_environments(
                    quiet_optional_imports=False,
                )

            self.assertEqual(result.mattergen_import_root, mattergen_root)
            self.assertEqual(result.mattergen_site_packages, site_packages)
            self.assertEqual(result.grace_python, grace_python)

    def test_none_discovers_sibling_installer_environments(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            venvs = root / "venvs"
            vsbtools_venv = venvs / "vsbtools"
            scout_venv = venvs / "scout-matter"
            grace_venv = venvs / "grace"
            for venv in (vsbtools_venv, scout_venv, grace_venv):
                (venv / "bin").mkdir(parents=True)
                (venv / "bin" / "python").touch()
                (venv / "pyvenv.cfg").touch()

            import_root = root / "scout-matter-source"
            (import_root / "mattergen").mkdir(parents=True)
            site_packages = scout_venv / "lib" / "python3.12" / "site-packages"
            site_packages.mkdir(parents=True)
            completed = [
                Mock(returncode=0, stdout=f"{import_root}\n", stderr=""),
                Mock(returncode=0, stdout=f"{site_packages}\n", stderr=""),
            ]

            with patch.dict(os.environ, {}, clear=True), patch(
                "vsbtools.materials_dataset.external_paths.sys.prefix",
                vsbtools_venv.as_posix(),
            ), patch(
                "vsbtools.materials_dataset.notebook_setup.subprocess.run",
                side_effect=completed,
            ):
                result = configure_notebook_external_environments(
                    quiet_optional_imports=False,
                )

            self.assertEqual(result.mattergen_import_root, import_root)
            self.assertEqual(result.mattergen_site_packages, site_packages)
            self.assertEqual(result.grace_python, grace_venv / "bin" / "python")

    def test_grace_python_venv_symlink_is_preserved(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            system_python = root / "system" / "python3.12"
            system_python.parent.mkdir()
            system_python.touch()
            grace_python = root / "grace" / "bin" / "python"
            grace_python.parent.mkdir(parents=True)
            grace_python.symlink_to(system_python)

            with patch.dict(
                os.environ,
                {"GRACE_PYTHON": grace_python.as_posix()},
                clear=True,
            ):
                result = configure_notebook_external_environments(
                    quiet_optional_imports=False,
                )
                configured_grace_python = os.environ["GRACE_PYTHON"]

            self.assertEqual(result.grace_python, grace_python)
            self.assertEqual(configured_grace_python, grace_python.as_posix())


if __name__ == "__main__":
    unittest.main()
