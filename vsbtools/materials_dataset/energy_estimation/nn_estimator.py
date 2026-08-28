from dataclasses import dataclass
from typing import Any, Callable, ClassVar, Dict
import types
from ..crystal_dataset import CrystalDataset, CrystalEntry
from ..geom_utils.structure_checks import check_density_sanity_ase
from pymatgen.core import Structure


@dataclass(slots=True)
class NNEstimator:

    known_models: ClassVar[Dict[str, types.ModuleType]] = {}
    default_model: str = "mattersim"
    force_gpu: int | None = None
    grace_model: str | None = None

    def _prepare_kwargs(self, kwargs: Dict[str, Any]) -> Dict[str, Any]:
        kwargs = dict(kwargs)
        if "force_gpu" not in kwargs:
            kwargs["force_gpu"] = self.force_gpu
        if self.grace_model is not None:
            kwargs.setdefault("grace_model", self.grace_model)
        return kwargs

    @staticmethod
    def _add_estimator_metadata(dataset, estimator, model_name, kwargs):
        dataset.metadata["estimator"] = model_name
        describe_model = getattr(estimator, "describe_model", None)
        if describe_model is not None:
            dataset.metadata.update(describe_model(**kwargs))
        return dataset

    def estimate_dataset_energies(self, dataset: CrystalDataset, model_name: str | None = None, **kwargs):
        kwargs = self._prepare_kwargs(kwargs)
        model_name = self.default_model if model_name is None else model_name
        if model_name not in self.known_models:
            raise ValueError(f"Unknown model: '{model_name}', available: {list(self.known_models.keys())}")
        estimator = self.known_models[model_name]
        kwargs.setdefault("estimator_name", model_name)
        new_energies = estimator.estimate_batch(dataset, **kwargs)
        new_entries = []
        for entry, estimation in zip(dataset, new_energies):
            new_entries.append(entry.copy_with(**{"energy": estimation}))
        msg = f"Energies estimated with {model_name}"
        result = CrystalDataset.from_parents(new_entries, (dataset,), message=msg)
        return self._add_estimator_metadata(result, estimator, model_name, kwargs)

    def estimate_entry_energy(self, e: CrystalEntry, model: str | None = "mattersim", **kwargs):
        kwargs = self._prepare_kwargs(kwargs)
        return self.known_models[model].estimate_entry_energy(e, **kwargs)

    def relax_dataset(self, dataset: CrystalDataset, model_name: str | None = None, **kwargs):
        kwargs = self._prepare_kwargs(kwargs)
        model_name = self.default_model if model_name is None else model_name
        if model_name not in self.known_models:
            raise ValueError(f"Unknown model: '{model_name}', available: {list(self.known_models.keys())}")
        estimator = self.known_models[model_name]
        new_structures = estimator.relax_batch(dataset, **kwargs)
        new_entries = []
        for entry, atoms in zip(dataset, new_structures):
            md = entry.metadata
            if atoms is None:
                is_OK = False
                info = "Relaxation_failed"
            else:
                is_OK, info = check_density_sanity_ase(atoms)
            if is_OK:
                new_entries.append(entry.copy_with(**{"structure": Structure.from_ase_atoms(atoms),
                                                      "metadata": {**md, **{'relaxation_done': True}}}))
            else:
                print(f"id {entry.id} - Unreasonable structure after relaxation: {info}")
                new_entries.append(entry.copy_with(**{"metadata": {**md, **{'relaxation_done': False}}}))

        msg = f"Structures relaxed with {model_name}"
        result = CrystalDataset.from_parents(new_entries, (dataset,), message=msg)
        return self._add_estimator_metadata(result, estimator, model_name, kwargs)

    def relax_entry(self, e: CrystalEntry, model: str | None = "mattersim", **kwargs):
        kwargs = self._prepare_kwargs(kwargs)
        return self.known_models[model].relax_entry(e, **kwargs)

    @classmethod
    def register_model(cls, name: str, module: types.ModuleType):
        cls.known_models[name] = module
