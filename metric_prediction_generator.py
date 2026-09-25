"""
Water-Quality Metric Simulator & Predictor
===========================================
Generates random, practically-possible sensor readings, computes all
6 metrics from the "Metric calculation.pdf" spec, adds a plain-text
prediction for every metric per row, and writes everything to Excel.

Source formulas (from the PDF):
  1) OFI   = (Turbidity / Baseline_Turbidity) * ((pH_midday - pH_morning) / dT)
  2) DABI  = (pH_midday - pH_morning) * sqrt(Turbidity)
  3) SDest = 100 / (Turbidity + 1)                          [meters]
  4) SOR   = TDS / (Turbidity + 1)
  5) DSLR  = TDS / (Turbidity + 1)
  6) DOsat = 14.621 - 0.41022*T + 0.007991*T^2 - 0.000077774*T^3
             - ((TDS * 0.0007) * 0.015)                     [mg/L]
"""

import argparse
import math
import random
from datetime import date
# NOTE: pandas is imported lazily inside excel/preview helpers only so the
# module imports on any runtime (e.g. Vercel) without heavyweight deps.

# ---------------------------------------------------------------------------
# Practically-possible sensor ranges
# ---------------------------------------------------------------------------
SENSOR_RANGES = {
    "temperature_c":  (-2.0, 45.0),     # deg C  (icy to hot inland water)
    "ph_morning":     (4.0, 10.0),      # standard water pH scale
    "ph_delta":       (-0.5, 2.0),      # midday - morning pH shift
    "turbidity_ntu":  (0.1, 1000.0),    # clean spring to flood/slurry
    "baseline_turb":  (0.1, 1000.0),    # historical reference NTU
    "tds_ppm":        (0.0, 5000.0),    # fresh to brackish / runoff
    "dT_c":           (0.1, 3.0),       # morning-to-midday temperature delta
}

# Turbidity above this is treated as "high" for qualifier predictions.
HIGH_TURBIDITY_NTU = 20.0

# ---------------------------------------------------------------------------
# Random sensor record generation
# ---------------------------------------------------------------------------
def gen_sensor_record(rng: random.Random) -> dict:
    def rnd(lo, hi, dec=2):
        return round(rng.uniform(lo, hi), dec)

    rec = {
        "temperature_c": rnd(*SENSOR_RANGES["temperature_c"], 1),
        "ph_morning":    rnd(*SENSOR_RANGES["ph_morning"]),
        "ph_midday":     rnd(4.0, 10.0),
        "turbidity_ntu": rnd(*SENSOR_RANGES["turbidity_ntu"], 1),
        "baseline_turb": rnd(*SENSOR_RANGES["baseline_turb"], 1),
        "tds_ppm":       rnd(*SENSOR_RANGES["tds_ppm"], 1),
        "dT_c":          rnd(*SENSOR_RANGES["dT_c"]),
    }

    # Daily photosynthesis cycle normally RAISES pH toward midday; let the
    # morning, delta and midday stay mutually consistent.
    delta = rnd(*SENSOR_RANGES["ph_delta"])
    rec["ph_morning"] = round(max(4.0, min(10.0, rec["ph_midday"] - delta)), 2)
    return rec


# ---------------------------------------------------------------------------
# Metric computation (plain implementation of the PDF formulas)
# ---------------------------------------------------------------------------
def compute_metrics(r: dict) -> dict:
    t   = r["temperature_c"]
    tds = r["tds_ppm"]
    tur = r["turbidity_ntu"]
    base = r["baseline_turb"]
    ph_d = r["ph_midday"] - r["ph_morning"]
    dT   = r["dT_c"]

    ofi   = (tur / base) * (ph_d / dT)
    dabi  = ph_d * math.sqrt(tur)
    sdest = 100.0 / (tur + 1.0)
    sor   = tds / (tur + 1.0)
    dslr  = tds / (tur + 1.0)
    dosat = (14.621
             - 0.41022 * t
             + 0.007991 * t ** 2
             - 0.000077774 * t ** 3
             - (tds * 0.0007) * 0.015)
    return {"OFI": ofi, "DABI": dabi, "SDest": sdest,
            "SOR": sor, "DSLR": dslr, "DOsat": dosat}


# ---------------------------------------------------------------------------
# Text predictions (thresholds copied from the PDF)
# ---------------------------------------------------------------------------
def high_turb(r: dict) -> bool:
    return r["turbidity_ntu"] >= HIGH_TURBIDITY_NTU


