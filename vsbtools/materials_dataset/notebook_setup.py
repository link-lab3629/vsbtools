"""Small user-facing helpers for configuring materials-analysis notebooks."""

from __future__ import annotations

import os
import subprocess
import warnings
from dataclasses import dataclass
from pathlib import Path

from .external_paths import managed_sibling_venv


@dataclass(frozen=True)
class NotebookExternalEnvironment:
    """Resolved external paths used by a materials-analysis notebook."""

    mattergen_import_root: Path | None
    mattergen_site_packages: Path | None
    grace_python: Path | None

    def summary_lines(self) -> list[str]:
        mattergen = self.mattergen_import_root or "environment/config fallback"
        grace = self.grace_python or "environment/config fallback"
        return [f"MatterGen: {mattergen}", f"GRACE: {grace}"]


def _optional_path(value: str | Path | None) -> Path | None:
    if value in (None, ""):
        return None
    path = Path(os.path.abspath(Path(value).expanduser()))
    if not path.exists():
        raise FileNotFoundError(path)
    return path


def _venv_python(path: Path) -> Path:
    candidates = (path / "bin" / "python", path / "Scripts" / "python.exe")
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    raise FileNotFoundError(f"No Python executable found in virtual environment {path}")


def _python_output(python: Path, code: str, description: str) -> Path:
    proc = subprocess.run(
        [python.as_posix(), "-c", code],
        text=True,
        capture_output=True,
        timeout=60,
    )
    if proc.returncode != 0:
        detail = proc.stderr.strip().splitlines()[-1] if proc.stderr.strip() else f"exit code {proc.returncode}"
        raise RuntimeError(f"Could not resolve {description} from {python}: {detail}")
    path = Path(proc.stdout.strip()).expanduser().resolve()
    if not path.exists():
        raise FileNotFoundError(path)
    return path


def _mattergen_paths(value: str | Path | None) -> tuple[Path | None, Path | None]:
    path = _optional_path(value)
    if path is None:
        import_root = _optional_path(os.environ.get("MATTERGEN_PYTHON_PATH"))
        site_packages = _optional_path(os.environ.get("SCOUT_MATTER_SITE_PACKAGES"))
        if import_root is not None or site_packages is not None:
            return import_root, site_packages
        managed_venv = managed_sibling_venv("scout-matter")
        if managed_venv is None:
            return None, None
        path = managed_venv

    python = None
    if path.is_file():
        python = path
    elif (path / "pyvenv.cfg").is_file():
        python = _venv_python(path)

    if python is None:
        if not (path / "mattergen").is_dir():
            raise FileNotFoundError(f"MatterGen package directory not found under {path}")
        return path, None

    import_root = _python_output(
        python,
        "from pathlib import Path; import mattergen; "
        "print(Path(mattergen.__file__).resolve().parent.parent)",
        "MatterGen import root",
    )
    site_packages = _python_output(
        python,
        'import sysconfig; print(sysconfig.get_paths()["purelib"])',
        "site-packages",
    )
    if not (import_root / "mattergen").is_dir():
        raise FileNotFoundError(import_root / "mattergen")
    return import_root, site_packages


def _grace_python(value: str | Path | None) -> Path | None:
    path = _optional_path(value)
    if path is None:
        path = _optional_path(managed_sibling_venv("grace"))
        if path is None:
            path = _optional_path(os.environ.get("GRACE_PYTHON"))
        if path is None:
            return None
    if path.is_dir():
        path = _venv_python(path)
    if not path.is_file():
        raise FileNotFoundError(path)
    return path


def configure_notebook_external_environments(
    *,
    mattergen: str | Path | None = None,
    grace: str | Path | None = None,
    quiet_optional_imports: bool = True,
) -> NotebookExternalEnvironment:
    """Configure MatterGen and GRACE from venvs, executables, or a source tree.

    ``None`` uses environment variables first, then discovers sibling managed
    venvs from an active ``venvs/vsbtools`` environment. Explicit MatterGen
    venvs are resolved to both their import root and their site-packages
    directory so editable installs work in the notebook kernel.
    """
    if quiet_optional_imports:
        os.environ.setdefault("TF_CPP_MIN_LOG_LEVEL", "3")
        os.environ.setdefault("TF_USE_LEGACY_KERAS", "1")
        warnings.filterwarnings("ignore", message=".*enabling the new type promotion.*")
        warnings.filterwarnings(
            "ignore",
            message="An issue occurred while importing '.*'. Disabling its usage.*",
            category=UserWarning,
        )
        warnings.filterwarnings("ignore", message="IProgress not found.*", category=Warning)

    mattergen_import_root, mattergen_site_packages = _mattergen_paths(mattergen)
    grace_python = _grace_python(grace)

    if mattergen_import_root is not None:
        os.environ["MATTERGEN_PYTHON_PATH"] = mattergen_import_root.as_posix()
    if mattergen_site_packages is not None:
        os.environ["SCOUT_MATTER_SITE_PACKAGES"] = mattergen_site_packages.as_posix()
    if grace_python is not None:
        os.environ["GRACE_PYTHON"] = grace_python.as_posix()

    return NotebookExternalEnvironment(
        mattergen_import_root=mattergen_import_root,
        mattergen_site_packages=mattergen_site_packages,
        grace_python=grace_python,
    )
