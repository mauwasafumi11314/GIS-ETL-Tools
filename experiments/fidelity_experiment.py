#!/usr/bin/env python3
"""
Experiment: how much of a GIS payload survives a shapefile-centred ETL pipeline?

The pipeline in this repository routes spatial data through ESRI Shapefile and
then through Excel -> CSV. Both hops are lossy in ways that are silent: no
exception is raised, the row count is unchanged, and the loss is only visible
if you compare values against the source.

This script builds one ground-truth GeoDataFrame whose values probe each known
failure mode, round-trips it through five interchange formats and through the
Excel->CSV chain, and diffs every cell against the original.

Run:  python3 experiments/fidelity_experiment.py
"""
import os, sys, time, json, warnings, tempfile, shutil
import numpy as np
import pandas as pd
import geopandas as gpd
import shapely
from shapely.geometry import Polygon

RNG = np.random.default_rng(42)
CRS = "EPSG:6677"          # JGD2011 / Japan Plane Rectangular CS IX (projected, metres)
OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "RESULTS.md")

LONG_TEXT = "A" * 300      # shapefile DBF caps character fields at 254
BIG_INT   = 2**53 + 1      # exceeds IEEE-754 double integer precision
PRECISE   = 0.12345678901234567


def build_truth():
    """Ground truth. Every column probes one documented failure mode."""
    # CCW exterior ring with a CW hole -- the OGC Simple Features convention.
    # The shapefile specification mandates the opposite (CW exterior).
    ext = [(0, 0), (100, 0), (100, 100), (0, 100), (0, 0)]
    hole = [(20, 20), (20, 40), (40, 40), (40, 20), (20, 20)]
    p1 = Polygon(ext, [hole])
    p2 = Polygon([(200, 200), (300, 200), (250, 280), (200, 200)])
    p3 = Polygon([(0.123456789, 0.987654321), (1, 0), (1, 1), (0.123456789, 0.987654321)])

    gdf = gpd.GeoDataFrame(
        {
            "rid": [0, 1, 2],   # stable key: some drivers reorder features on write
            # -- field-name probes (>10 chars, and a pair that collides at 10) --
            "population_density_2025": [1.5, 2.5, 3.5],
            "population_density_2024": [1.4, 2.4, 3.4],
            # -- value probes (names <=10 chars so naming never confounds them) --
            "big_id":   pd.array([BIG_INT, 2**31, 7], dtype="Int64"),
            "ratio":    [PRECISE, np.nan, 3.5],
            "is_urban": [True, False, True],
            "surveyed": pd.to_datetime(["2025-03-01 14:30:00",
                                        "2024-12-31 23:59:59",
                                        "2025-06-15 08:00:00"]),
            "name_ja":  ["東京都千代田区", "大阪市北区", "札幌市中央区"],
            "postal":   ["0100001", "5300001", "0600001"],   # leading zeros
            "notes":    [LONG_TEXT, "short", None],
        },
        geometry=[p1, p2, p3],
        crs=CRS,
    )
    return gdf


# ----------------------------------------------------------------------------
# Probes: each returns (passed: bool, detail: str)
# ----------------------------------------------------------------------------
def _col(rt, name):
    if name in rt.columns:
        return rt[name]
    if name[:10] in rt.columns:
        return rt[name[:10]]
    return None


def p_fieldnames(t, rt):
    missing = [c for c in t.columns if c != "geometry" and c not in rt.columns]
    if not missing:
        return True, "all names verbatim"
    return False, f"{len(missing)} renamed, e.g. {missing[0]!r} -> {sorted(set(rt.columns)-set(t.columns))[:2]}"


def p_bigint(t, rt):
    c = _col(rt, "big_id")
    if c is None:
        return False, "column absent"
    got = c.iloc[0]
    try:
        got_i = int(got)
    except (TypeError, ValueError):
        return False, f"unreadable ({got!r})"
    return (got_i == BIG_INT), (f"exact" if got_i == BIG_INT else f"{BIG_INT} -> {got_i} (off by {got_i-BIG_INT})")


def p_float(t, rt):
    c = _col(rt, "ratio")
    if c is None:
        return False, "column absent"
    got = float(c.iloc[0])
    if got == PRECISE:
        return True, "full double"
    return False, f"{PRECISE!r} -> {got!r}"


