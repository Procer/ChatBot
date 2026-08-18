import logging
import os
import sys

# Add root directory to sys.path
BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

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
BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
CHROMA_PATH = os.path.join(BASE_DIR, "chroma_db")

# Configuración de Embeddings
AI_PROVIDER = os.getenv("AI_PROVIDER", "google").lower()
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY")

if AI_PROVIDER == "openai" and OPENAI_API_KEY:
    embeddings = OpenAIEmbeddings(api_key=OPENAI_API_KEY)
else:
    embeddings = GoogleGenerativeAIEmbeddings(model="models/gemini-embedding-001", google_api_key=GOOGLE_API_KEY)


def _embeddings_for(client_id: int):
    """Embeddings a usar para este cliente: los propios si configuró una OpenAI API key
    (aislamiento de billing por tenant), o los globales del .env si no."""
    if AI_PROVIDER != "openai":
        return embeddings
    from src.database.openai_key import get_client_embeddings
    return get_client_embeddings(client_id, embeddings)


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
        logging.error(f"Error al leer PDF {file_path}: {e}")
    return text

def ingest_data_saas(client_id: int):
    """
    Lee datos de la base de datos SQL Server (tabla data_knowledge) para el client_id dado,
    extrae el contenido de los archivos asociados si existen, y sincroniza la BD vectorial Chroma.
    """
    logging.info(f"--- INICIANDO SINCRONIZACIÓN DE CONOCIMIENTO PARA CLIENTE {client_id} ---")
    documents = []

    from src.database.session import SessionLocal
    from src.database.models import Knowledge

    db = SessionLocal()
    try:
        # Obtener los elementos de conocimiento para el cliente específico
        knowledge_items = db.query(Knowledge).filter_by(client_id=client_id).all()
        logging.info(f"Encontrados {len(knowledge_items)} registros de conocimiento en SQL Server para el cliente {client_id}.")

        for k in knowledge_items:
            if k.analyze_rag is False:
                logging.info(f"Saltando indexación RAG para topic '{k.topic}' (analyze_rag=False).")
                continue
            has_form_str = "SÍ" if k.has_form else "NO"
            text_parts = [
                f"TEMA: {k.topic}",
                f"CATEGORIA: {k.category if k.category else 'General'}",
                f"FORMULARIO_ACTIVO: {has_form_str}",
                f"CAMPOS_REQUERIDOS: {k.form_fields if k.form_fields else 'Ninguno'}",
                f"CONTENIDO: {k.content if k.content else ''}"
            ]
            
            source_info = "database"
            
            # Si tiene archivos adjuntos en media_path, extraer texto e incorporarlo
            if k.media_path:
                paths = [p.strip() for p in k.media_path.split(",") if p.strip()]
                for path in paths:
                    # Resolver ruta del archivo local
                    # Los paths se guardan como /uploads/client_1/archivo.pdf
                    local_filename = path.lstrip("/")
                    local_path = os.path.join(BASE_DIR, local_filename)
                    
                    if os.path.exists(local_path):
                        logging.info(f"Procesando archivo adjunto para topic '{k.topic}': {local_path}")
                        file_content = ""
                        if local_path.lower().endswith(".pdf"):
                            file_content = load_pdf_content(local_path)
                        elif local_path.lower().endswith(".txt"):
                            try:
                                with open(local_path, "r", encoding="utf-8") as f:
                                    file_content = f.read()
                            except Exception as e:
                                logging.error(f"Error al leer TXT {local_path}: {e}")
                        
                        if file_content.strip():
                            text_parts.append(f"\nCONTENIDO DEL ARCHIVO ADJUNTO ({os.path.basename(local_path)}):\n{file_content}")
                            source_info = f"file:{os.path.basename(local_path)}"
                    else:
                        logging.warning(f"El archivo no se encuentra físicamente: {local_path}")

            combined_text = "\n".join(text_parts)
            documents.append(Document(
                page_content=combined_text,
                metadata={
                    "client_id": client_id,
                    "topic": k.topic,
                    "category": k.category,
                    "has_form": k.has_form,
                    "form_fields": k.form_fields,
                    "storage_dest": k.storage_dest,
                    "source": source_info,
                    "required_role": k.required_role or "General",
                    "tags_to_apply": k.tags_to_apply or ""
                }
            ))

    except Exception as e:
        logging.error(f"Error consultando SQL Server para client_id {client_id}: {e}")
    finally:
        db.close()

    if not documents:
        logging.info(f"No hay conocimiento o documentos para el cliente {client_id}.")
        # Si no hay documentos, igual limpiamos lo anterior por seguridad
        try:
            if os.path.exists(CHROMA_PATH):
                vector_db = Chroma(persist_directory=CHROMA_PATH, embedding_function=_embeddings_for(client_id))
                vector_db._collection.delete(where={"client_id": client_id})
                logging.info(f"ChromaDB limpio para el cliente {client_id} (sin registros nuevos).")
        except Exception as e:
            logging.error(f"Error al vaciar ChromaDB: {e}")
        return

    # Dividir en fragmentos (Chunking)
    text_splitter = RecursiveCharacterTextSplitter(chunk_size=1000, chunk_overlap=200)
    chunks = text_splitter.split_documents(documents)
    logging.info(f"Procesando {len(chunks)} fragmentos totales para el cliente {client_id}.")

    # Guardar en ChromaDB
    try:
        vector_db = Chroma(persist_directory=CHROMA_PATH, embedding_function=_embeddings_for(client_id))

        # Eliminar registros previos de este cliente para evitar duplicados
        logging.info(f"Eliminando registros antiguos de ChromaDB para el cliente {client_id}...")
        try:
            vector_db._collection.delete(where={"client_id": client_id})
        except Exception as e:
            logging.error(f"Error eliminando fragmentos previos: {e}")

        # Insertar los nuevos fragmentos
        logging.info(f"Guardando {len(chunks)} fragmentos en ChromaDB...")
        vector_db = Chroma.from_documents(
            documents=chunks,
            embedding=embeddings,
            persist_directory=CHROMA_PATH
        )
        logging.info(f"--- CONOCIMIENTO SINCRONIZADO EXITOSAMENTE PARA CLIENTE {client_id} ---")
    except Exception as e:
        logging.error(f"Error al guardar en ChromaDB para el cliente {client_id}: {e}")

if __name__ == "__main__":
    # Test rápido de ingesta
    import sys
    if len(sys.argv) > 1:
        try:
            cid = int(sys.argv[1])
            ingest_data_saas(cid)
        except ValueError:
            print("Por favor especifique un client_id entero.")
    else:
        print("Uso: python ingest_saas.py <client_id>")
