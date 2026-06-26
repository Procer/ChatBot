import os
from sqlalchemy import create_engine, text

db_url = "mssql+pyodbc://sa:ZarateAutos2026!@127.0.0.1,1433/zsg_master?driver=ODBC+Driver+17+for+SQL+Server&TrustServerCertificate=yes"
engine = create_engine(db_url)

with engine.begin() as conn:
    conn.execute(text("ALTER TABLE bot_tags ALTER COLUMN name NVARCHAR(100) NOT NULL;"))
    conn.execute(text("UPDATE bot_tags SET name = '👋 Nuevo Contacto' WHERE name LIKE '%Nuevo Contacto%';"))
    conn.execute(text("UPDATE bot_tags SET name = '📱 Canal: WhatsApp' WHERE name LIKE '%Canal: WhatsApp%';"))
    conn.execute(text("UPDATE bot_tags SET name = '💬 Canal: Telegram' WHERE name LIKE '%Canal: Telegram%';"))
    conn.execute(text("UPDATE bot_tags SET name = '⚡ Activo Reciente' WHERE name LIKE '%Activo Reciente%';"))
    conn.execute(text("UPDATE bot_tags SET name = '🗓️ Turno Agendado' WHERE name LIKE '%Turno Agendado%';"))
    conn.execute(text("UPDATE bot_tags SET name = '❌ Turno Cancelado' WHERE name LIKE '%Turno Cancelado%';"))
    conn.execute(text("UPDATE bot_tags SET name = '📝 Trámite Iniciado' WHERE name LIKE '%Trámite Iniciado%';"))
    conn.execute(text("UPDATE bot_tags SET name = '🎓 Trámite Completado' WHERE name LIKE '%Trámite Completado%';"))
    conn.execute(text("UPDATE bot_tags SET name = '⚠️ Sin Responder' WHERE name LIKE '%Sin Responder%';"))
    conn.execute(text("UPDATE bot_tags SET name = '👤 Humano Requerido' WHERE name LIKE '%Humano Requerido%';"))
print("Tags actualizados exitosamente en SQL Server.")
