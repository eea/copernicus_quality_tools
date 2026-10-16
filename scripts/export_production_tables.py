import os
import subprocess
import csv
from io import StringIO


# Instructions: This script exports specified PostgreSQL tables from QC Tool production pod to CSV files.
# Prerequisities:
# - kubectl installed and configured to access the Kubernetes cluster
# - Access to the QC Tool production pod


# ================= CONFIGURATION =================
NAMESPACE = "qc-tool"
POD_NAME = "database-postgres-ss-0"
DB_USER = "qc_user"       # Replace with your DB user if different
DB_NAME = "qc_tool"         # Replace with your DB name if different

TABLES = [
    "dashboard_job",
    "dashboard_delivery",
    "auth_user"
]
# =================================================

def export_table_to_csv(table_name):
    print(f"Exporting table: {table_name}...")
    
    copy_sql = f"COPY (SELECT * FROM {table_name}) TO STDOUT WITH CSV HEADER;"
    
    cmd = [
        "kubectl", "exec", "-i",
        "-n", NAMESPACE,
        POD_NAME,
        "--",
        "psql",
        "-U", DB_USER,
        "-d", DB_NAME,
        "-c", copy_sql
    ]
    
    try:
        # Force UTF-8 decoding and handle non-printable characters gracefully
        result = subprocess.run(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=True
        )
        
        output_filename = f"{table_name}.csv"
        with open(output_filename, "w", encoding="utf-8") as f:
            f.write(result.stdout)
            
        print(f" Successfully exported {table_name} -> {output_filename}")

    except subprocess.CalledProcessError as e:
        print(f" Error exporting {table_name}:")
        print(e.stderr)

def main():
    # Verify kubectl is installed and accessible
    try:
        subprocess.run(["kubectl", "version", "--client"], stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True)
    except (subprocess.CalledProcessError, FileNotFoundError):
        print("Error: 'kubectl' command not found. Ensure kubectl is installed and in your PATH.")
        return

    print("Starting CSV export process...")
    for table in TABLES:
        export_table_to_csv(table)
    print("Done!")

if __name__ == "__main__":
    main()