import os
from sqlalchemy import create_engine, text
from dotenv import load_dotenv

load_dotenv()
DB_URL = os.getenv("DATABASE_URL")
if not DB_URL:
    DB_URL = "mssql+pyodbc://sa:ZsgAdmin2026!!@127.0.0.1,1434/zsg_master?driver=ODBC+Driver+17+for+SQL+Server&TrustServerCertificate=yes"

engine = create_engine(DB_URL)
with engine.begin() as conn:
    queries = [
        "ALTER TABLE adm_client_settings ADD test_mode_enabled BIT DEFAULT 0;",
        "ALTER TABLE adm_client_settings ADD test_numbers VARCHAR(255);"
    ]
    for q in queries:
        try:
            conn.execute(text(q))
            print("Success:", q)
        except Exception as e:
            print("Failed:", q, e)
