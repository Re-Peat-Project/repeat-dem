"""Defaults (mirror demnas_dtm.DEFAULTS), parsers for text/matrix widgets, YAML seeding and the
log bridge to the Processing feedback."""
from __future__ import annotations

import copy
import json
import logging



def _ground_defaults() -> dict:
    """gt.GROUND_DEFAULTS, read as a literal so the provider can load (and show its parameters)
    even when pandas, which ground_truth imports at the top, is not installed yet."""
    import ast
    import os
    with open(os.path.join(os.path.dirname(__file__), "ground_truth.py"), encoding="utf-8") as f:
        for node in ast.parse(f.read()).body:
            if isinstance(node, ast.AnnAssign) and getattr(node.target, "id", "") == "GROUND_DEFAULTS":
                return ast.literal_eval(node.value)
    raise RuntimeError("GROUND_DEFAULTS not found in ground_truth.py")


DEFAULTS: dict = {
    "aoi_buffer_m": 500,
    "target_crs": "auto-utm",
    "target_res_m": 8.0,
    "dem_valid_range_m": [-50, 4000],
    "corrections": {
        "mode": "download",
        "landcover_path": None,
        "chm_path": None,
        "worldcover_url": (
            "https://esa-worldcover.s3.eu-central-1.amazonaws.com/v200/2021/map/"
            "ESA_WorldCover_10m_2021_v200_{tile}_Map.tif"),
        "chm_url": (
            "https://dataforgood-fb-data.s3.amazonaws.com/forests/v1/"
            "alsgedi_global_v6_float/chm/{quadkey}.tif"),
        "chm_quadkey_zoom": 9,
        "chm_min_m": 2.0,
        "chm_max_m": 60.0,
        "chm_fallback_m": {"10": 20.0, "95": 12.0},
    },
    "k_by_class": {"10": 0.8, "20": 0.5, "30": 0.2, "40": 0.2, "50": 0.0, "60": 0.0, "70": 0.0,
                   "80": 0.0, "90": 0.4, "95": 0.8, "100": 0.0},
    "k_default": 0.5,
    "bias_by_class": {},
    "bias_default": 0.0,
    "mask": {
        "landcover_classes": [80, 50],
        "vectors": [],
        "despike": True,
        "despike_window_m": 400,
        "despike_threshold_m": 2.5,
    },
    "smoothing": {
        "steps": [{"method": "median", "window_m": 300}, {"method": "gaussian", "sigma_m": 150}],
        "fill_max_search_px": 200,
    },
    "ground": _ground_defaults(),
    "outputs": {"write_intermediates": True, "compress": "deflate"},
}


def deep_update(base: dict, upd: dict) -> dict:
    for k, v in (upd or {}).items():
        if isinstance(v, dict) and isinstance(base.get(k), dict):
            deep_update(base[k], v)
        else:
            base[k] = v
    return base


def base_config(yaml_path: str | None = None) -> dict:
    """Defaults, overlaid by an optional YAML file (same schema as the CLI's config)."""
    cfg = copy.deepcopy(DEFAULTS)
    if yaml_path:
        try:
            import yaml
        except ImportError as e:  # pragma: no cover
            raise RuntimeError("PyYAML is not available in this Python; clear the YAML parameter "
                               "or install pyyaml") from e
        with open(yaml_path, "r", encoding="utf-8") as f:
            deep_update(cfg, yaml.safe_load(f) or {})
    return cfg


def set_path(cfg: dict, path: tuple, value):
    d = cfg
    for k in path[:-1]:
        d = d[k]
    d[path[-1]] = value


def get_path(cfg: dict, path: tuple):
    d = cfg
    for k in path:
        d = d[k]
    return d


# --------------------------------------------------------------------------------------
# Text and matrix widgets
# --------------------------------------------------------------------------------------
def parse_class_list(text: str) -> list[int]:
    """'80, 50' -> [80, 50]"""
    return [int(t) for t in str(text or "").replace(";", ",").split(",") if t.strip()]


