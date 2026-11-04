Exporting Legacy Database

1. Prerequisities for running the scripts

- a .kube/config file from rancher.eea.europa.eu (production environment, running QCTool release 2.5.1)

- a .kube/config_staging file from https://rancher2pre.eea.europa.eu/ (staging environment, running QCTool release 3.0.0) 


2. Export the tables from legacy database to CSV files.

-  KUBECONFIG=/c/Users/jkadlec/.kube/config python export_legacy_tables.py

This will create four exported .csv files (auth_user.csv, dashboard_delivery.csv, dashboard_job.csv, dashboard_s3info.csv)


3. Import the users from the CSV file to the new 3.0.0 database schema.

- KUBECONFIG=/c/Users/jkadlec/.kube/config_staging python import_legacy_tables_kubernetes.py users --dry-run

- KUBECONFIG=/c/Users/jkadlec/.kube/config_staging python import_legacy_tables_kubernetes.py users

4. Import the other data from the CSV files to the new 3.0.0 database schema, data from past 1 month:

- KUBECONFIG=/c/Users/jkadlec/.kube/config_staging python import_legacy_tables_kubernetes.py --months 1 --auto-approve

months 1 (can be changed to more months)
auto-approve (submitted deliveries are set to "approved" where possible)