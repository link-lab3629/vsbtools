from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
from pathlib import Path
from typing import Callable, Iterable, Mapping


class ExternalPathResolutionError(RuntimeError):
    """Raised when an external dependency path cannot be resolved."""


PathValidator = Callable[[Path], tuple[bool, str]]
PathNormalizer = Callable[[Path], Path]

CONFIG_ENV_VAR = "VSBTOOLS_EXTERNAL_PATHS_CONFIG"
PRESETS_ENV_VAR = "VSBTOOLS_EXTERNAL_PATHS_PRESETS"


def managed_sibling_venv(name: str, prefix: str | Path | None = None) -> Path | None:
    """Find a sibling venv created by the reusable workflow installer."""

    active_venv = Path(prefix or sys.prefix).expanduser()
    if active_venv.name != "vsbtools" or active_venv.parent.name != "venvs":
        return None
    candidate = active_venv.parent / name
    if not (candidate / "pyvenv.cfg").is_file():
        return None
    return candidate


def default_config_path() -> Path:
    return Path(os.environ.get(CONFIG_ENV_VAR, "~/.config/vsbtools/external_paths.json")).expanduser()


def default_presets_path() -> Path:
    return Path(os.environ.get(PRESETS_ENV_VAR, Path(__file__).with_name("external_paths_presets.json"))).expanduser()


def _load_mapping(path: Path) -> dict:
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}
    return data if isinstance(data, dict) else {}


def _load_config(config_path: Path | None = None) -> dict[str, str]:
    return _load_mapping(config_path or default_config_path())


def _load_host_presets(presets_path: Path | None = None, hostname: str | None = None) -> dict[str, str]:
    presets = _load_mapping(presets_path or default_presets_path())
    host_presets = presets.get(hostname or socket.gethostname(), {})
    return host_presets if isinstance(host_presets, dict) else {}


