import logging
import os
import sqlite3
import shutil
import time
from dotenv import load_dotenv
from langchain_core.documents import Document
from langchain_text_splitters import RecursiveCharacterTextSplitter
from langchain_google_genai import GoogleGenerativeAIEmbeddings
from langchain_openai import OpenAIEmbeddings
from langchain_community.vectorstores import Chroma
import PyPDF2

# Cargar variables de entorno
load_dotenv()

# Configuración de rutas
CHROMA_PATH = "chroma_db"
SETTINGS_DB = "settings.sqlite"
DATA_DIR = "data"

# Configuración de Embeddings
AI_PROVIDER = os.getenv("AI_PROVIDER", "google").lower()
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY")

if AI_PROVIDER == "openai" and OPENAI_API_KEY:
    embeddings = OpenAIEmbeddings(api_key=OPENAI_API_KEY)
else:
    embeddings = GoogleGenerativeAIEmbeddings(model="models/gemini-embedding-001", google_api_key=GOOGLE_API_KEY)

def load_pdf_content(file_path):
    """Extrae texto de un archivo PDF usando PyPDF2."""
    text = ""
    try:
        with open(file_path, "rb") as f:
            reader = PyPDF2.PdfReader(f)
            for page in reader.pages:
                page_text = page.extract_text()
                if page_text:
                    text += page_text + "\n"
    except Exception as e:
        logging.info(f"Error al leer PDF {file_path}: {e}")
    return text

def ingest_data():
    """
    Lee datos de SQLite y archivos en 'data/', sincronizándolos con la BD vectorial.
    """
    logging.info("--- INICIANDO SINCRONIZACIÓN DE CONOCIMIENTO ---")
    documents = []

    # 1. Obtener datos de SQLite (TABLA knowledge)
    try:
        if os.path.exists(SETTINGS_DB):
            conn = sqlite3.connect(SETTINGS_DB)
            cursor = conn.cursor()
            cursor.execute("SELECT topic, content, category, has_form, form_fields, storage_dest FROM knowledge")
            rows = cursor.fetchall()
            for row in rows:
                has_form = "SÍ" if row[3] else "NO"
                text = f"TEMA: {row[0]}\nCONTENIDO: {row[1]}\nCATEGORIA: {row[2]}\nFORMULARIO_ACTIVO: {has_form}\nCAMPOS_REQUERIDOS: {row[4] if row[4] else 'Ninguno'}"
                documents.append(Document(
                    page_content=text, 
                    metadata={
                        "source": "database", 
                        "topic": row[0], 
                        "category": row[2],
                        "has_form": row[3],
                        "form_fields": row[4],
                        "storage_dest": row[5]
                    }
                ))
            conn.close()
            logging.info(f"Cargados {len(rows)} registros desde la base de datos con soporte de formularios.")
    except Exception as e:
        logging.info(f"Error al leer SQLite: {e}")

    # 2. Obtener datos de Archivos (CARPETA data/)
    if os.path.exists(DATA_DIR):
        files_count = 0
        for filename in os.listdir(DATA_DIR):
            file_path = os.path.join(DATA_DIR, filename)
            content = ""
            
            if filename.endswith(".txt"):
                try:
                    with open(file_path, "r", encoding="utf-8") as f:
                        content = f.read()
                except Exception as e:
                    logging.info(f"Error al leer TXT {filename}: {e}")
            
            elif filename.endswith(".pdf"):
                content = load_pdf_content(file_path)
            
            if content.strip():
                documents.append(Document(
                    page_content=content,
                    metadata={"source": filename}
                ))
                files_count += 1
        logging.info(f"Cargados {files_count} archivos desde la carpeta '{DATA_DIR}'.")

    if not documents:
        logging.info("No hay datos para sincronizar.")
        return

    # 3. Dividir en fragmentos (Chunking)
    text_splitter = RecursiveCharacterTextSplitter(chunk_size=1000, chunk_overlap=200)
    chunks = text_splitter.split_documents(documents)
    logging.info(f"Procesando {len(chunks)} fragmentos totales.")

    # 4. Guardar en ChromaDB
    try:
        # Limpieza total para evitar duplicados y datos antiguos
        if os.path.exists(CHROMA_PATH):
            logging.info("Limpiando colección antigua de Chroma mediante el cliente...")
            try:
                vector_db = Chroma(persist_directory=CHROMA_PATH, embedding_function=embeddings)
                all_ids = vector_db._collection.get()['ids']
                if all_ids:
                    vector_db._collection.delete(ids=all_ids)
                    logging.info(f"Se eliminaron {len(all_ids)} registros de la colección existente.")
            except Exception as e:
                logging.error(f"Error al vaciar ChromaDB: {e}")
        
        logging.info("Creando/Actualizando base de datos vectorial con datos nuevos...")
        vector_db = Chroma.from_documents(
            documents=chunks,
            embedding=embeddings,
            persist_directory=CHROMA_PATH
        )
        logging.info("--- CONOCIMIENTO SINCRONIZADO EXITOSAMENTE ---")
    except Exception as e:
        logging.info(f"Error al guardar en ChromaDB: {e}")

if __name__ == "__main__":
    ingest_data()