def predict_all(r: dict, m: dict) -> dict:
    p = {}

    # OFI
    if m["OFI"] > 1.5:
        p["OFI"] = "Live Algae / Microalgae Dominance (Organic waste driver)"
    elif 0.3 <= m["OFI"] <= 1.5:
        p["OFI"] = "Mixed Organic & Inorganic suspension"
    else:  # OFI < 0.3
        if high_turb(r):
            p["OFI"] = ("Inorganic Silt / Mud / Clay (Non-biological "
                        "cloudiness) - High Turbidity")
        else:
            p["OFI"] = ("Low biological activity / near-clear conditions "
                        "(OFI < 0.3, Low Turbidity)")

    # DABI
    if m["DABI"] > 8.0:
        p["DABI"] = "Active Algae/Cyanobacteria Bloom (Nighttime O2 drop risk)"
    elif 2.0 <= m["DABI"] <= 8.0:
        p["DABI"] = "Stable biological activity"
    else:  # DABI < 2.0
        if high_turb(r):
            p["DABI"] = "Non-photosynthetic silt cloudiness (High Turbidity)"
        else:
            p["DABI"] = "Low algae activity / clear water (Low Turbidity)"

    # SDest
    if m["SDest"] < 0.3:
        p["SDest"] = "Severe murky water (Bottom plants shaded, dying)"
    elif 0.3 <= m["SDest"] <= 1.0:
        p["SDest"] = "Normal moderate clarity"
    else:
        p["SDest"] = "High transparency / Clear water column"

    # SOR
    if m["SOR"] > 10.0:
        p["SOR"] = "Inorganic Salt Ingress / Fertilizer / Mineral Runoff"
    elif 1.5 <= m["SOR"] <= 10.0:
        p["SOR"] = "Mixed Mineral & Particulate background"
    else:
        p["SOR"] = "Heavy Organic Waste / Manure / Decaying Fish Feed"

    # DSLR
    if m["DSLR"] > 10.0:
        p["DSLR"] = "Dissolved Ion Dominance (Chemical/runoff treatment needed)"
    elif 1.5 <= m["DSLR"] <= 10.0:
        p["DSLR"] = "Balanced dissolved & suspended load"
    else:
        p["DSLR"] = "Particulate Suspended Dominance (Mechanical filtration needed)"

    # DOsat
    if m["DOsat"] < 6.5:
        p["DOsat"] = "Warm Water Stress Zone (Low O2 capacity)"
    elif 6.5 <= m["DOsat"] <= 9.0:
        p["DOsat"] = "Moderate O2 capacity"
    else:
        p["DOsat"] = "Optimal Cool Water Oxygen Storage"

    return p


ALL_PREDICTION_STRINGS = {
    "OFI": ["Live Algae / Microalgae Dominance (Organic waste driver)",
            "Mixed Organic & Inorganic suspension",
            ("Inorganic Silt / Mud / Clay (Non-biological cloudiness) - "
             "High Turbidity"),
            ("Low biological activity / near-clear conditions (OFI < 0.3, "
             "Low Turbidity)")],
    "DABI": ["Active Algae/Cyanobacteria Bloom (Nighttime O2 drop risk)",
             "Stable biological activity",
             "Non-photosynthetic silt cloudiness (High Turbidity)",
             "Low algae activity / clear water (Low Turbidity)"],
    "SDest": ["Severe murky water (Bottom plants shaded, dying)",
              "Normal moderate clarity",
              "High transparency / Clear water column"],
    "SOR": ["Inorganic Salt Ingress / Fertilizer / Mineral Runoff",
            "Mixed Mineral & Particulate background",
            "Heavy Organic Waste / Manure / Decaying Fish Feed"],
    "DSLR": ["Dissolved Ion Dominance (Chemical/runoff treatment needed)",
             "Balanced dissolved & suspended load",
             "Particulate Suspended Dominance (Mechanical filtration needed)"],
    "DOsat": ["Warm Water Stress Zone (Low O2 capacity)",
              "Moderate O2 capacity",
              "Optimal Cool Water Oxygen Storage"],
}


def build_row(rec: dict, idx: int) -> dict:
    m = compute_metrics(rec)
    p = predict_all(rec, m)
    row = {
        "Row #": idx,
        "Temperature (C)": rec["temperature_c"],
        "pH Morning": rec["ph_morning"],
        "pH Midday": rec["ph_midday"],
        "Turbidity (NTU)": rec["turbidity_ntu"],
        "Baseline Turbidity (NTU)": rec["baseline_turb"],
        "TDS (ppm)": rec["tds_ppm"],
        "dT (C)": rec["dT_c"],
    }
    for metric in ["OFI", "DABI", "SDest", "SOR", "DSLR", "DOsat"]:
        row[f"{metric} Value"] = round(m[metric], 4)
        row[f"{metric} Prediction"] = p[metric]
    return row


