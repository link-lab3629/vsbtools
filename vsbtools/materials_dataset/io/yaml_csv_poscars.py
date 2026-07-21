import ast
import csv
import os
import re
import tempfile
import zipfile
from collections.abc import Iterable
from typing import Dict, Any
from pathlib import Path
import yaml
from pymatgen.core import Structure
from ..crystal_dataset import CrystalDataset, CrystalEntry

def load_yaml_recursively(yaml_fname=None, raw=None, ym_dict=None):
    if yaml_fname is not None:
        with open(yaml_fname) as ym_fid:
            raw = ym_fid.read()
    if raw is not None:
        ym_dict = yaml.safe_load(raw)
    if ym_dict is None:
        return None

    # Only iterate mappings
    if not isinstance(ym_dict, dict):
        return ym_dict

    for k, v in list(ym_dict.items()):
        if isinstance(v, str) and k not in ['message']:
            try:
                loaded = yaml.safe_load(v)
            except yaml.YAMLError:
                continue
            if isinstance(loaded, dict):
                ym_dict[k] = load_yaml_recursively(ym_dict=loaded)
            else:
                # keep original string if it doesn't load to a mapping
                ym_dict[k] = v
        elif isinstance(v, dict):
            ym_dict[k] = load_yaml_recursively(ym_dict=v)

    return ym_dict


def _get_str_value_for_csv(e: CrystalEntry, attr_name):
    if attr_name == 'structure':
        val = e.poscarname
    elif 'metadata.' in attr_name:
        metadata = e.metadata if isinstance(e.metadata, dict) else {}
        val = metadata.get(attr_name.split('.')[-1], 'NA')
    else:
        val = getattr(e, attr_name)
    if isinstance(val, float):
        return f"{val:.6f}"
    return str(val).strip()


def _parse_metadata_value(val: str):
    if val in ['NA', 'None', '']:
        return None
    if val == 'set()':
        return set()
    if val in ['True', 'False']:
        return val == 'True'
    if not val or val[0] not in ("{", "[", "(", "\'", '"'):
        return val

    try:
        return ast.literal_eval(val)
    except (SyntaxError, ValueError):
        repaired = re.sub(r"(?<=[}\]'\"])\s+('(?:[^'\\]|\\.)+'\s*:)", r", \1", val)
        try:
            return ast.literal_eval(repaired)
        except (SyntaxError, ValueError):
            return val

def _remove_private_keys(dct, recursive=True):
    for key in [k for k in dct if k.startswith('_')]:
        if isinstance(dct[key], dict) and recursive:
            _remove_private_keys(dct[key])
        else:
            dct.pop(key)

def _prepare_for_yaml_write(dct: dict):
    for k, v in dct.items():
        if isinstance(v, dict):
            _prepare_for_yaml_write(v)
        elif isinstance(v, Path):
            dct[k] = v.as_posix()


def read(manifest_yaml: str | Path) -> CrystalDataset:
    manifest_yaml = Path(manifest_yaml)
    def _rebase_path(pth: Path, base: Path):
        return pth if pth.is_absolute() else base / pth
    dataset_info = load_yaml_recursively(yaml_fname=manifest_yaml)
    dataset_info.pop("comment")
    _remove_private_keys(dataset_info)
    entry_descr_csv = _rebase_path(Path(dataset_info.pop('entries_csv')), manifest_yaml.parent)
    poscars_dir = _rebase_path(Path(dataset_info.pop('poscars')), manifest_yaml.parent)
    dataset = read_csv_poscars(entry_descr_csv, poscars_dir=poscars_dir, use_fname_as_id=False)
    for k in dataset_info:
        setattr(dataset, k, dataset_info[k])
    dataset.override_base_path(manifest_yaml.parent)
    return dataset


def write(dataset: CrystalDataset, enforce_base_path: str | Path | None = None, comment=None, **kwargs):
    if enforce_base_path:
        dataset.override_base_path(Path(enforce_base_path))
    dataset.base_path.mkdir(parents=True, exist_ok=True)
    manifest_yaml = dataset.base_path / "manifest.yaml"
    csv_file = manifest_yaml.with_name('data.csv')
    poscars_path = manifest_yaml.with_name('POSCARS.zip')
    write_csv_poscars(dataset, csv_file, poscars_path, **kwargs)
    ds_dict = dataset.__dict__.copy()
    _remove_private_keys(ds_dict)
    _prepare_for_yaml_write(ds_dict)
    ds_dict["entries_csv"] = csv_file.relative_to(manifest_yaml.parent).as_posix()
    ds_dict["poscars"] = poscars_path.relative_to(manifest_yaml.parent).as_posix()
    ds_dict["comment"] = comment
    with open(manifest_yaml, 'wt') as ds_desc:
        yaml.dump(ds_dict, ds_desc)
    print(f"Data saved to {dataset.base_path.as_posix()}")


