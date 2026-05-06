import sqlite3
conn = sqlite3.connect('settings.sqlite')
cursor = conn.cursor()
cursor.execute("""
    UPDATE knowledge 
    SET has_form = 1, 
        form_fields = 'Título del automotor, Informe de dominio, Estado civil' 
    WHERE topic = 'FORMULARIO 08'
""")
conn.commit()
print("Formulario 08 actualizado con campos interactivos.")
conn.close()