# ---------------------------------------------------------------------------
# Guarantee every possible prediction text appears at least once
# ---------------------------------------------------------------------------
def ensure_coverage(records: list, seed: int) -> None:
    rng = random.Random(seed + 123456)
    seen = {metric: set() for metric in ALL_PREDICTION_STRINGS}
    for rec in records:
        m = predict_all(rec, compute_metrics(rec))
        for metric in ALL_PREDICTION_STRINGS:
            seen[metric].add(m[metric])

    missing = {metric: [s for s in ALL_PREDICTION_STRINGS[metric]
                        if s not in seen[metric]]
               for metric in ALL_PREDICTION_STRINGS}
    if not any(missing.values()):
        return

    attempts = 0
    max_attempts = 400_000
    while any(missing.values()) and attempts < max_attempts:
        attempts += 1
        rec = gen_sensor_record(rng)
        p = predict_all(rec, compute_metrics(rec))
        hit = False
        for metric in ALL_PREDICTION_STRINGS:
            if p[metric] in missing[metric]:
                missing[metric].remove(p[metric])
                seen[metric].add(p[metric])
                hit = True
        if hit:
            records.append(rec)

    leftovers = {k: v for k, v in missing.items() if v}
    if leftovers:
        print("NOTE: could not generate these prediction cases randomly:",
              leftovers)


# ---------------------------------------------------------------------------
# Excel export
# ---------------------------------------------------------------------------
def reference_rows() -> list:
    rows = [
        ["Metric", "Sensor Inputs", "Formula", "Thresholds -> Prediction"],
        ["OFI (Silt vs Algae Differentiator)",
         "Turbidity, Baseline_Turbidity, pH(am/pm), dT",
         "OFI = (Turb/Baseline_Turb) * ((pH_mid - pH_morn) / dT)",
         ">1.5 Live Algae | 0.3-1.5 Mixed | <0.3+H.Turb Inorganic Silt"],
        ["DABI (Diurnal Algal Bloom Index)",
         "pH(am/pm), Turbidity",
         "DABI = (pH_mid - pH_morn) * sqrt(Turbidity)",
         ">8.0 Active Bloom | 2.0-8.0 Stable | <2.0+H.Turb Silt"],
        ["SDest (Estimated Secchi Depth)",
         "Turbidity",
         "SDest = 100 / (Turbidity + 1)  [m]",
         "<0.3m Severe murk | 0.3-1.0m Moderate | >1.0m Clear"],
        ["SOR (Organic vs Inorganic Salt)",
         "TDS, Turbidity",
         "SOR = TDS / (Turbidity + 1)",
         ">10 Salt ingress | 1.5-10 Mixed | <1.5 Heavy organic"],
        ["DSLR (Dissolved vs Suspended)",
         "TDS, Turbidity",
         "DSLR = TDS / (Turbidity + 1)",
         ">10 Dissolved ions | 1.5-10 Balanced | <1.5 Particulate"],
        ["DOsat (O2 Saturation Capacity)",
         "Temperature, TDS",
         "DOsat = 14.621 - 0.41022T + 0.007991T2 - 0.000077774T3 "
         "- ((TDS*0.0007)*0.015)  [mg/L]",
         "<6.5 Warm stress | 6.5-9.0 Moderate | >9.0 Optimal cool"],
    ]
    rows.append([])
    rows.append(["Sensor", "Practical Range", "Unit"])
    rows.append(["Temperature", "-2 .. 45", "deg C"])
    rows.append(["pH (morning/midday)", "4.0 .. 10.0", "pH units"])
    rows.append(["Turbidity (incl. baseline)", "0.1 .. 1000", "NTU"])
    rows.append(["TDS", "0 .. 5000", "ppm"])
    rows.append(["dT (morning->midday)", "0.1 .. 3.0", "deg C"])
    return rows


def write_excel(rows_data, path: str) -> None:
    import pandas as pd
    df = pd.DataFrame(rows_data)
    ref = pd.DataFrame(reference_rows())

    with pd.ExcelWriter(path, engine="openpyxl") as writer:
        df.to_excel(writer, sheet_name="Sensor Data & Predictions", index=False)
        ref.to_excel(writer, sheet_name="Reference", index=False, header=False)

    # Widen columns via openpyxl after writing
    from openpyxl import load_workbook
    wb = load_workbook(path)
    for sheet in wb.sheetnames:
        ws = wb[sheet]
        for col in ws.columns:
            width = max((len(str(c.value or "")) for c in col), default=8)
            ws.column_dimensions[col[0].column_letter].width = min(width + 2, 60)
    wb.save(path)


# ---------------------------------------------------------------------------
# Lake / grid dataset (spatially correlated, ~1 sq km, ~400+ grid cells)
# ---------------------------------------------------------------------------
def _lake_polygon(seed: int, n: int = 150, R: float = 520.0) -> list:
    """Seed-dependent organic lake outline (perturbed ellipse, centred 0,0).
    Random harmonic phases/amplitudes per seed -> visibly different lakes."""
    rng = random.Random(seed ^ 0x9E3779B9)
    harms = []
    for k_ in (2, 3, 4, 5, 6, 7, 8):
        harms.append((k_, rng.uniform(0.045, 0.24), rng.uniform(0, 2 * math.pi)))
    pts = []
    for i in range(n):
        a = 2 * math.pi * i / n
        r = R * max(0.22, 1.0 + sum(h * math.sin(k_ * a + ph)
                                    for k_, h, ph in harms))
        pts.append((r * math.cos(a), r * math.sin(a)))
    return pts


