"""Load the JanSetu tables (grievances, wards, mplads_funds) from SQLite into
BigQuery, enabling constituency-scale analytics.

Usage:
  pip install google-cloud-bigquery pandas pyarrow
  gcloud auth application-default login
  python scripts/load_bigquery.py --project YOUR_PROJECT --dataset jansetu

Then run the app with:
  export USE_BIGQUERY=1 BQ_PROJECT=YOUR_PROJECT BQ_DATASET=jansetu
"""
import argparse
import os
import sqlite3

import pandas as pd
from google.cloud import bigquery

DB = os.path.join(os.path.dirname(__file__), "..", "jansetu.db")
TABLES = ["grievances", "wards", "mplads_funds"]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--project", required=True)
    ap.add_argument("--dataset", default="jansetu")
    args = ap.parse_args()

    client = bigquery.Client(project=args.project)
    ds_ref = bigquery.Dataset(f"{args.project}.{args.dataset}")
    ds_ref.location = "asia-south1"
    client.create_dataset(ds_ref, exists_ok=True)
    print(f"Dataset {args.project}.{args.dataset} ready (asia-south1)")

    conn = sqlite3.connect(DB)
    for t in TABLES:
        df = pd.read_sql_query(f"SELECT * FROM {t}", conn)
        job = client.load_table_from_dataframe(
            df, f"{args.project}.{args.dataset}.{t}",
            job_config=bigquery.LoadJobConfig(write_disposition="WRITE_TRUNCATE"))
        job.result()
        print(f"Loaded {len(df)} rows into {args.dataset}.{t}")
    conn.close()
    print("Done. Set USE_BIGQUERY=1 BQ_PROJECT=... BQ_DATASET=... to activate.")


if __name__ == "__main__":
    main()
