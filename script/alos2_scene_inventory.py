"""Inventory of open ALOS-2 PALSAR-2 ScanSAR L1.1 scenes over a KHG at ASF (metadata only, no download, no login).

    python script/alos2_scene_inventory.py --khg "KHG Sungai Sugihan - Sungai Lumpur" [--out docs/alos2_scenes_<slug>.csv]

Queries the ASF SearchAPI (platform=ALOS-2) with the KHG bounding box, keeps scenes covering at least 20% of the KHG (a large KHG spans two frames; khg_cover says how much),
and writes one row per scene (path, frame, date, beam mode, direction, polarisations, size, granule name, URL), sorted by
path/frame/date. A summary per path/frame (scenes, years, total size) is printed. Used to plan the L-band subsidence
pilot (docs/alos2-pilot-plan.md).
"""
import argparse
import json
import os
import sys
import urllib.parse
import urllib.request
from pathlib import Path

import geopandas as gpd
import pandas as pd
from shapely.geometry import shape

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO.parent / "repeat-common" / "src"))
from repeat_common import khg  # noqa: E402

BOUNDARY = ("batas_khg_indonesia.gpkg", "nama__khg__indonesia__2017__rev_tipologi", "NAMA_KHG")
API = "https://api.daac.asf.alaska.edu/services/search/param"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--khg", required=True)
    ap.add_argument("--out")
    a = ap.parse_args()
    data = Path(os.environ.get("REPEAT_DATA") or REPO.parent / "_data")
    b = gpd.read_file(data / BOUNDARY[0], layer=BOUNDARY[1])
    norm = lambda s: " ".join(str(s).split())
    g = b[b[BOUNDARY[2]].map(norm) == norm(a.khg)].to_crs(4326).union_all()
    x0, y0, x1, y1 = g.bounds
    q = urllib.parse.urlencode({"platform": "ALOS-2", "bbox": f"{x0:.4f},{y0:.4f},{x1:.4f},{y1:.4f}", "output": "geojson", "maxResults": 5000})
    with urllib.request.urlopen(f"{API}?{q}", timeout=120) as r:
        fs = json.load(r)["features"]
    rows = []
    for f in fs:
        p = f["properties"]
        cover = shape(f["geometry"]).intersection(g).area / g.area if f.get("geometry") else 0.0
        rows.append({"path": p.get("pathNumber"), "frame": p.get("frameNumber"), "date": p.get("startTime", "")[:10],
                     "beam": p.get("beamModeType"), "direction": p.get("flightDirection"),
                     "polarization": "+".join(p.get("polarization") or []) if isinstance(p.get("polarization"), list) else p.get("polarization"),
                     "size_gb": round((p.get("bytes") or 0) / 1e9, 1), "khg_cover": round(cover, 3),
                     "granule": p.get("sceneName") or p.get("fileID"), "url": p.get("url")})
    d = pd.DataFrame(rows)
    d = d[d.khg_cover >= 0.2].sort_values(["path", "frame", "date"])
    out = Path(a.out) if a.out else REPO / "docs" / f"alos2_scenes_{khg.slug(a.khg)}.csv"
    d.to_csv(out, index=False)
    s = d.groupby(["path", "frame", "direction", "beam"]).agg(scenes=("date", "size"), first=("date", "min"), last=("date", "max"),
                                                            total_tb=("size_gb", lambda v: round(v.sum() / 1000, 2)),
                                                            khg_cover=("khg_cover", "median"))
    print(s.to_string())
    print("wrote", out)


if __name__ == "__main__":
    main()