class _RadialPoly:
    """Point-in-polygon for a star-shaped (radial graph) polygon, via
    interpolation of the boundary radius in polar coordinates. ~10x faster
    than a ray cast for large vertex counts."""

    def __init__(self, poly):
        pts = sorted((math.atan2(y, x), math.hypot(x, y)) for x, y in poly)
        base = pts[0][0]
        self.angles = []
        self.radii = []
        for a, r in pts:
            if self.angles and a < self.angles[-1]:
                a += 2 * math.pi
            self.angles.append(a)
            self.radii.append(r)
        self.base = base
        self.n = len(self.angles)

    def inside(self, x, y):
        r = math.hypot(x, y)
        if r <= 1e-9:
            return True
        a = math.atan2(y, x)
        if a < self.base:
            a += 2 * math.pi
        ang = self.angles
        rad = self.radii
        lo, hi = 0, self.n - 1
        while lo < hi:
            mid = (lo + hi) // 2
            if ang[mid] < a:
                lo = mid + 1
            else:
                hi = mid
        i0 = lo - 1 if lo > 0 else self.n - 1
        i1 = lo
        span = ang[i1] - ang[i0]
        t = (a - ang[i0]) / span if span > 0 else 0.0
        bound = rad[i0] + (rad[i1] - rad[i0]) * t
        return r <= bound


def _chaikin(pts: list, iters: int = 3) -> list:
    """Corner-cutting smoothing (keeps the outline hugging the block union)."""
    for _ in range(iters):
        out = []
        n = len(pts)
        for k in range(n):
            ax, ay = pts[k]
            bx, by = pts[(k + 1) % n]
            out.append((0.75 * ax + 0.25 * bx, 0.75 * ay + 0.25 * by))
            out.append((0.25 * ax + 0.75 * bx, 0.25 * ay + 0.75 * by))
        pts = out
    return pts


def _block_union_outline(mask: set, n: int, ext: float, step: float) -> list:
    """Exact orthogonal boundary of the block-mask union as a polygon ring,
    then smoothed. The lake shape therefore IS the footprint of the blocks."""
    from collections import defaultdict
    edges = defaultdict(int)
    for (i, j) in mask:
        c = [(i, j), (i, j + 1), (i + 1, j + 1), (i + 1, j)]  # CCW corners
        segs = [(c[0], c[1]), (c[1], c[2]), (c[2], c[3]), (c[3], c[0])]
        for aa, bb in segs:
            k = (aa, bb) if aa <= bb else (bb, aa)
            edges[k] += 1
    # boundary edges = used exactly once
    bnd = defaultdict(list)
    for (aa, bb), c in edges.items():
        if c == 1:
            bnd[aa].append(bb)
            bnd[bb].append(aa)
    # walk rings
    rings = []
    used = set()
    for aa, nbrs in bnd.items():
        for bb in nbrs:
            e = tuple(sorted((aa, bb)))
            if e in used:
                continue
            ring = [aa]
            used.add(e)
            cur, prev = bb, aa
            guard = 0
            while cur != aa and guard < 400000:
                ring.append(cur)
                nxts = [v for v in bnd[cur]
                        if v != prev and tuple(sorted((cur, v))) not in used]
                if not nxts:
                    break
                nx = nxts[0]
                used.add(tuple(sorted((cur, nx))))
                prev, cur = cur, nx
                guard += 1
            rings.append(ring)
            if len(rings) > 8:
                break
    ring = max(rings, key=len) if rings else [(0, 0)]
    verts = [(-ext + jv * step, ext - iv * step) for (iv, jv) in ring]
    # close the ring explicitly (first point repeated)
    verts.append(verts[0])
    return verts


def _point_in_block(x, y, bx, by, half, ang):
    ang = math.radians(ang)
    dx, dy = x - bx, y - by
    u = dx * math.cos(ang) + dy * math.sin(ang)
    v = -dx * math.sin(ang) + dy * math.cos(ang)
    return abs(u) <= half and abs(v) <= half


def _coverage(mask, blocks, ext, step, subs=(-0.33, 0.0, 0.33)):
    """Fraction of masked area covered by block squares (rotated).
    Fast: only blocks in a ±2-cell window around each sample are tested."""
    bycell = {}
    for b in blocks:
        bycell.setdefault((b["row"], b["col"]), []).append(b)
    total = 0
    covered = 0
    for (i, j) in mask:
        cxb = -ext + (j + 0.5) * step
        cyb = ext - (i + 0.5) * step
        cand = []
        for di in range(-2, 3):
            for dj in range(-2, 3):
                for b in bycell.get((i + di, j + dj), ()):
                    cand.append(b)
        for ox in subs:
            for oy in subs:
                total += 1
                sx = cxb + ox * step
                sy = cyb + oy * step
                for b in cand:
                    if _point_in_block(sx, sy, b["bx"], b["by"],
                                       b["half"], b["ang"]):
                        covered += 1
                        break
    return covered / max(1, total)


