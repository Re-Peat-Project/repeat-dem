"""Build demnas_dtm_qgis.zip for Plugins > Manage and Install Plugins > Install from ZIP.

    python build_zip.py
"""
import subprocess
import sys
import zipfile
from pathlib import Path

here = Path(__file__).resolve().parent
if subprocess.call([sys.executable, str(here / "sync_ground_truth.py"), "--check"]) != 0:
    sys.exit("ground_truth.py in the plugin is stale: run python sync_ground_truth.py first")

pkg = here / "demnas_dtm_qgis"
out = here / "demnas_dtm_qgis.zip"
with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
    for f in sorted(pkg.rglob("*")):
        if f.is_file() and "__pycache__" not in f.parts and f.suffix != ".pyc":
            z.write(f, f.relative_to(here))
print(f"wrote {out} ({out.stat().st_size // 1024} kB)")
