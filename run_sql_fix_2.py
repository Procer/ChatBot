import os
from sqlalchemy import create_engine, text

db_url = "mssql+pyodbc://sa:ZarateAutos2026!@127.0.0.1,1433/zsg_master?driver=ODBC+Driver+17+for+SQL+Server&TrustServerCertificate=yes"
engine = create_engine(db_url)

with engine.begin() as conn:
    # Need to use parameters to pass unicode strings safely to pyodbc/SQL Server
    queries = [
        ("👋 Nuevo Contacto", "%Nuevo Contacto%"),
        ("📱 Canal: WhatsApp", "%Canal: WhatsApp%"),
        ("💬 Canal: Telegram", "%Canal: Telegram%"),
        ("⚡ Activo Reciente", "%Activo Reciente%"),
        ("🗓️ Turno Agendado", "%Turno Agendado%"),
        ("❌ Turno Cancelado", "%Turno Cancelado%"),
        ("📝 Trámite Iniciado", "%Trámite Iniciado%"),
        ("🎓 Trámite Completado", "%Trámite Completado%"),
        ("⚠️ Sin Responder", "%Sin Responder%"),
        ("👤 Humano Requerido", "%Humano Requerido%"),
    ]
    for emoji_name, search_pattern in queries:
        conn.execute(text("UPDATE bot_tags SET name = :name WHERE name LIKE :search"), {"name": emoji_name, "search": search_pattern})
        # Also let's handle the exact ?? match just in case
        conn.execute(text("UPDATE bot_tags SET name = :name WHERE name LIKE :search2"), {"name": emoji_name, "search2": search_pattern.replace('%', '%??%')})

print("Tags actualizados exitosamente en SQL Server.")
