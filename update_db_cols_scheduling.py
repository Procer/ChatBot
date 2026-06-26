import os
from sqlalchemy import create_engine, text
from dotenv import load_dotenv

load_dotenv()
DB_URL = os.getenv("DATABASE_URL")
if not DB_URL:
    DB_URL = "mssql+pyodbc://sa:ZarateAutos2026!@127.0.0.1,1433/zsg_master?driver=ODBC+Driver+17+for+SQL+Server&TrustServerCertificate=yes"

engine = create_engine(DB_URL)
with engine.begin() as conn:
    queries = [
        "ALTER TABLE adm_client_settings ADD scheduling_provider VARCHAR(50) DEFAULT 'local';",
        "ALTER TABLE adm_client_settings ADD scheduling_days VARCHAR(255) DEFAULT 'mon,tue,wed,thu,fri';",
        "ALTER TABLE adm_client_settings ADD scheduling_capacity INT DEFAULT 1;",
        "ALTER TABLE adm_client_settings ADD appointment_duration INT DEFAULT 30;",
        "ALTER TABLE adm_client_settings ADD google_calendar_id VARCHAR(255) DEFAULT 'primary';"
    ]
    for q in queries:
        try:
            conn.execute(text(q))
            print("Success:", q)
        except Exception as e:
            print("Failed:", q, e)
