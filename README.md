# GIS ETL automation tool 

## **Overview**

This portfolio demonstrates my ability to automate GIS workflows using Python. It includes tools for:
1. Extracting and loading spatial data (shapefiles, GeoJSON, and raster files) into an ArcGIS and save their attribute tables as excel/csv files in each sub-holder.
2. Automating the loading of shapefiles into a PostgreSQL/PostGIS database.

## **Features**

### **[1. Import Spatial Data into a Geodatabase and Export Attribute Tables as Excel/CSV Files](Shp_To_Table_And_Excel.py)**
- Load all spatial data (shp, tif, geojson) from a folder onto a new geodatabase.
- Extract attribute tables from shapefiles and save the tables in another geodatabase
- Export attribute tables as excel and csv files in each of their own sub fold

### **[2. Load Spatial Data into PostgreSQL with PostGIS extention](Shp_To_SQL.py)**
- Extract and load all spatial data from a folder into a PostgreSQL/PostGIS database.

## **Experiments**

### **[Fidelity loss in a shapefile-centred ETL pipeline](experiments/fidelity_experiment.py)**

A controlled measurement of how much of a spatial payload survives each hop of the
pipeline above. One ground-truth `GeoDataFrame` probes thirteen documented failure
modes (field-name length, integer and float precision, NULLs, datetimes, unicode,
string length, CRS authority, coordinate precision, ring orientation, feature
order); it is round-tripped through Shapefile, GeoPackage, GeoJSON, FlatGeobuf and
GeoParquet, then through the `Excel -> CSV` chain, and diffed cell by cell.

Headline result: **Shapefile scores 9/13 and GeoPackage, GeoJSON and GeoParquet
score 13/13**, and the `Excel -> CSV` hop loses more than the shapefile hop does —
a postal code `'0100001'` comes back as the integer `100001`. Full matrix,
throughput benchmark and findings in **[experiments/RESULTS.md](experiments/RESULTS.md)**.

```bash
pip install -r experiments/requirements.txt
python3 experiments/fidelity_experiment.py
```
