import os
import subprocess

# Set your database credentials
DB_NAME = "test"
DB_USER = "postgres"
DB_PASSWORD = "1111"
DB_SCHEMA = "public"
SRID = "4326"  # Change SRID if needed

# Path to the directory containing shapefiles
shapefile_dir = r"D:\LPA_Data"

# Set environment variable for password
os.environ['PGPASSWORD'] = DB_PASSWORD

# Loop through all shapefiles in the directory
for root, dirs, files in os.walk(shapefile_dir):
    for file in files:
        if  file.endswith(".shp"):
            basename = os.path.splitext(file)[0]
            table_name = f"{DB_SCHEMA}.{basename}"
            
            # Full paths
            shapefile_path = os.path.join(shapefile_dir, file)
            sql_file = f"{basename}.sql"

            # Generate SQL file using shp2pgsql
            print(f"Processing {shapefile_path}...")
            subprocess.run(
                [r"C:\Program Files\PostgreSQL\17\bin\shp2pgsql.exe", "-s", SRID, shapefile_path, table_name],
                stdout=open(sql_file, "w")
            )

            # Import the SQL file into PostgreSQL
            subprocess.run(
                [r"C:\Program Files\PostgreSQL\17\bin\psql.exe", "-U", DB_USER, "-d", DB_NAME, "-f", sql_file]
            )

            # Clean up the generated SQL file
            os.remove(sql_file)

    print("All shapefiles have been imported.")
