# mattersim_relaxer_helper_batch.py
import sys
import io
import os
import traceback
import numpy as np
from ase.io import read, write
from ase.optimize import BFGS
from ase.filters import FrechetCellFilter

# --------------------------------------------------------------------------- #
#  Redirect ALL normal stdout to stderr (imports + runtime)                   #
# --------------------------------------------------------------------------- #

_orig_stdout = sys.stdout   # real stdout – used only for protocol lines


class _StdoutToStderr(io.TextIOBase):
    def write(self, s):
        sys.stderr.write(s)
    def flush(self):
        sys.stderr.flush()


sys.stdout = _StdoutToStderr()

force_gpu_index = os.getenv("VSB_FORCE_GPU_INDEX")
if force_gpu_index is not None:
    os.environ["CUDA_DEVICE_ORDER"] = "PCI_BUS_ID"
    os.environ["CUDA_VISIBLE_DEVICES"] = force_gpu_index

from tensorpotential.calculator import grace_fm
DEFAULT_GRACE_MODEL = "GRACE-2L-OMAT-large-ft-AM"
grace_model = os.environ.get("VSB_GRACE_MODEL") or DEFAULT_GRACE_MODEL
calc = grace_fm(grace_model)

# --------------------------------------------------------------------------- #


def relax_one(ats, fmax=0.02):
    atoms_new = ats.copy()
    atoms_new.positions += 0.1 * np.random.randn(len(ats), 3)
    atoms_new.calc = calc

    atoms_ucf = FrechetCellFilter(atoms_new)
    dyn = BFGS(atoms_ucf, logfile="relax.log")
    flag = dyn.run(fmax=fmax, steps=500)

    if not flag:
        result = ats
    else:
        result = atoms_new
    print("relaxed with GRACE" if flag else "relaxation failed, original structure returned")  # to stderr
    return result


for i, line in enumerate(sys.stdin):
    line = line.strip()
    if not line:
        continue

    try:
        atoms = read(io.StringIO(line), format="json")
        print(f"Now relaxing: {i}")
        relaxed = relax_one(atoms)
        buf = io.StringIO()
        write(buf, relaxed, format="json")
        json_str = buf.getvalue().replace("\n", " ")  # one JSON per line

        _orig_stdout.write(json_str + "\n")
        _orig_stdout.flush()

    except Exception as err:
        # Signal error to caller via stdout, details to stderr
        _orig_stdout.write(f"ERR {err}\n")
        _orig_stdout.flush()
        traceback.print_exc(file=sys.stderr)