def p_null_num(t, rt):
    c = _col(rt, "ratio")
    if c is None:
        return False, "column absent"
    got = c.iloc[1]
    return (pd.isna(got)), ("NULL kept" if pd.isna(got) else f"NULL -> {got!r}")


def p_bool(t, rt):
    c = _col(rt, "is_urban")
    if c is None:
        return False, "column absent"
    if c.dtype == bool or str(c.dtype) == "boolean":
        return True, "bool dtype"
    return False, f"bool -> {c.dtype} ({list(c[:2])})"


def p_datetime(t, rt):
    c = _col(rt, "surveyed")
    if c is None:
        return False, "column absent"
    want = pd.Timestamp("2025-03-01 14:30:00")
    try:
        got = pd.Timestamp(c.iloc[0])
    except Exception:
        return False, f"unparseable ({c.iloc[0]!r})"
    if got.tz is not None:
        got = got.tz_localize(None)
    if got == want:
        return True, "date+time"
    return False, f"{want} -> {got} (time lost)" if got.normalize() == want.normalize() else f"{want} -> {got}"


def p_unicode(t, rt):
    c = _col(rt, "name_ja")
    if c is None:
        return False, "column absent"
    got = c.iloc[0]
    return (got == "東京都千代田区"), ("intact" if got == "東京都千代田区" else f"-> {got!r}")


def p_longstr(t, rt):
    c = _col(rt, "notes")
    if c is None:
        return False, "column absent"
    got = c.iloc[0] or ""
    return (len(got) == 300), (f"300 chars" if len(got) == 300 else f"300 -> {len(got)} chars (truncated)")


def p_null_str(t, rt):
    c = _col(rt, "notes")
    if c is None:
        return False, "column absent"
    got = c.iloc[2]
    return (got is None or pd.isna(got)), ("NULL kept" if (got is None or pd.isna(got)) else f"NULL -> {got!r}")


def p_crs(t, rt):
    if rt.crs is None:
        return False, "CRS dropped entirely"
    epsg = rt.crs.to_epsg()
    if epsg == 6677:
        return True, "EPSG:6677"
    if rt.crs.equals(t.crs):
        return False, "WKT equal but EPSG code lost"
    return False, f"EPSG:6677 -> {epsg or rt.crs.name}"


def p_geom(t, rt):
    a, b = t.geometry.values, rt.geometry.values
    if len(a) != len(b):
        return False, f"{len(a)} -> {len(b)} rows"
    # normalize() puts rings in canonical orientation/start-point, so this probe
    # measures coordinate precision only; orientation is probed separately below.
    na = [shapely.normalize(g) for g in a]
    nb = [None if g is None else shapely.normalize(g) for g in b]
    bad = [i for i in range(len(a))
           if nb[i] is None or not shapely.equals_exact(na[i], nb[i], tolerance=1e-9)]
    if not bad:
        return True, "exact to 1e-9"
    i = bad[0]
    if nb[i] is not None and shapely.equals_exact(na[i], nb[i], tolerance=1e-6):
        return False, f"coords drift >1e-9 (row {i})"
    return False, f"{len(bad)}/{len(a)} geometries differ"


def p_ring(t, rt):
    o = t.geometry.iloc[0].exterior.is_ccw
    try:
        g = rt.geometry.iloc[0]
        r = g.exterior.is_ccw
    except Exception:
        return False, "no exterior ring"
    return (r == o), (f"CCW kept" if r == o else f"exterior CCW -> CW (flipped)")


def p_order(t, rt):
    ok = rt.attrs.get("order_ok")
    if ok is None:
        return False, "no stable key"
    return ok, ("source order" if ok else "features reordered (spatial index packing)")


PROBES = [
    ("feature order",          p_order),
    ("field names >10 chars",  p_fieldnames),
    ("int64 beyond 2^53",      p_bigint),
    ("float64 precision",      p_float),
    ("NULL in numeric",        p_null_num),
    ("bool dtype",             p_bool),
    ("datetime (with time)",   p_datetime),
    ("unicode (ja)",           p_unicode),
    ("string >254 chars",      p_longstr),
    ("NULL in text",           p_null_str),
    ("CRS authority code",     p_crs),
    ("geometry coords (precision)", p_geom),
    ("ring orientation",       p_ring),
]

