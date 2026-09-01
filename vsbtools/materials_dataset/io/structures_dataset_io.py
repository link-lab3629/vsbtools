from __future__ import annotations

"""StructureDatasetIO – read/write utilities for CrystalDataset

Features
--------
* **Load** structures from a directory tree that may contain nested zip archives.
  Archive exploration is optional via *expand_archives* (default **True**).
* **Load** structures from a multi‑image POSCARS file.
* **Dump** individual POSCAR files for each entry.
* **Dump** a combined multi‑image POSCARS file (plus optional plain‑text ID list).

Zip handling (copy‑then‑explode with directory‑hierarchy preservation, akin to
`find … -name '*.zip' -exec cp {} --parents …`) is isolated in
`zip_handling.py` so that archive specifics stay out of this module.
"""

import logging
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable, Iterator, Collection, Callable, Sequence

from pymatgen.core import Structure, Lattice
from pymatgen.io.vasp import Poscar

from ..crystal_dataset import CrystalDataset, CrystalEntry
from .zip_handling import exploded_zip_tree         # archive helper
from .poscars import read_poscars
from .mattergen_tools.parsers import input_parameters_to_dict

LOG = logging.getLogger(__name__)

SINGLE_STRUCTURE_PATTERNS = ('*.cif', '*POSCAR', '*POSCAR*')
ALLOWED_BATCH_METADATA_DIFF_KEYS = {"output_path", "batch_size", "gpu_memory_gb", "print_loss"}

BATCH_READER_REGISTRY: dict[str, Callable[["StructureDatasetIO", Path], CrystalDataset]] = {
    '*POSCARS': lambda io, file: io.load_from_multiimage_poscar(file),
    '*.extxyz': lambda io, file: io.load_from_extxyz(file),
}
BATCH_STRUCTURE_PATTERNS = tuple(BATCH_READER_REGISTRY)
SUPPORTED_PATTERNS = SINGLE_STRUCTURE_PATTERNS + BATCH_STRUCTURE_PATTERNS

###############################################################################
# Internal helpers                                                           #
###############################################################################

def _safe_structure_from_file(path: Path, merge_tol: float = 0.01) -> Structure | None:
    """Return Structure or *None* on parser failure; logs the error."""
    try:
        return Structure.from_file(path, merge_tol=merge_tol)
    except Exception as exc:  # ValueError, RuntimeError, etc.
        LOG.warning("Skipping %s – %s", path, exc)
        return None


def _entry_id_sequence(prefix: str) -> Iterator[str]:
    """Yield id strings prefix0, prefix1, … endlessly."""
    counter = 0
    while True:
        yield f"{prefix}{counter}"
        counter += 1


def _iter_structure_files(root: Path, pattern: str) -> Iterator[Path]:
    """Yield files in *root* matching *pattern* (via rglob)."""
    yield from root.rglob(pattern)


def _pattern_kind(pattern: str) -> str:
    if pattern in SINGLE_STRUCTURE_PATTERNS:
        return "single"
    if pattern in BATCH_STRUCTURE_PATTERNS:
        return "batch"
    return "unsupported"

