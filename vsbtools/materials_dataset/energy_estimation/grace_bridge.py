import numpy as np
import time
from ..crystal_dataset import CrystalDataset, CrystalEntry
from ..NN_energy_estimators import grace_client


def describe_model(grace_model: str | None = None, **kwargs) -> dict[str, str]:
    """Return model metadata persisted on datasets produced by this bridge."""
    return {"grace_model": grace_client.resolve_grace_model(grace_model)}


def estimate_batch(
    dataset: CrystalDataset,
    force_gpu: int | None = None,
    grace_model: str | None = None,
    **kwargs,
):
    progress_interval_s = kwargs.get("progress_interval_s", 0.5)
    estimator_name = kwargs.get("estimator_name", "grace")
    with grace_client.EnergyStream(
        force_gpu=force_gpu,
        grace_model=grace_model,
    ) as es:
        n_entries = len(dataset)
        energies = np.zeros(n_entries)
        last_progress = 0.0
        status_len = 0
        for i, e in enumerate(dataset):
            try:
                source = e.metadata.get("file", e.metadata["source"])
                status = f"Now estimating energy with {estimator_name} {i + 1}/{n_entries} of entry with id={e.id} from {source}"
                now = time.monotonic()
                if now - last_progress >= progress_interval_s:
                    print(f"\r{status}{' ' * max(0, status_len - len(status))}", end="", flush=True)
                    last_progress, status_len = now, len(status)
                s = e.structure.copy()
                if "selective_dynamics" in s.site_properties:
                    s.remove_site_property("selective_dynamics")
                energies[i] = es.calc(s.to_ase_atoms())
            except RuntimeError as err:
                print()
                print(f"Couldn't get energy for {e.id}, set to infinity")
                energies[i] = np.inf
        if n_entries:
            status = f"Now estimating energy with {estimator_name} {n_entries}/{n_entries}"
            print(f"\r{status}{' ' * max(0, status_len - len(status))}")
    return energies

def estimate_entry_energy(
    e: CrystalEntry,
    force_gpu: int | None = None,
    grace_model: str | None = None,
    **kwargs,
):
    return grace_client.get_energy(
        e.structure.to_ase_atoms(),
        force_gpu=force_gpu,
        grace_model=grace_model,
    )

def relax_batch(
    dataset: CrystalDataset,
    force_gpu: int | None = None,
    grace_model: str | None = None,
    **kwargs,
):
    with grace_client.RelaxStream(
        force_gpu=force_gpu,
        grace_model=grace_model,
    ) as rs:
        new_structures = [None] * len(dataset)
        for i, e in enumerate(dataset):
            try:
                print(f"Now relaxing structure with id = {e.id} ({e.poscarname}) from dataset id = {dataset.dataset_id}")
                s = e.structure.copy()
                if "selective_dynamics" in s.site_properties:
                    s.remove_site_property("selective_dynamics")
                new_structures[i] = rs.relax(s.to_ase_atoms())
            except RuntimeError as err:
                print (f"Couldn't relax structure with id = {e.id} ({e.poscarname}) from dataset id = {dataset.dataset_id}")
    return new_structures

def relax_entry(
    e: CrystalEntry,
    force_gpu: int | None = None,
    grace_model: str | None = None,
    **kwargs,
):
    return grace_client.relax(
        e.structure.to_ase_atoms(),
        force_gpu=force_gpu,
        grace_model=grace_model,
    )