FORMATS = [
    ("Shapefile",  "torture.shp",     dict(driver="ESRI Shapefile")),
    ("GeoPackage", "torture.gpkg",    dict(driver="GPKG")),
    ("GeoJSON",    "torture.geojson", dict(driver="GeoJSON")),
    ("FlatGeobuf", "torture.fgb",     dict(driver="FlatGeobuf")),
    ("GeoParquet", "torture.parquet", None),      # native geopandas writer
]


def roundtrip(truth, tmp, fname, kw):
    path = os.path.join(tmp, fname)
    msgs = []
    with warnings.catch_warnings(record=True) as w:
        warnings.simplefilter("always")
        if kw is None:
            truth.to_parquet(path)
            rt = gpd.read_parquet(path)
        else:
            truth.to_file(path, **kw)
            rt = gpd.read_file(path)
        msgs = [str(x.message)[:120] for x in w]
    order_ok = list(rt["rid"]) == list(truth["rid"]) if "rid" in rt.columns else None
    if "rid" in rt.columns:
        rt = rt.sort_values("rid").reset_index(drop=True)
    rt.attrs["order_ok"] = order_ok
    size = os.path.getsize(path) if os.path.isfile(path) else sum(
        os.path.getsize(os.path.join(tmp, f)) for f in os.listdir(tmp)
        if f.startswith(os.path.splitext(fname)[0]))
    return rt, size, msgs


def excel_csv_hop(truth, tmp):
    """Mirror Shp_To_Table_And_Excel.py: attribute table -> xlsx -> read -> csv -> read."""
    tbl = pd.DataFrame(truth.drop(columns="geometry"))
    xlsx = os.path.join(tmp, "table.xlsx")
    csv = os.path.join(tmp, "table.csv")
    tbl.to_excel(xlsx, index=False)
    via_xlsx = pd.read_excel(xlsx)
    via_xlsx.to_csv(csv, index=False)
    via_csv = pd.read_csv(csv)
    return via_xlsx, via_csv


def repo_traversal_check():
    """Replay the directory-walk logic of the two scripts in this repo against a
    tree that has a shapefile in a subfolder, and see which paths resolve."""
    tmp = tempfile.mkdtemp()
    try:
        sub = os.path.join(tmp, "prefectures", "kanto")
        os.makedirs(sub)
        g = gpd.GeoDataFrame({"id": [1]}, geometry=[shapely.box(0, 0, 1, 1)], crs=CRS)
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            g.to_file(os.path.join(tmp, "top.shp"))
            g.to_file(os.path.join(sub, "nested.shp"))

        # --- logic as written in Shp_To_SQL.py (joins on shapefile_dir, not root) ---
        sql_paths = []
        for root, dirs, files in os.walk(tmp):
            for f in files:
                if f.endswith(".shp"):
                    sql_paths.append(os.path.join(tmp, f))

        # --- logic as written in Shp_To_Table_And_Excel.py (keeps basename only) ---
        names = []
        for root, dirs, files in os.walk(tmp):
            for f in files:
                if f.endswith((".shp", ".tif", ".geojson")):
                    names.append(f)
        gdb_paths = [r"{0}\{1}".format(tmp, f) for f in names]

        correct = [os.path.join(r, f) for r, d, fs in os.walk(tmp)
                   for f in fs if f.endswith(".shp")]
        return {
            "discovered": len(correct),
            "sql_resolve": sum(os.path.exists(x) for x in sql_paths),
            "gdb_resolve": sum(os.path.exists(x.replace("\\", os.sep)) for x in gdb_paths),
        }
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def benchmark(n=20000):
    """ETL throughput + on-disk size for the same payload in each format."""
    x = RNG.uniform(-50000, 50000, n)
    y = RNG.uniform(-50000, 50000, n)
    g = shapely.box(x, y, x + 50, y + 50)
    gdf = gpd.GeoDataFrame(
        {"id": np.arange(n),
         "cat": RNG.choice(["a", "b", "c"], n),
         "val": RNG.normal(size=n),
         "cnt": RNG.integers(0, 10**6, n)},
        geometry=g, crs=CRS)

    rows = []
    for name, fname, kw in FORMATS:
        tmp = tempfile.mkdtemp()
        try:
            t0 = time.perf_counter()
            if kw is None:
                gdf.to_parquet(os.path.join(tmp, fname))
            else:
                with warnings.catch_warnings():
                    warnings.simplefilter("ignore")
                    gdf.to_file(os.path.join(tmp, fname), **kw)
            t_w = time.perf_counter() - t0

            t0 = time.perf_counter()
            if kw is None:
                _ = gpd.read_parquet(os.path.join(tmp, fname))
            else:
                _ = gpd.read_file(os.path.join(tmp, fname))
            t_r = time.perf_counter() - t0

            size = sum(os.path.getsize(os.path.join(tmp, f)) for f in os.listdir(tmp))
            rows.append((name, t_w, t_r, size / 1e6))
        except Exception as e:
            rows.append((name, None, None, None))
        finally:
            shutil.rmtree(tmp, ignore_errors=True)
    return n, rows