def _parse_extxyz_structures(extxyz_file: Path) -> list[Structure]:
    lines = extxyz_file.read_text().splitlines()
    idx = 0
    structures: list[Structure] = []
    lattice_re = re.compile(r'Lattice="([^"]+)"')

    while idx < len(lines):
        line = lines[idx].strip()
        if not line:
            idx += 1
            continue
        try:
            natoms = int(line)
        except ValueError as exc:
            raise ValueError(f"Invalid atom count line in {extxyz_file}: {line}") from exc
        if idx + 1 >= len(lines):
            raise ValueError(f"Missing Lattice line after atom count in {extxyz_file}")

        lattice_line = lines[idx + 1]
        match = lattice_re.search(lattice_line)
        if not match:
            raise ValueError(f"Missing Lattice definition in {extxyz_file}: {lattice_line}")
        lattice_vals = [float(x) for x in match.group(1).split()]
        if len(lattice_vals) != 9:
            raise ValueError(f"Expected 9 lattice values in {extxyz_file}, got {len(lattice_vals)}")
        lattice = Lattice([
            lattice_vals[0:3],
            lattice_vals[3:6],
            lattice_vals[6:9],
        ])

        start = idx + 2
        end = start + natoms
        if end > len(lines):
            raise ValueError(f"Not enough atom lines in {extxyz_file} for natoms={natoms}")
        species: list[str] = []
        coords: list[list[float]] = []
        for atom_line in lines[start:end]:
            parts = atom_line.split()
            if len(parts) < 4:
                raise ValueError(f"Invalid atom line in {extxyz_file}: {atom_line}")
            species.append(parts[0])
            coords.append([float(parts[1]), float(parts[2]), float(parts[3])])

        structures.append(Structure(lattice, species, coords, coords_are_cartesian=True))
        idx = end

    return structures

def get_batch_metadata(root: Path, prov_file: str | Path) -> str | None:
    root = Path(root)
    prov_pattern = prov_file.as_posix() if isinstance(prov_file, Path) else str(prov_file)
    found_prov_files = sorted(root.rglob(prov_pattern))
    if not found_prov_files:
        return None

    metadata_by_file = [
        (found_prov_file, found_prov_file.read_text(encoding="utf-8"))
        for found_prov_file in found_prov_files
    ]
    reference_file, reference_metadata = metadata_by_file[0]
    reference_params = input_parameters_to_dict(raw=reference_metadata)
    comparable_reference = {
        k: v for k, v in reference_params.items()
        if k not in ALLOWED_BATCH_METADATA_DIFF_KEYS
    }
    for found_prov_file, prov_metadata in metadata_by_file[1:]:
        prov_params = input_parameters_to_dict(raw=prov_metadata)
        comparable_params = {
            k: v for k, v in prov_params.items()
            if k not in ALLOWED_BATCH_METADATA_DIFF_KEYS
        }
        if comparable_params != comparable_reference:
            raise ValueError(
                f"Found '{reference_file.as_posix()}' and '{found_prov_file.as_posix()}', "
                "but they differ outside allowed batch metadata keys: "
                f"{sorted(ALLOWED_BATCH_METADATA_DIFF_KEYS)}."
            )

    return reference_metadata

###############################################################################
# Public façade                                                              #
###############################################################################

