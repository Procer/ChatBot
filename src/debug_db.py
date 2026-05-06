import sqlite3
import json

def check_db():
    conn = sqlite3.connect('settings.sqlite')
    cursor = conn.cursor()
    
    tables = ['knowledge', 'form_submissions', 'proceedings', 'config']
    
    for table in tables:
        print(f"\n--- Contenido de la tabla: {table} ---")
        try:
            cursor.execute(f"PRAGMA table_info({table})")
            columns = cursor.fetchall()
            col_names = [col[1] for col in columns]
            print(f"Columnas: {col_names}")
            
            cursor.execute(f"SELECT * FROM {table}")
            rows = cursor.fetchall()
            for row in rows:
                print(row)
        except Exception as e:
            print(f"Error al leer {table}: {e}")
            
    conn.close()

if __name__ == "__main__":
    check_db()
