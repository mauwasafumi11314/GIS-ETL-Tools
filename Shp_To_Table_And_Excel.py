
### Load all spatial data (shp, tif, geojson) from a folder onto a new geodatabase

import arcpy
import pandas as pd
import os
arcpy.env.overwriteOutput = True


folder_path = "D:\LPA\Data"

arcpy.env.workspace = r"D:\Porflolio\automation"

# Set local variables
out_folder_path = r"D:\Porflolio\automation"
out_name = "featuregdb.gdb"

# Execute CreateFileGDB
arcpy.CreateFileGDB_management(out_folder_path, out_name)


shapeFileList = []
for root, dirs, files in os.walk(folder_path):
    for file in files:                       
        if file.endswith((".shp", ".tif", ".geojson")):
            shapeFileList.append(file)

for file in shapeFileList:
    newName = os.path.splitext(os.path.basename(file))[0]
    newName = "".join(c for c in newName if c.isalnum() or c == "_")
    if not newName[0].isalpha():
        newName = f"f_{newName}"
    print(newName)
    arcpy.conversion.FeatureClassToFeatureClass(r"{0}\{1}".format(folder_path, file), r"{0}\{1}".format(out_folder_path, out_name),f"{newName}")
#D:\LPA_Data\ne_10m_admin_0_countries.shp


### Extract attribute tables from shapefiles and save the tables in another geodatabase

import arcpy
import os

arcpy.env.workspace = r"D:\Porflolio\automation"

# Set local variables
out_folder_path = r"D:\Porflolio\automation"
out_name2 = "tablegdb.gdb"

arcpy.CreateFileGDB_management(out_folder_path, out_name2)


input_folder = r"{0}\{1}".format(out_folder_path, out_name2)
target_gdb = r"D:\LPA\Data"

arcpy.env.workspace = target_gdb


shapefiles = arcpy.ListFeatureClasses()
for shapefile in shapefiles:
    try:
        # Create a new table name (based on the shapefile name)
        table_name = os.path.splitext(shapefile)[0]

        # Extract attribute tables into a new folder 
        arcpy.conversion.TableToTable(shapefile, input_folder, table_name)

        print(f"Extracted {table_name} from {shapefile} in {target_gdb}")
    except Exception as e:
        print(f"Failed to convert {shapefile}: {e}")

        
        
        
### Exported attribute tables as excel and csv files in each of their own sub fold


folder_path = r"D:\portflolio\Excel_Folder"
os.makedirs(folder_path, exist_ok=True)
# Set environment settings
arcpy.env.workspace = r"{0}\{1}".format(out_folder_path, out_name2)

tablefiles = arcpy.ListTables()
if tablefiles:
    for tablefile in tablefiles:
        table_name = os.path.splitext(tablefile)[0]
        # Create a subfolder for this table
        output_subfolder = os.path.join(folder_path, table_name)
        if not os.path.exists(output_subfolder):
            os.makedirs(output_subfolder)
        # Define the output Excel file path
        output_excel = os.path.join(output_subfolder, f"{table_name}.xlsx")
        
        # Convert the table to Excel
        try:
            arcpy.conversion.TableToExcel(tablefile, output_excel)
            print(f"Exported {tablefile} to {output_excel}")
            
            
            # Define the output Excel file path
            output_csv = os.path.join(output_subfolder, f"{table_name}.csv")
            
            # Convert the excel to csv
            
            df = pd.read_excel(output_excel)
            df.to_csv(output_csv, index=False)
            
        except Exception as e:
            print(f"Failed to export {tablefile}: {e}")


