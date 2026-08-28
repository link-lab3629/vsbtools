import sys, io, os
from ase.io import read
# --- temporary hijack of stdout so import-time banners go to stderr ----------
class _Stdout2Stderr(io.TextIOBase):
    def write(self, s):  sys.stderr.write(s)
    def flush(self):     sys.stderr.flush()

_orig_stdout = sys.stdout
sys.stdout   = _Stdout2Stderr()      # anything printed during imports → stderr
# ---------------------------------------------------------

force_gpu_index = os.getenv("VSB_FORCE_GPU_INDEX")
if force_gpu_index is not None:
    os.environ["CUDA_DEVICE_ORDER"] = "PCI_BUS_ID"
    os.environ["CUDA_VISIBLE_DEVICES"] = force_gpu_index

from tensorpotential.calculator import grace_fm
DEFAULT_GRACE_MODEL = "GRACE-2L-OMAT-large-ft-AM"
grace_model = os.environ.get("VSB_GRACE_MODEL") or DEFAULT_GRACE_MODEL
calc = grace_fm(grace_model)
# restore clean stdout for our own protocol
sys.stdout = _OrigStdout = _orig_stdout

# energy_worker.py  –  read JSON atoms on stdin, emit energy per line

for line in sys.stdin:                     # newline-delimited protocol
    line = line.strip()
    if not line:                           # ignore blank lines
        continue
    try:
        atoms = read(io.StringIO(line), format="json")
        atoms.calc = calc                  # attach the calculator
        e = atoms.get_potential_energy()  # get the energy
        print(e, flush=True)               # one float, one line
    except Exception as err:
        print(f"ERR {err}", flush=True)
