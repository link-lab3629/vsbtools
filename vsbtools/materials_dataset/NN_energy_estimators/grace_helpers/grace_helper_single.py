import sys, io, os
from ase.io import read
force_gpu_index = os.getenv("VSB_FORCE_GPU_INDEX")
if force_gpu_index is not None:
    os.environ["CUDA_DEVICE_ORDER"] = "PCI_BUS_ID"
    os.environ["CUDA_VISIBLE_DEVICES"] = force_gpu_index
from tensorpotential.calculator import grace_fm
DEFAULT_GRACE_MODEL = "GRACE-2L-OMAT-large-ft-AM"
grace_model = os.environ.get("VSB_GRACE_MODEL") or DEFAULT_GRACE_MODEL
calc = grace_fm(grace_model)

"""
Read an ASE JSON structure from stdin, print the total energy to stdout.
"""
atoms = read(io.StringIO(sys.stdin.read()), format="json")
atoms.calc = calc
e = atoms.get_potential_energy()
print(e)