def format_class_list(vals) -> str:
    return ", ".join(str(int(v)) for v in vals)


def matrix_to_table(flat: list, ncols: int = 2) -> dict:
    """Flat matrix (row-major, as QgsProcessingParameterMatrix returns it) -> {class: value}."""
    out = {}
    for i in range(0, len(flat) - ncols + 1, ncols):
        cls, val = flat[i], flat[i + 1]
        if str(cls).strip() == "" or str(val).strip() == "":
            continue
        out[str(int(float(cls)))] = float(val)
    return out


def table_to_matrix(table: dict) -> list:
    flat = []
    for k, v in table.items():
        flat += [int(k), float(v)]
    return flat


_STEP_POS = {"median": "window_m", "gaussian": "sigma_m", "polynomial": "degree"}


def parse_steps(text: str) -> list[dict]:
    """'median:300; gaussian:150; polynomial:degree=3,huber_m=1.0' -> step dicts.
    The first bare number is window_m (median), sigma_m (gaussian) or degree (polynomial)."""
    steps = []
    for chunk in str(text or "").split(";"):
        chunk = chunk.strip()
        if not chunk:
            continue
        method, _, args = chunk.partition(":")
        method = method.strip().lower()
        if method not in _STEP_POS:
            raise ValueError(f"unknown smoothing method {method!r} (use median, gaussian, polynomial)")
        step = {"method": method}
        for i, a in enumerate(x for x in args.split(",") if x.strip()):
            if "=" in a:
                k, v = a.split("=", 1)
                step[k.strip()] = float(v)
            elif i == 0:
                step[_STEP_POS[method]] = float(a)
            else:
                raise ValueError(f"cannot read {a!r} in smoothing step {chunk!r}; use key=value")
        need = _STEP_POS[method]
        if method != "polynomial" and need not in step:
            raise ValueError(f"smoothing step {chunk!r} needs a value ({need})")
        steps.append(step)
    return steps


def format_steps(steps: list[dict]) -> str:
    out = []
    for s in steps:
        key = _STEP_POS[s["method"]]
        extra = [f"{k}={v:g}" for k, v in s.items() if k not in ("method", key)]
        first = [f"{s[key]:g}"] if key in s else []
        out.append(f"{s['method']}:" + ",".join(first + extra))
    return "; ".join(out)


def parse_fallback(text: str) -> dict:
    """'10:20; 95:12' -> {'10': 20.0, '95': 12.0}"""
    out = {}
    for chunk in str(text or "").replace(",", ";").split(";"):
        if ":" in chunk:
            k, v = chunk.split(":", 1)
            out[str(int(k))] = float(v)
    return out


def format_fallback(d: dict) -> str:
    return "; ".join(f"{k}:{v:g}" for k, v in d.items())


# --------------------------------------------------------------------------------------
# Logging bridge
# --------------------------------------------------------------------------------------
class FeedbackHandler(logging.Handler):
    """Sends the pipeline's log records to a QgsProcessingFeedback."""

    def __init__(self, feedback):
        super().__init__(logging.INFO)
        self.fb = feedback

    def emit(self, record):
        msg = self.format(record)
        if record.levelno >= logging.ERROR:
            self.fb.reportError(msg)
        elif record.levelno >= logging.WARNING:
            self.fb.pushWarning(msg)
        else:
            self.fb.pushInfo(msg)


class bridge_logging:
    """with bridge_logging(feedback): ... routes demnas_dtm* loggers to the feedback."""

    def __init__(self, feedback):
        self.h = FeedbackHandler(feedback)

    def __enter__(self):
        for n in ("demnas_dtm", "demnas_dtm.ground"):
            lg = logging.getLogger(n)
            lg.setLevel(logging.INFO)
            lg.propagate = False
            lg.addHandler(self.h)
        return self

    def __exit__(self, *exc):
        for n in ("demnas_dtm", "demnas_dtm.ground"):
            logging.getLogger(n).removeHandler(self.h)
        return False


def dump_json(path, obj):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(obj, f, indent=2, default=str)
