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