@dataclass(slots=True)
class StructureDatasetIO:
    """Read and write `CrystalDataset` objects.

    Parameters
    ----------
    root : Path
        Source directory that may contain structure files and/or zip archives.
    patterns_priority : Sequence[str], default ("*.cif", "*POSCAR", "*POSCARS", "*.extxyz")
        Ordered list of patterns to try. The first pattern with matching files
        is selected and used for loading.
    pattern : str | None, default None
        Backward-compatible alias for a single pattern. If provided, it
        overrides `patterns_priority` with a one-item list.
    id_prefix : str, default ""
        Prefix for auto‑generated entry IDs.
    expand_archives : bool, default True
        If *True* the loader copies every ``*.zip`` (preserving directory tree)
        to a temporary area, recursively explodes them, and reads structures
        from that expanded tree **in addition to** structures already present
        on disk.  If *False* only files on disk are inspected.
    """

    root: Path | str | None = None
    patterns_priority: Sequence[str] = ("*.cif", "*POSCAR", "*POSCARS", "*.extxyz")
    pattern: str | None = None
    id_prefix: str = ""
    expand_archives: bool = True
    source_name: str = "NA"
    batch_metadata_file: str | Path | None = None
    _id_iter: Iterator[str] = field(init=False, repr=False)

    # --------------------------------------------------------------------- #
    # Initialisation                                                        #
    # --------------------------------------------------------------------- #
    def __post_init__(self) -> None:
        if isinstance(self.root, str):
            self.root = Path(self.root)
        # if not self.root.is_dir():
        #     raise FileNotFoundError(self.root)
        if self.pattern is not None:
            self.patterns_priority = (self.pattern,)
        if not self.patterns_priority:
            raise ValueError("patterns_priority must contain at least one pattern.")
        unsupported = [p for p in self.patterns_priority if _pattern_kind(p) == "unsupported"]
        if unsupported:
            raise ValueError(
                f"Unsupported pattern(s): {tuple(unsupported)}. "
                f"Supported patterns: {SUPPORTED_PATTERNS}."
            )
        self._id_iter = _entry_id_sequence(self.id_prefix)

    # --------------------------------------------------------------------- #
    # Reader methods                                                        #
    # --------------------------------------------------------------------- #
    def load_from_directory(
        self,
        *,
        elements: Collection[str] | None = None,
        message: str | None = None,
        # expand_archives: bool = True
    ) -> CrystalDataset:
        """Return a dataset built from *root*.

        Parameters
        ----------
        message : str | None
            Optional dataset message.
        expand_archives : bool | None
            Overrides the instance‑level ``expand_archives`` flag.
        """
        # use_archives = self.expand_archives if expand_archives is None else expand_archives

        entries: list[CrystalEntry] = []
        source_file_count = 0
        parsed_structure_count = 0
        bad = 0
        matched_by_pattern = {
            p: list(_iter_structure_files(self.root, p))
            for p in self.patterns_priority
        }
        selected_pattern = next((p for p in self.patterns_priority if matched_by_pattern[p]), None)
        batch_metadata = get_batch_metadata(self.root, self.batch_metadata_file) if \
            self.batch_metadata_file else None
        if selected_pattern is None:
            msg = message or (
                f"0 structures out of 0 parsed structures across 0 files "
                f"collected from {self.root}"
            )
            return CrystalDataset(
                entries,
                message=msg,
                supplementary_metadata={
                    "batch_metadata": batch_metadata,
                    "source_pattern": None,
                    "source_file_count": 0,
                    "parsed_structure_count": 0,
                    "retained_structure_count": 0,
                    "failed_file_count": 0,
                },
            )

        matched_patterns = [p for p in self.patterns_priority if matched_by_pattern[p]]
        if len(matched_patterns) > 1:
            LOG.warning(
                "Path %s: Files were found for multiple patterns %s; using '%s' by priority.",
                self.root, tuple(matched_patterns), selected_pattern
            )
            path_sets = {p: set(matched_by_pattern[p]) for p in matched_patterns}
            overlap_exists = any(
                path_sets[p1] & path_sets[p2]
                for idx, p1 in enumerate(matched_patterns)
                for p2 in matched_patterns[idx + 1:]
            )
            if overlap_exists:
                LOG.warning(
                    "Some files match multiple priority patterns; verify ordering in patterns_priority=%s.",
                    tuple(self.patterns_priority)
                )
        matched_kinds = {_pattern_kind(p) for p in matched_patterns}
        if 'single' in matched_kinds and 'batch' in matched_kinds:
            LOG.warning(
                "Mixed structure sources detected (single-file and batch-file). Using '%s' by priority.",
                selected_pattern
            )

        selected_kind = _pattern_kind(selected_pattern)
        for file in matched_by_pattern[selected_pattern]:
            source_file_count += 1
            if selected_kind == "single":
                struct = _safe_structure_from_file(file)
                if struct:
                    parsed_structure_count += 1
                    entries.append(CrystalEntry(id=next(self._id_iter), structure=struct,
                                                metadata={"source": self.source_name, "file": file.name}))
                else:
                    bad += 1
            elif selected_kind == "batch":
                try:
                    reader = BATCH_READER_REGISTRY.get(selected_pattern)
                    if reader is None:
                        raise ValueError(
                            f"Unhandled batch pattern '{selected_pattern}'. "
                            f"Registered batch patterns: {tuple(BATCH_READER_REGISTRY)}."
                        )
                    batch_ds = reader(self, file)
                    parsed_structure_count += len(batch_ds)
                    entries.extend(batch_ds)
                except Exception as exc:
                    LOG.warning("Skipping batch file %s – %s", file, exc)
                    bad += 1
            else:
                raise ValueError(
                    f"Unsupported pattern '{selected_pattern}'. "
                    f"Supported single patterns: {SINGLE_STRUCTURE_PATTERNS}; "
                    f"batch patterns: {BATCH_STRUCTURE_PATTERNS}."
                )

        if elements:
            entries = [e for e in entries if not (set(e.composition.as_data_dict()["elements"]) - set(elements))]
        retained_structure_count = len(entries)
        msg = message or (
            f"{retained_structure_count} structures out of "
            f"{parsed_structure_count} parsed structures across "
            f"{source_file_count} files collected from {self.root}"
        )
        return CrystalDataset(
            entries,
            message=msg,
            supplementary_metadata={
                "batch_metadata": batch_metadata,
                "source_pattern": selected_pattern,
                "source_file_count": source_file_count,
                "parsed_structure_count": parsed_structure_count,
                "retained_structure_count": retained_structure_count,
                "failed_file_count": bad,
            },
        )

    def load_from_multiimage_poscar(
        self,
        poscars_file: Path,
        entries_ids_file: Path | None = None,
        *,
        message: str | None = None,
    ) -> CrystalDataset:
        """Return a dataset from a multi‑image POSCARS file."""
        from pymatgen.io.ase import AseAtomsAdaptor

        atoms_list = read_poscars(poscars_file)
        if entries_ids_file:
            ids = Path(entries_ids_file).read_text().splitlines()
            if len(ids) != len(atoms_list):
                raise ValueError("Number of IDs does not match number of structures.")
        else:
            ids = [next(self._id_iter) for _ in range(len(atoms_list))]

        entries = [
            CrystalEntry(id=id_, structure=AseAtomsAdaptor.get_structure(ats))
            for id_, ats in zip(ids, atoms_list)
        ]
        msg = message or f"Structures loaded from {poscars_file.as_posix()}"
        return CrystalDataset(entries, message=msg)

    def load_from_extxyz(
        self,
        extxyz_file: Path,
        entries_ids_file: Path | None = None,
        *,
        message: str | None = None,
    ) -> CrystalDataset:
        """Return a dataset from an extended XYZ file."""
        structures = _parse_extxyz_structures(extxyz_file)
        if entries_ids_file:
            ids = Path(entries_ids_file).read_text().splitlines()
            if len(ids) != len(structures):
                raise ValueError("Number of IDs does not match number of structures.")
        else:
            ids = [next(self._id_iter) for _ in range(len(structures))]

        entries = [
            CrystalEntry(id=id_, structure=struct, metadata={"source": self.source_name, "file": extxyz_file.name})
            for id_, struct in zip(ids, structures)
        ]
        msg = message or f"Structures loaded from {extxyz_file.as_posix()}"
        return CrystalDataset(entries, message=msg)

    # --------------------------------------------------------------------- #
    # Writer methods                                                        #
    # --------------------------------------------------------------------- #
    @staticmethod
    def dump_poscar_files(
        dataset: Iterable[CrystalEntry],
        out_dir: Path,
    ) -> None:
        """Write each entry to its own POSCAR file in *out_dir*."""
        out_dir.mkdir(parents=True, exist_ok=True)
        for entry in dataset:
            filename = out_dir / entry.poscarname
            entry.structure.to(fmt="poscar", filename=filename, comment=entry.id)

    @staticmethod
    def dump_multiimage_poscar(
        dataset: Iterable[CrystalEntry],
        filename: Path,
        *,
        sort_key=None,
    ) -> None:
        """Write a POSCARS multi‑image file; optional plain‑text ID list."""
        sequence = sorted(dataset, key=sort_key) if sort_key else list(dataset)
        with open(filename, "wt") as fid:
            for entry in sequence:
                poscar_str = Poscar(entry.structure, comment=entry.id).get_str()
                fid.write(poscar_str)