def _polygon_area(pts: list) -> float:
    s = 0.0
    n = len(pts)
    for i in range(n):
        x1, y1 = pts[i]
        x2, y2 = pts[(i + 1) % n]
        s += x1 * y2 - x2 * y1
    return abs(s) / 2.0


def _inside(x: float, y: float, poly: list) -> bool:
    n = len(poly)
    c = False
    for i in range(n):
        x1, y1 = poly[i]
        x2, y2 = poly[(i + 1) % n]
        if ((y1 > y) != (y2 > y)) and \
           (x < (x2 - x1) * (y - y1) / (y2 - y1) + x1):
            c = not c
    return c


def _distance_transform(rows: int, cols: int, interior: set):
    """Chebyshev distance from shoreline -> deepest cells."""
    from collections import deque
    dist = [[-1] * cols for _ in range(rows)]
    dq = deque()
    for (i, j) in interior:
        for di, dj in ((1, 0), (-1, 0), (0, 1), (0, -1),
                       (1, 1), (1, -1), (-1, 1), (-1, -1)):
            ni, nj = i + di, j + dj
            if (ni, nj) not in interior:
                dist[i][j] = 1
                dq.append((i, j))
                break
    while dq:
        i, j = dq.popleft()
        for di, dj in ((1, 0), (-1, 0), (0, 1), (0, -1),
                       (1, 1), (1, -1), (-1, 1), (-1, -1)):
            ni, nj = i + di, j + dj
            if 0 <= ni < rows and 0 <= nj < cols and (ni, nj) in interior \
                    and dist[ni][nj] == -1:
                dist[ni][nj] = dist[i][j] + 1
                dq.append((ni, nj))
    maxd = max(dist[i][j] for (i, j) in interior)
    return dist, maxd


def _clip(v, lo, hi):
    return max(lo, min(hi, v))


# Sensor recipes that force each prediction zone (used for coverage).
ZONE_FIX = {
    "Live Algae / Microalgae Dominance (Organic waste driver)":
        {"ph_delta": 1.2, "turbidity_ntu": 320.0, "baseline_turb": 45.0, "dT_c": 1.2},
    "Mixed Organic & Inorganic suspension":
        {"ph_delta": 0.5, "turbidity_ntu": 60.0, "baseline_turb": 70.0, "dT_c": 1.0},
    ("Inorganic Silt / Mud / Clay (Non-biological cloudiness) - High Turbidity"):
        {"ph_delta": 0.03, "turbidity_ntu": 380.0, "baseline_turb": 395.0, "dT_c": 2.6},
    ("Low biological activity / near-clear conditions (OFI < 0.3, Low Turbidity)"):
        {"ph_delta": 0.05, "turbidity_ntu": 2.5, "baseline_turb": 180.0, "dT_c": 1.8},
    "Active Algae/Cyanobacteria Bloom (Nighttime O2 drop risk)":
        {"ph_delta": 1.5, "turbidity_ntu": 90.0, "baseline_turb": 100.0, "dT_c": 1.5},
    "Stable biological activity":
        {"ph_delta": 0.7, "turbidity_ntu": 25.0, "baseline_turb": 120.0, "dT_c": 1.2},
    "Non-photosynthetic silt cloudiness (High Turbidity)":
        {"ph_delta": 0.04, "turbidity_ntu": 260.0, "baseline_turb": 280.0, "dT_c": 2.2},
    "Low algae activity / clear water (Low Turbidity)":
        {"ph_delta": 0.08, "turbidity_ntu": 2.0, "baseline_turb": 90.0, "dT_c": 1.0},
    "Severe murky water (Bottom plants shaded, dying)":
        {"ph_delta": 0.2, "turbidity_ntu": 450.0, "baseline_turb": 400.0, "dT_c": 1.5},
    "Normal moderate clarity":
        {"ph_delta": 0.4, "turbidity_ntu": 120.0, "baseline_turb": 130.0, "dT_c": 1.4},
    "High transparency / Clear water column":
        {"ph_delta": 0.5, "turbidity_ntu": 4.0, "baseline_turb": 60.0, "dT_c": 1.1},
    "Inorganic Salt Ingress / Fertilizer / Mineral Runoff":
        {"ph_delta": 0.3, "turbidity_ntu": 4.0, "baseline_turb": 80.0, "tds_ppm": 4200.0, "dT_c": 1.3},
    "Mixed Mineral & Particulate background":
        {"ph_delta": 0.4, "turbidity_ntu": 60.0, "baseline_turb": 100.0, "tds_ppm": 520.0, "dT_c": 1.3},
    "Heavy Organic Waste / Manure / Decaying Fish Feed":
        {"ph_delta": 0.2, "turbidity_ntu": 150.0, "baseline_turb": 120.0, "tds_ppm": 80.0, "dT_c": 1.6},
    "Dissolved Ion Dominance (Chemical/runoff treatment needed)":
        {"ph_delta": 0.3, "turbidity_ntu": 4.0, "baseline_turb": 80.0, "tds_ppm": 4200.0, "dT_c": 1.3},
    "Balanced dissolved & suspended load":
        {"ph_delta": 0.4, "turbidity_ntu": 60.0, "baseline_turb": 100.0, "tds_ppm": 520.0, "dT_c": 1.3},
    "Particulate Suspended Dominance (Mechanical filtration needed)":
        {"ph_delta": 0.2, "turbidity_ntu": 180.0, "baseline_turb": 140.0, "tds_ppm": 60.0, "dT_c": 1.6},
    "Warm Water Stress Zone (Low O2 capacity)":
        {"temperature_c": 40.0, "ph_delta": 0.4, "turbidity_ntu": 50.0, "baseline_turb": 90.0, "tds_ppm": 1500.0, "dT_c": 1.4},
    "Moderate O2 capacity":
        {"temperature_c": 28.0, "ph_delta": 0.5, "turbidity_ntu": 60.0, "baseline_turb": 100.0, "tds_ppm": 600.0, "dT_c": 1.3},
    "Optimal Cool Water Oxygen Storage":
        {"temperature_c": 12.0, "ph_delta": 0.6, "turbidity_ntu": 30.0, "baseline_turb": 80.0, "tds_ppm": 200.0, "dT_c": 1.2},
}

