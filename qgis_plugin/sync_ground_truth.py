"""Copy ../ground_truth.py into the plugin (the plugin must be self-contained when zipped).

    python sync_ground_truth.py          copy the file
    python sync_ground_truth.py --check  exit 1 if the plugin copy differs from the repo file
"""
import shutil
import sys
from pathlib import Path

here = Path(__file__).resolve().parent
src = here.parent / "ground_truth.py"
dst = here / "demnas_dtm_qgis" / "core" / "ground_truth.py"

if "--check" in sys.argv:
    same = dst.exists() and src.read_bytes() == dst.read_bytes()
    print("in sync" if same else f"OUT OF SYNC: run python {Path(__file__).name}")
    sys.exit(0 if same else 1)
shutil.copyfile(src, dst)
print(f"copied {src} -> {dst}")
