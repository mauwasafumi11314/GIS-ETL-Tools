# Experiment: fidelity loss in a shapefile-centred GIS ETL pipeline

Reproduce with `python3 experiments/fidelity_experiment.py`  
Environment: GDAL 3.12.4, GeoPandas 1.1.4, Shapely 2.1.2, pandas 3.0.6, Python 3.11.15

## 1. Interchange-format round trip

One GeoDataFrame in `EPSG:6677` (JGD2011 / Japan Plane Rectangular CS IX), 3 features, written and read back. `PASS` = byte-for-byte equal to source.

| Probe | Shapefile | GeoPackage | GeoJSON | FlatGeobuf | GeoParquet |
|---|---|---|---|---|---|
| feature order | PASS | PASS | PASS | **FAIL** — features reordered (spatial index packing) | PASS |
| field names >10 chars | **FAIL** — 2 renamed, e.g. 'population_density_2025' -> ['populati_1', 'population'] | PASS | PASS | PASS | PASS |
| int64 beyond 2^53 | PASS | PASS | PASS | PASS | PASS |
| float64 precision | **FAIL** — 0.12345678901234566 -> 0.123456789012346 | PASS | PASS | PASS | PASS |
| NULL in numeric | PASS | PASS | PASS | PASS | PASS |
| bool dtype | PASS | PASS | PASS | PASS | PASS |
| datetime (with time) | PASS | PASS | PASS | PASS | PASS |
| unicode (ja) | PASS | PASS | PASS | PASS | PASS |
| string >254 chars | **FAIL** — 300 -> 254 chars (truncated) | PASS | PASS | PASS | PASS |
| NULL in text | PASS | PASS | PASS | PASS | PASS |
| CRS authority code | PASS | PASS | PASS | PASS | PASS |
| geometry coords (precision) | PASS | PASS | PASS | PASS | PASS |
| ring orientation | **FAIL** — exterior CCW -> CW (flipped) | PASS | PASS | PASS | PASS |
| **score** | **9/13** | **13/13** | **13/13** | **12/13** | **13/13** |

## 2. Attribute table -> Excel -> CSV

The hop implemented in `Shp_To_Table_And_Excel.py` (`TableToExcel`, then `pd.read_excel` -> `to_csv`), reproduced with pandas/openpyxl.

| Value | Source | After .xlsx | After .csv |
|---|---|---|---|
| postal (leading zeros) | '0100001' | **np.int64(100001)** | **np.int64(100001)** |
| big_id (2^53+1) | np.int64(9007199254740993) | **np.int64(9007199254740992)** | **np.int64(9007199254740992)** |
| ratio (17 sig digits) | np.float64(0.123456789012345… | **np.float64(0.1234567890123457)** | **np.float64(0.1234567890123457)** |
| ratio (NULL) | np.float64(nan) | np.float64(nan) | np.float64(nan) |
| notes (300 chars) | 'AAAAAAAAAAAAAAAAAAAAAAAAAAA… | 'AAAAAAAAAAAAAAAAAAAAAAAAAAA… | 'AAAAAAAAAAAAAAAAAAAAAAAAAAA… |
| notes (NULL) | nan | nan | nan |
| surveyed (date+time) | Timestamp('2025-03-01 14:30:… | Timestamp('2025-03-01 14:30:… | **'2025-03-01 14:30:00'** |
| name_ja (unicode) | '東京都千代田区' | '東京都千代田区' | '東京都千代田区' |

dtypes after csv hop: `{'rid': 'int64', 'population_density_2025': 'float64', 'population_density_2024': 'float64', 'big_id': 'int64', 'ratio': 'float64', 'is_urban': 'bool', 'surveyed': 'str', 'name_ja': 'str', 'postal': 'int64', 'notes': 'str'}`

## 3. Throughput (20,000 polygons, 4 attribute columns)

| Format | write (s) | read (s) | on disk (MB) |
|---|---|---|---|
| Shapefile | 0.092 | 0.083 | 5.7 |
| GeoPackage | 0.107 | 0.047 | 4.5 |
| GeoJSON | 0.269 | 0.208 | 8.4 |
| FlatGeobuf | 0.091 | 0.037 | 4.4 |
| GeoParquet | 0.105 | 0.071 | 1.3 |

## 4. Driver warnings emitted during the round trip

- **Shapefile**: `Column names longer than 10 characters will be truncated when saved to ESRI Shapefile.`; `Normalized/laundered field name: 'population_density_2025' to 'population'`; `Normalized/laundered field name: 'population_density_2024' to 'populati_1'`
- **GeoPackage**: _none_
- **GeoJSON**: _none_
- **FlatGeobuf**: _none_
- **GeoParquet**: _none_

## 5. Directory traversal in this repository's scripts

`os.walk` descends into subfolders, but both scripts rebuild the path from the top-level folder instead of the current `root`, so anything below the top level resolves to a path that does not exist. Replayed against a tree holding one shapefile at the top level and one in `prefectures/kanto/`:

| Script | shapefiles discovered | paths that resolve |
|---|---|---|
| `Shp_To_SQL.py` | 2 | 1 |
| `Shp_To_Table_And_Excel.py` | 2 | 1 |

The missing file raises no error in either script: `shp2pgsql` writes an empty `.sql` that `psql` applies as a no-op, and the arcpy call is caught by a bare `except` that prints and continues. The run reports success with the data absent.

## 6. Findings

1. **Shapefile is the only lossy interchange format tested, and it fails silently in four ways** (9/13). Field names are cut to 10 characters, so `population_density_2025` and `population_density_2024` both become `populati*` and are no longer distinguishable by name. Numerics are stored as fixed-width ASCII in the DBF, costing precision beyond ~15 significant digits. Text is capped at 254 characters. Polygon rings are rewritten clockwise, inverting the OGC winding order.

2. **Much of the shapefile folklore no longer holds.** With GDAL 3.12.4, int64 past 2^53, NULLs in numeric and text fields, datetimes with a time component, non-ASCII text and the EPSG authority code all survived. The losses above are the real ones.

3. **The Excel/CSV hop loses more than the shapefile hop.** A postal code `'0100001'` returns as the integer `100001`; the leading zero is gone and the value is now numeric. `2**53+1` is rounded by Excel's float64 cells. Timestamps come back from CSV as strings. This hop has no schema, so every re-read re-infers types.

4. **GeoPackage is the drop-in replacement**: 13/13 fidelity, fastest read of the lossless formats, smallest footprint apart from Parquet, one file instead of the shapefile's sidecar set. **GeoParquet** is 13/13 at 1.3 MB against the shapefile's 5.7 MB (4.4x smaller) and is the better choice for analytics. **FlatGeobuf** is fast and lossless in content but reorders features to pack its spatial index, so any downstream join on row position breaks.

5. **Both scripts skip data in subfolders without reporting it** (section 5).

### Recommendation for this pipeline

Keep shapefiles as an accepted *input* — that choice belongs to the data publisher. Stop using them as an intermediate. Write `.gpkg` where a GIS reads the result and `.parquet` where an analyst does, and emit CSV only as a terminal export, never as something re-read. Where the Excel deliverable is required, carry the schema alongside it, since the CSV cannot.