def _save_config(config: Mapping[str, str], config_path: Path | None = None) -> None:
    config_path = config_path or default_config_path()
    config_path.parent.mkdir(parents=True, exist_ok=True)
    config_path.write_text(json.dumps(dict(config), indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _as_path(value: str | Path) -> Path:
    return Path(value).expanduser()


def _validate(path: Path, validator: PathValidator | None) -> tuple[bool, str]:
    if validator is None:
        return (path.exists(), f"{path} does not exist")
    return validator(path)


def _format_errors(errors: Iterable[tuple[str, Path, str]]) -> str:
    return "\n".join(f"- {label}: {path} ({message})" for label, path, message in errors)


def resolve_external_path(
    *,
    name: str,
    config_key: str,
    env_var: str | None = None,
    explicit_path: str | Path | None = None,
    validator: PathValidator | None = None,
    normalizer: PathNormalizer | None = None,
    prompt: bool = True,
    required: bool = True,
    prompt_text: str | None = None,
) -> Path | None:
    """Resolve, validate, and optionally prompt for an external resource path.

    Candidate order is explicit path, environment variable, then saved local
    config. Manually entered valid paths are persisted under
    ``~/.config/vsbtools/external_paths.json`` so first-time setup is not
    repeated on every import.
    """
    normalizer = normalizer or (lambda path: path)
    config_path = default_config_path()
    presets_path = default_presets_path()
    hostname = socket.gethostname()
    config = _load_config()
    host_presets = _load_host_presets(presets_path, hostname)
    candidates: list[tuple[str, str | Path]] = []

    if explicit_path is not None:
        candidates.append(("provided path", explicit_path))
    if env_var and os.environ.get(env_var):
        candidates.append((f"${env_var}", os.environ[env_var]))
    if config_key in config:
        candidates.append((f"{config_path}:{config_key}", config[config_key]))
    if config_key in host_presets:
        candidates.append((f"{presets_path}:{hostname}.{config_key}", host_presets[config_key]))

    errors: list[tuple[str, Path, str]] = []
    for label, candidate in candidates:
        path = normalizer(_as_path(candidate))
        ok, message = _validate(path, validator)
        if ok:
            return path
        errors.append((label, path, message))

    if not prompt:
        if required:
            details = _format_errors(errors)
            raise ExternalPathResolutionError(
                f"{name} path is not configured or invalid."
                + (f"\n{details}" if details else "")
            )
        return None

    prompt_text = prompt_text or f"Enter path to {name}: "
    if errors:
        print(f"Could not validate configured {name} path(s):", file=sys.stderr)
        print(_format_errors(errors), file=sys.stderr)

    while True:
        try:
            raw_path = input(prompt_text).strip()
        except EOFError as exc:
            if required:
                raise ExternalPathResolutionError(f"{name} path is required.") from exc
            return None

        if raw_path.lower() in {"q", "quit", "exit"}:
            raise SystemExit(1)
        if not raw_path:
            print("Empty path is not valid.", file=sys.stderr)
            continue

        path = normalizer(_as_path(raw_path))
        ok, message = _validate(path, validator)
        if ok:
            config[config_key] = path.as_posix()
            _save_config(config)
            return path

        print(f"Invalid {name} path: {message}", file=sys.stderr)
        try:
            choice = input("Enter 'r' to re-enter the path or 'q' to quit [r/q]: ").strip().lower()
        except EOFError as exc:
            if required:
                raise ExternalPathResolutionError(f"{name} path is required.") from exc
            return None
        if choice in {"q", "quit", "exit"}:
            raise SystemExit(1)


def add_sys_path(path: str | Path, *, prepend: bool = True) -> None:
    path_str = Path(path).as_posix()
    if path_str in sys.path:
        return
    if prepend:
        sys.path.insert(0, path_str)
    else:
        sys.path.append(path_str)


def glob_validator(pattern: str, *, description: str | None = None) -> PathValidator:
    description = description or pattern

    def _validator(path: Path) -> tuple[bool, str]:
        if not path.is_dir():
            return False, f"{path} is not a directory"
        if not any(path.glob(pattern)):
            return False, f"no {description} files matching {pattern!r}"
        return True, ""

    return _validator


def import_from_path_validator(modules: str | Iterable[str]) -> PathValidator:
    module_names = (modules,) if isinstance(modules, str) else tuple(modules)

    def _validator(path: Path) -> tuple[bool, str]:
        if not path.exists():
            return False, f"{path} does not exist"
        env = os.environ.copy()
        env["PYTHONPATH"] = path.as_posix() + (
            os.pathsep + env["PYTHONPATH"] if env.get("PYTHONPATH") else ""
        )
        cmd = [
            sys.executable,
            "-c",
            "import importlib; "
            + "; ".join(f"importlib.import_module({module_name!r})" for module_name in module_names),
        ]
        try:
            proc = subprocess.run(cmd, text=True, capture_output=True, timeout=60, env=env)
        except Exception as exc:
            return False, f"could not run import check: {exc}"
        if proc.returncode != 0:
            stderr = proc.stderr.strip().splitlines()
            detail = stderr[-1] if stderr else f"exit code {proc.returncode}"
            return False, f"could not import {', '.join(module_names)}: {detail}"
        return True, ""

    return _validator


def python_executable_from_venv(path: Path) -> Path:
    if path.is_dir():
        return path / "bin" / "python"
    return path


def python_import_validator(modules: str | Iterable[str]) -> PathValidator:
    module_names = (modules,) if isinstance(modules, str) else tuple(modules)

    def _validator(path: Path) -> tuple[bool, str]:
        if not path.is_file():
            return False, f"{path} is not a Python executable"
        cmd = [
            path.as_posix(),
            "-c",
            "import importlib; "
            + "; ".join(f"importlib.import_module({module_name!r})" for module_name in module_names),
        ]
        try:
            proc = subprocess.run(cmd, text=True, capture_output=True, timeout=60)
        except Exception as exc:
            return False, f"could not run {path}: {exc}"
        if proc.returncode != 0:
            stderr = proc.stderr.strip().splitlines()
            detail = stderr[-1] if stderr else f"exit code {proc.returncode}"
            return False, f"could not import {', '.join(module_names)}: {detail}"
        return True, ""

    return _validator