METRIC_KEYS = ["OFI", "DABI", "SDest", "SOR", "DSLR", "DOsat"]


def _interior_units(rp: "_RadialPoly", ext: float, step: float) -> list:
    """Grid centres (row, col, x, y) that fall inside the lake."""
    n = math.ceil(2 * ext / step)
    units = []
    for i in range(n):
        y = ext - (i + 0.5) * step                  # row 0 = north
        for j in range(n):
            x = -ext + (j + 0.5) * step
            if rp.inside(x, y):
                units.append((i, j, x, y))
    return units


def _find_step(poly, ext, target) -> tuple:
    """Find a grid pitch whose interior-cell count equals `target` exactly."""
    area = _polygon_area(poly)
    rp = _RadialPoly(poly)
    lo = max(math.sqrt(area / (target * 2.2)), 5.0)
    hi = math.sqrt(area / (target * 0.45))
    for _ in range(70):
        mid = (lo + hi) / 2
        if len(_interior_units(rp, ext, mid)) > target:
            lo = mid
        else:
            hi = mid
    for f in (1.0, 0.997, 1.003, 0.994, 1.006, 0.991, 1.009,
              0.988, 0.985, 1.012, 1.015, 0.982, 1.018):
        step = hi * f
        count = len(_interior_units(rp, ext, step))
        if count == target:
            return step, count
    best, best_d = (hi, len(_interior_units(rp, ext, hi))), 1e9
    for f in (1.0, 0.99, 1.01, 0.98, 1.02, 0.95, 1.05, 0.9, 1.1):
        step = hi * f
        count = len(_interior_units(rp, ext, step))
        if abs(count - target) < best_d:
            best, best_d = (step, count), abs(count - target)
    return best


def _synthetic_cell(x, y, row, col, overrides, rng, size=30.0, rot=0.0):
    base = {"temperature_c": 22.0, "ph_delta": 0.2, "turbidity_ntu": 40.0,
            "baseline_turb": 90.0, "tds_ppm": 300.0, "dT_c": 1.2}
    for k, v in base.items():
        if k not in overrides:
            base[k] = v * (1 + rng.uniform(-0.05, 0.05))
    base.update(overrides)
    sens = {
        "temperature_c": round(_clip(base["temperature_c"], -2.0, 45.0), 1),
        "ph_morning": round(_clip(7.0 + rng.uniform(-0.3, 0.3), 4.0, 10.0), 2),
        "turbidity_ntu": round(_clip(base["turbidity_ntu"], 0.1, 1000.0), 1),
        "baseline_turb": round(_clip(base["baseline_turb"], 0.1, 1000.0), 1),
        "tds_ppm": round(_clip(base["tds_ppm"], 0.0, 5000.0), 1),
        "dT_c": round(_clip(base["dT_c"], 0.1, 3.0), 2),
    }
    sens["ph_midday"] = round(
        _clip(sens["ph_morning"] + base["ph_delta"], 4.0, 10.0), 2)
    m = compute_metrics(sens)
    p = predict_all(sens, m)
    return {"row": row, "col": col, "x": x, "y": y, "depth": 0.5,
            "size": round(size, 1), "rot": round(rot, 1),
            "temperature_c": sens["temperature_c"],
            "ph_morning": sens["ph_morning"], "ph_midday": sens["ph_midday"],
            "turbidity_ntu": sens["turbidity_ntu"],
            "baseline_turb": sens["baseline_turb"],
            "tds_ppm": sens["tds_ppm"], "dT_c": sens["dT_c"],
            "metrics": {k: round(m[k], 4) for k in METRIC_KEYS},
            "predictions": p}