def _load_structures_from_poscars(poscars_path: Path, structure_refs: list[str]) -> dict[str, Structure]:
    if poscars_path.is_dir():
        return {ref: Structure.from_file(poscars_path / ref) for ref in set(structure_refs)}
    if poscars_path.is_file():
        with tempfile.TemporaryDirectory() as tmpdir:
            with zipfile.ZipFile(poscars_path) as archive:
                archive.extractall(tmpdir)
            root = Path(tmpdir)
            return {ref: Structure.from_file(root / ref) for ref in set(structure_refs)}
    raise FileNotFoundError(f"POSCARS path does not exist: {poscars_path}")


def read_csv_poscars(csv_file, poscars_dir=None, use_fname_as_id=True) -> CrystalDataset:
    csv_file = Path(csv_file)
    if poscars_dir:
        poscars_dir = Path(poscars_dir)
    else:
        poscars_dir = csv_file.with_name(csv_file.stem + 'POSCARS.zip')
        legacy_poscars_dir = csv_file.with_name(csv_file.stem + 'POSCARS')
        if not poscars_dir.exists() and legacy_poscars_dir.exists():
            poscars_dir = legacy_poscars_dir
    dataset_ID = csv_file.stem if use_fname_as_id else None
    with open(csv_file, 'rt', newline='') as csv_h:
        reader = csv.DictReader(csv_h)
        labels = reader.fieldnames or []
        entries_data = []
        structure_refs = []
        for i, row in enumerate(reader):
            entry_data: Dict[str, Any] = {k: (v.strip() if isinstance(v, str) else v) for k, v in row.items() if k is not None}
            entry_data["metadata"] = dict()
            if not "id" in labels:
                entry_data["id"] = str(i)
            if 'energy' in entry_data:
                entry_data['energy'] = float(entry_data['energy']) if entry_data['energy'] != 'None' else None
            if 'structure' in entry_data:
                structure_refs.append(entry_data.pop('structure'))
            for l in labels:
                if 'metadata.' in l:
                    val = entry_data.pop(l)
                    entry_data["metadata"][l.split('.')[-1]] = _parse_metadata_value(val)
            entry_keys = [k for k in entry_data if k in CrystalEntry.__annotations__.keys()]
            entry_data = {k: entry_data[k] for k in entry_keys}
            entries_data.append(entry_data)
    if 'structure' in labels:
        structures = _load_structures_from_poscars(poscars_dir, structure_refs)
        for entry_data, structure_ref in zip(entries_data, structure_refs):
            entry_data["structure"] = structures[structure_ref]
    entries = [CrystalEntry(**entry_data) for entry_data in entries_data]
    return CrystalDataset(entries,
                          dataset_id=dataset_ID,
                          message=f'Loaded from {csv_file}',
                          base_path=csv_file.parent,
                          )

def write_csv_poscars(ds: CrystalDataset,
          csv_file: str | Path | None = None,
          poscars_path: str | Path | None = None,
          labels: list[str] | None = None):

    labels = (labels or (["id", "composition", "energy", "structure"]
              + [f"metadata.{k}" for k in gather_metadata_fields(ds)]))
    base_path = getattr(ds, "basepath", Path(os.getcwd()))
    base_path.mkdir(exist_ok=True)
    csv_file = csv_file or base_path / 'data.csv'
    poscars_path = poscars_path or csv_file.with_name(csv_file.stem + 'POSCARS.zip')
    with open(csv_file, 'wt', newline='') as csv_h:
        writer = csv.writer(csv_h)
        writer.writerow(labels)
        with tempfile.TemporaryDirectory() as tmpdir:
            poscars_dir = Path(tmpdir)
            poscar_refs = []
            for e in ds:
                writer.writerow([_get_str_value_for_csv(e, label) for label in labels])
                structure_ref = _get_str_value_for_csv(e, "structure")
                poscar_file = poscars_dir / structure_ref
                poscar_file.parent.mkdir(parents=True, exist_ok=True)
                e.structure.to(fmt="poscar", filename=poscar_file, comment=e.id)
                poscar_refs.append((poscar_file, structure_ref.replace('\\', '/')))
            with zipfile.ZipFile(poscars_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
                for poscar_file, structure_ref in poscar_refs:
                    archive.writestr(structure_ref, poscar_file.read_bytes())


def gather_metadata_fields(dataset):
    fields = set()
    for e in dataset:
        if isinstance(e.metadata, dict):
            fields |= set(e.metadata.keys())
    return list(fields)
