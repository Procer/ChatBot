import os
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from dotenv import load_dotenv

# Cargar las variables de entorno
load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL")

# Validar que exista la URL (útil para que no crashee si alguien clona el repo sin .env)
if not DATABASE_URL:
    raise ValueError("⚠️ DATABASE_URL no está definida en el archivo .env")

# Crear el Motor de SQLAlchemy apuntando a SQL Server
# pool_pre_ping revisa que la conexión esté viva antes de usarla
engine = create_engine(DATABASE_URL, pool_pre_ping=True)

# Crear la fábrica de Sesiones
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

# Dependencia para FastAPI (Generador)
def get_db():
    """
    Crea una sesión de BD para la petición actual,
    y la cierra automáticamente al terminar.
    """
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