def build_lake_dataset(seed: int = 42, cells_target: int = 500) -> dict:
    """Build a ~1 sq km lake where the number of blocks equals the number of
    rows exactly, the boxes tile the lake with NO gaps, and the lake outline
    is derived from the block coordinates themselves (so every new seed /
    coordinate set produces a visibly different shape). Layout is not a
    standard lattice: blocks are slightly jittered and individually rotated."""
    poly = _lake_polygon(seed)
    xs = [p[0] for p in poly]
    ys = [p[1] for p in poly]
    ext = max(max(map(abs, xs)), max(map(abs, ys))) * 1.04

    rng = random.Random(seed ^ 0xC0FFEE)

    # 1) pitch so the interior lattice count == cells_target exactly
    step, _ = _find_step(poly, ext, cells_target)
    n_grid = math.ceil(2 * ext / step)
    units = _interior_units(_RadialPoly(poly), ext, step)
    exact = len(units) == cells_target
    if len(units) < cells_target:                    # rare: pad to exact count
        extra = cells_target - len(units)
        for _ in range(extra):
            u = rng.choice(units)
            units.append((u[0], u[1],
                          u[2] + rng.uniform(-step, step),
                          u[3] + rng.uniform(-step, step)))
    elif len(units) > cells_target:
        units = units[:cells_target]

    mask = {(i, j) for (i, j, _, _) in units}        # lattice footprint

    # 2) jitter fill positions slightly; boundary blocks stay on the rim so
    #    the outline (= block union) wraps them exactly
    jittered = []
    for (i, j, x, y) in units:
        is_boundary = any((i + di, j + dj) not in mask
                          for di, dj in ((1, 0), (-1, 0), (0, 1), (0, -1)))
        if is_boundary:
            jittered.append((i, j, x, y))
        else:
            jittered.append((i, j,
                             x + rng.uniform(-0.10, 0.10) * step,
                             y + rng.uniform(-0.10, 0.10) * step))

    # 3) distance transform (depth) grid from the footprint
    dist, maxd = _distance_transform(n_grid, n_grid, mask)

    # inlet reference near angle 2.5 rad (for the runoff gradient)
    ang = 2.5
    inlet = min(poly, key=lambda p: abs((math.atan2(p[1], p[0]) + 3 * math.pi)
                                        % (2 * math.pi) - ang))
    inlet = (inlet[0] * 1.10, inlet[1] * 1.10)
    sig2 = (260.0 ** 2)

    cells = []
    ylim = ext
    for (i, j, x, y) in jittered:
        depth = (dist[i][j] / maxd) if maxd else 0.5
        dx, dy = x - inlet[0], y - inlet[1]
        g = math.exp(-(dx * dx + dy * dy) / (2 * sig2))     # inlet factor
        nst = (y + ylim) / (2 * ylim)                       # 0 south, 1 north

        algae = _clip(0.18 + 0.55 * depth + 0.30 * g
                      + rng.gauss(0, 0.12), 0.0, 1.0)
        turb = _clip(12 + 260 * g ** 1.6 + 70 * algae * (1 + 3 * g)
                     + rng.gauss(0, 20), 0.1, 1000.0)
        base_t = _clip(40 + 60 * g + rng.gauss(0, 18), 1.0, 1000.0)
        ph_m = _clip(6.9 + 0.35 * depth + 0.15 * g
                     + rng.gauss(0, 0.15), 4.0, 10.0)
        ph_d = _clip(-0.02 + 1.25 * algae * math.exp(-turb / 260)
                     + rng.gauss(0, 0.08), -0.5, 2.0)
        temp = _clip(20 + 6 * (1 - nst) - 3 * depth
                     + rng.gauss(0, 1.2), 10.0, 33.0)
        tds = _clip(90 + 950 * g + 220 * algae * depth
                    + rng.gauss(0, 150), 0.0, 5000.0)
        dT = _clip(0.9 + 1.1 * abs(ph_d) + 0.5 * (1 - depth)
                   + rng.gauss(0, 0.35), 0.1, 3.0)

        sens = {
            "temperature_c": round(temp, 1),
            "ph_morning": round(ph_m, 2),
            "ph_midday": round(_clip(ph_m + ph_d, 4.0, 10.0), 2),
            "turbidity_ntu": round(turb, 1),
            "baseline_turb": round(base_t, 1),
            "tds_ppm": round(tds, 1),
            "dT_c": round(dT, 2),
        }
        m = compute_metrics(sens)
        p = predict_all(sens, m)

        # 4) per-block visual size (half-side) + rotation
        half = step * rng.uniform(0.52, 0.58)
        rot = rng.uniform(-15.0, 15.0)
        cells.append({"row": i, "col": j, "x": round(x, 1),
                      "y": round(y, 1), "depth": round(depth, 3),
                      "size": round(half, 2), "rot": round(rot, 2),
                      "ph_morning": sens["ph_morning"],
                      "ph_midday": sens["ph_midday"],
                      "temperature_c": sens["temperature_c"],
                      "turbidity_ntu": sens["turbidity_ntu"],
                      "baseline_turb": sens["baseline_turb"],
                      "tds_ppm": sens["tds_ppm"], "dT_c": sens["dT_c"],
                      "metrics": {k: round(m[k], 4) for k in METRIC_KEYS},
                      "predictions": p})

    # 5) Guarantee every prediction zone is present (rare/edge cases).
    base_count = len(cells)
    seen = {k: set() for k in METRIC_KEYS}
    for c in cells:
        for k in METRIC_KEYS:
            seen[k].add(c["predictions"][k])
    missing = {k: [s for s in ALL_PREDICTION_STRINGS[k]
                   if s not in seen[k]] for k in METRIC_KEYS}
    for k, strings in missing.items():
        for s in strings:
            base_cell = rng.choice(cells)
            sc = _synthetic_cell(base_cell["x"], base_cell["y"],
                                 base_cell["row"], base_cell["col"],
                                 ZONE_FIX[s], rng,
                                 size=base_cell["size"],
                                 rot=base_cell["rot"])
            cells.append(sc)

    # rows must equal blocks exactly -> drop surplus originals (coverage kept)
    over = len(cells) - cells_target
    if over > 0:
        for ii in sorted(rng.sample(range(base_count), min(over, base_count)),
                         reverse=True):
            cells.pop(ii)

    # 6) gap-free tiling: grow block half-sizes until the mask is ≥99.8%
    grown = [dict(bx=c["x"], by=c["y"], half=c["size"], ang=c["rot"],
                  row=c["row"], col=c["col"]) for c in cells]
    for _ in range(8):
        cov = _coverage(mask, grown, ext, step)
        if cov >= 0.998:
            break
        for b in grown:
            b["half"] *= 1.12
    for c, b in zip(cells, grown):
        c["size"] = round(b["half"], 2)

    # 7) lake outline = footprint of the blocks (smoothed), scaled up so it
    #    hugs the outer block edges
    raw = _block_union_outline(mask, n_grid, ext, step)[:-1]       # drop dup
    smooth = _chaikin(raw, iters=3)
    sa = _polygon_area(smooth)
    mu = len(mask) * step * step
    if sa > 0:
        fac = math.sqrt(mu / sa) * 1.05
        cx = sum(p[0] for p in smooth) / len(smooth)
        cy = sum(p[1] for p in smooth) / len(smooth)
        outline = [(cx + (px - cx) * fac, cy + (py - cy) * fac)
                   for px, py in smooth]
    else:
        outline = smooth

    # inlet marker sitting on the outline rim (near the chosen angle)
    rim = min(outline, key=lambda p: abs((math.atan2(p[1], p[0]) + 3 * math.pi)
                                         % (2 * math.pi) - ang))
    inlet = (rim[0] * 1.04, rim[1] * 1.04)

    return {
        "seed": seed,
        "lake_area_km2": round(mu / 1e6, 3),
        "grid": (n_grid, n_grid),
        "step": round(step, 1),
        "cells_total": len(cells),
        "rows_requested": cells_target,
        "rows_exact": exact,
        "outline": [[round(px, 1), round(py, 1)] for px, py in outline],
        "inlet": [round(inlet[0], 1), round(inlet[1], 1)],
        "cells": cells,
    }


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main():
    ap = argparse.ArgumentParser(description="Water-quality metric simulator")
    ap.add_argument("--rows", type=int, default=1000,
                    help="number of random sensor records to generate")
    ap.add_argument("--out", default="metric_predictions.xlsx",
                    help="output Excel file name")
    ap.add_argument("--seed", type=int, default=42, help="random seed")
    args = ap.parse_args()

    rng = random.Random(args.seed)
    records = [gen_sensor_record(rng) for _ in range(args.rows)]

    before = len(records)
    ensure_coverage(records, args.seed)
    print(f"Generated {before} random rows + {len(records) - before} "
          f"extra rows added to cover every prediction case.")

    rows_data = [build_row(rec, i + 1) for i, rec in enumerate(records)]

    write_excel(rows_data, args.out)
    print(f"Wrote {len(rows_data)} rows to {args.out}")

    # Quick preview of first 3 rows' numeric metrics
    import pandas as pd
    preview = pd.DataFrame(rows_data[:3])
    print(preview[[c for c in preview.columns if c.endswith("Value")]])


if __name__ == "__main__":
    main()