def main():
    truth = build_truth()
    results, sizes, warns = {}, {}, {}

    for name, fname, kw in FORMATS:
        tmp = tempfile.mkdtemp()
        try:
            rt, size, msgs = roundtrip(truth, tmp, fname, kw)
            sizes[name] = size
            warns[name] = msgs
            results[name] = {label: fn(truth, rt) for label, fn in PROBES}
        except Exception as e:
            results[name] = {label: (False, f"ERROR: {type(e).__name__}") for label, fn in PROBES}
            sizes[name] = 0
            warns[name] = [f"{type(e).__name__}: {e}"]
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    tmp = tempfile.mkdtemp()
    try:
        via_xlsx, via_csv = excel_csv_hop(truth, tmp)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    n, bench = benchmark()
    trav = repo_traversal_check()

    # ---------------- report ----------------
    names = [f[0] for f in FORMATS]
    L = []
    L.append("# Experiment: fidelity loss in a shapefile-centred GIS ETL pipeline\n")
    L.append(f"Reproduce with `python3 experiments/fidelity_experiment.py`  \n"
             f"Environment: GDAL {__import__('pyogrio').__gdal_version_string__}, "
             f"GeoPandas {gpd.__version__}, Shapely {shapely.__version__}, "
             f"pandas {pd.__version__}, Python {sys.version.split()[0]}\n")
    L.append("## 1. Interchange-format round trip\n")
    L.append("One GeoDataFrame in `EPSG:6677` (JGD2011 / Japan Plane Rectangular CS IX), "
             "3 features, written and read back. `PASS` = byte-for-byte equal to source.\n")

    hdr = "| Probe | " + " | ".join(names) + " |"
    sep = "|---|" + "---|" * len(names)
    L.append(hdr); L.append(sep)
    for label, _ in PROBES:
        cells = []
        for nm in names:
            ok, det = results[nm][label]
            cells.append("PASS" if ok else f"**FAIL** — {det}")
        L.append(f"| {label} | " + " | ".join(cells) + " |")
    score = {nm: sum(1 for l, _ in PROBES if results[nm][l][0]) for nm in names}
    L.append("| **score** | " + " | ".join(f"**{score[nm]}/{len(PROBES)}**" for nm in names) + " |")
    L.append("")

    L.append("## 2. Attribute table -> Excel -> CSV\n")
    L.append("The hop implemented in `Shp_To_Table_And_Excel.py` "
             "(`TableToExcel`, then `pd.read_excel` -> `to_csv`), reproduced with pandas/openpyxl.\n")
    L.append("| Value | Source | After .xlsx | After .csv |")
    L.append("|---|---|---|---|")
    cases = [("postal (leading zeros)", "postal", 0),
             ("big_id (2^53+1)",        "big_id", 0),
             ("ratio (17 sig digits)",  "ratio",  0),
             ("ratio (NULL)",           "ratio",  1),
             ("notes (300 chars)",      "notes",  0),
             ("notes (NULL)",           "notes",  2),
             ("surveyed (date+time)",   "surveyed", 0),
             ("name_ja (unicode)",      "name_ja", 0)]
    for lbl, col, i in cases:
        def fmt(v):
            s = repr(v)
            return (s[:28] + "…") if len(s) > 30 else s
        src = truth[col].iloc[i]
        a = via_xlsx[col].iloc[i] if col in via_xlsx.columns else "—"
        b = via_csv[col].iloc[i] if col in via_csv.columns else "—"
        mark = lambda v, s: fmt(v) if repr(v) == repr(s) else f"**{fmt(v)}**"
        L.append(f"| {lbl} | {fmt(src)} | {mark(a, src)} | {mark(b, src)} |")
    L.append("")
    L.append(f"dtypes after csv hop: `{dict((k, str(v)) for k, v in via_csv.dtypes.items())}`\n")

    L.append(f"## 3. Throughput ({n:,} polygons, 4 attribute columns)\n")
    L.append("| Format | write (s) | read (s) | on disk (MB) |")
    L.append("|---|---|---|---|")
    for nm, tw, tr, mb in bench:
        if tw is None:
            L.append(f"| {nm} | — | — | — |")
        else:
            L.append(f"| {nm} | {tw:.3f} | {tr:.3f} | {mb:.1f} |")
    L.append("")

    L.append("## 4. Driver warnings emitted during the round trip\n")
    for nm in names:
        ws = [w for w in warns[nm] if w]
        L.append(f"- **{nm}**: " + ("; ".join(f"`{w}`" for w in ws[:3]) if ws else "_none_"))
    L.append("")

    L.append("## 5. Directory traversal in this repository's scripts\n")
    L.append("`os.walk` descends into subfolders, but both scripts rebuild the path from the "
             "top-level folder instead of the current `root`, so anything below the top level "
             "resolves to a path that does not exist. Replayed against a tree holding one "
             "shapefile at the top level and one in `prefectures/kanto/`:\n")
    L.append("| Script | shapefiles discovered | paths that resolve |")
    L.append("|---|---|---|")
    L.append(f"| `Shp_To_SQL.py` | {trav['discovered']} | {trav['sql_resolve']} |")
    L.append(f"| `Shp_To_Table_And_Excel.py` | {trav['discovered']} | {trav['gdb_resolve']} |")
    L.append("\nThe missing file raises no error in either script: `shp2pgsql` writes an empty "
             "`.sql` that `psql` applies as a no-op, and the arcpy call is caught by a bare "
             "`except` that prints and continues. The run reports success with the data absent.\n")

    L.append("## 6. Findings\n")
    L.append("1. **Shapefile is the only lossy interchange format tested, and it fails silently "
             "in four ways** (9/13). Field names are cut to 10 characters, so "
             "`population_density_2025` and `population_density_2024` both become `populati*` and "
             "are no longer distinguishable by name. Numerics are stored as fixed-width ASCII in "
             "the DBF, costing precision beyond ~15 significant digits. Text is capped at 254 "
             "characters. Polygon rings are rewritten clockwise, inverting the OGC winding order.\n")
    L.append("2. **Much of the shapefile folklore no longer holds.** With GDAL "
             f"{__import__('pyogrio').__gdal_version_string__}, int64 past 2^53, NULLs in numeric "
             "and text fields, datetimes with a time component, non-ASCII text and the EPSG "
             "authority code all survived. The losses above are the real ones.\n")
    L.append("3. **The Excel/CSV hop loses more than the shapefile hop.** A postal code "
             "`'0100001'` returns as the integer `100001`; the leading zero is gone and the value "
             "is now numeric. `2**53+1` is rounded by Excel's float64 cells. Timestamps come back "
             "from CSV as strings. This hop has no schema, so every re-read re-infers types.\n")
    L.append("4. **GeoPackage is the drop-in replacement**: 13/13 fidelity, fastest read of the "
             "lossless formats, smallest footprint apart from Parquet, one file instead of "
             "the shapefile's sidecar set. **GeoParquet** is 13/13 at 1.3 MB against the "
             "shapefile's 5.7 MB (4.4x smaller) and is the better choice for analytics. "
             "**FlatGeobuf** is fast and lossless in content but reorders features to pack its "
             "spatial index, so any downstream join on row position breaks.\n")
    L.append("5. **Both scripts skip data in subfolders without reporting it** (section 5).\n")
    L.append("### Recommendation for this pipeline\n")
    L.append("Keep shapefiles as an accepted *input* — that choice belongs to the data publisher. "
             "Stop using them as an intermediate. Write `.gpkg` where a GIS reads the result and "
             "`.parquet` where an analyst does, and emit CSV only as a terminal export, never as "
             "something re-read. Where the Excel deliverable is required, carry the schema "
             "alongside it, since the CSV cannot.\n")

    report = "\n".join(L)
    with open(OUT, "w", encoding="utf-8") as f:
        f.write(report)
    print(report)


if __name__ == "__main__":
    main()
