import json
import logging
import os
import sys
from datetime import datetime, timedelta

import bcrypt
from sqlalchemy import func

# Add root directory to sys.path (mismo patrón que ingest_saas.py)
BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

from dotenv import load_dotenv
from langchain_google_genai import GoogleGenerativeAIEmbeddings
from langchain_openai import OpenAIEmbeddings
from langchain_community.vectorstores import Chroma

load_dotenv()

CHROMA_PATH = os.path.join(BASE_DIR, "chroma_db")

AI_PROVIDER = os.getenv("AI_PROVIDER", "google").lower()
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY")

if AI_PROVIDER == "openai" and OPENAI_API_KEY:
    embeddings = OpenAIEmbeddings(api_key=OPENAI_API_KEY)
else:
    embeddings = GoogleGenerativeAIEmbeddings(model="models/gemini-embedding-001", google_api_key=GOOGLE_API_KEY)

from src.database.session import SessionLocal
from src.database.models import (
    DocSegment, DocLibraryUser, DocLibraryUserSegment, Document,
    DocumentSegmentLink, DocSession, DocSearchLog
)


# --- HASHING DE CONTRASEÑAS ---
# Deliberadamente NO se reutiliza el hashlib.md5 del login de administradores
# (main_saas.py): acá se maneja información de acceso operativo de terceros
# (choferes, fleteros, etc.) y bcrypt ya es una dependencia del proyecto.

def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(password: str, password_hash: str) -> bool:
    if not password or not password_hash:
        return False
    try:
        return bcrypt.checkpw(password.encode("utf-8"), password_hash.encode("utf-8"))
    except (ValueError, TypeError):
        return False


# --- SEGMENTOS Y SESIONES ---

def get_segment_by_name(db, client_id: int, name: str):
    if not name:
        return None
    return db.query(DocSegment).filter(
        DocSegment.client_id == client_id,
        DocSegment.is_active == True,
        func.lower(DocSegment.name) == name.strip().lower()
    ).first()


def thread_has_segment_access(db, client_id: int, thread_id: str, segment_id: int) -> bool:
    session = db.query(DocSession).filter_by(
        client_id=client_id, thread_id=thread_id, segment_id=segment_id
    ).order_by(DocSession.id.desc()).first()
    if not session:
        return False
    if session.expires_at and session.expires_at < datetime.utcnow():
        return False
    return True


def _create_or_extend_session(db, client_id: int, thread_id: str, segment: DocSegment, library_user_id: int = None):
    expires_at = None
    if segment.session_expiry_days:
        expires_at = datetime.utcnow() + timedelta(days=segment.session_expiry_days)

    existing = db.query(DocSession).filter_by(
        client_id=client_id, thread_id=thread_id, segment_id=segment.id
    ).first()
    if existing:
        existing.library_user_id = library_user_id
        existing.authenticated_at = datetime.utcnow()
        existing.expires_at = expires_at
    else:
        db.add(DocSession(
            client_id=client_id, thread_id=thread_id, segment_id=segment.id,
            library_user_id=library_user_id, authenticated_at=datetime.utcnow(), expires_at=expires_at
        ))
    db.commit()


def validate_segment_credentials(client_id: int, thread_id: str, segment_name: str, clave: str, usuario: str = None):
    """Valida usuario/clave contra un segmento protegido y, si es válido, crea/extiende
    la sesión autenticada del thread para ese segmento."""
    db = SessionLocal()
    try:
        segment = get_segment_by_name(db, client_id, segment_name)
        if not segment or segment.is_public:
            return {"status": "error", "message": f"No encontré el segmento protegido '{segment_name}'."}

        if segment.auth_mode == "individual":
            if not usuario or not usuario.strip():
                return {"status": "error", "message": "Falta el usuario. Pedile al usuario que indique su nombre de usuario y su contraseña."}
            user = db.query(DocLibraryUser).filter(
                DocLibraryUser.client_id == client_id,
                DocLibraryUser.is_active == True,
                func.lower(DocLibraryUser.username) == usuario.strip().lower()
            ).first()
            if not user or not verify_password(clave, user.password_hash):
                return {"status": "error", "message": "Usuario o contraseña incorrectos. Pedile al usuario que los vuelva a escribir."}
            has_access = db.query(DocLibraryUserSegment).filter_by(
                library_user_id=user.id, segment_id=segment.id
            ).first()
            if not has_access:
                return {"status": "error", "message": "Usuario o contraseña incorrectos. Pedile al usuario que los vuelva a escribir."}
            _create_or_extend_session(db, client_id, thread_id, segment, library_user_id=user.id)
        else:
            if not verify_password(clave, segment.generic_password_hash):
                return {"status": "error", "message": "Contraseña incorrecta. Pedile al usuario que la vuelva a escribir."}
            _create_or_extend_session(db, client_id, thread_id, segment, library_user_id=None)

        return {"status": "success"}
    except Exception as e:
        logging.error(f"[DocLibrary] Error validando credenciales de segmento: {e}")
        return {"status": "error", "message": "Ocurrió un error validando el acceso."}
    finally:
        db.close()


# --- BÚSQUEDA (Chroma: título + palabras clave, NUNCA contenido del archivo) ---

def sync_document_to_chroma(document_id: int):
    db = SessionLocal()
    try:
        doc = db.query(Document).filter_by(id=document_id).first()
        if not doc:
            return
        remove_document_from_chroma(document_id, doc.client_id)
        if not doc.is_active:
            return

        segment_ids = [l.segment_id for l in db.query(DocumentSegmentLink).filter_by(document_id=doc.id).all()]
        page_content = f"TITULO: {doc.title}\nPALABRAS_CLAVE: {doc.keywords or ''}"
        metadata = {
            "doc_type": "library_document",
            "client_id": doc.client_id,
            "document_id": doc.id,
            "segment_ids": ",".join(str(s) for s in segment_ids),
        }
        vector_db = Chroma(persist_directory=CHROMA_PATH, embedding_function=embeddings)
        vector_db.add_texts(texts=[page_content], metadatas=[metadata], ids=[f"library_document_{doc.id}"])
    except Exception as e:
        logging.error(f"[DocLibrary] Error sincronizando documento {document_id} en Chroma: {e}")
    finally:
        db.close()


def remove_document_from_chroma(document_id: int, client_id: int):
    try:
        if not os.path.exists(CHROMA_PATH):
            return
        vector_db = Chroma(persist_directory=CHROMA_PATH, embedding_function=embeddings)
        vector_db._collection.delete(where={"$and": [{"client_id": client_id}, {"document_id": document_id}]})
    except Exception as e:
        logging.error(f"[DocLibrary] Error eliminando documento {document_id} de Chroma: {e}")


# Distancia máxima (Chroma: menor = más similar) para considerar un resultado
# realmente relacionado con la consulta. Sin este corte, similarity_search siempre
# devuelve los k más cercanos aunque ninguno sea relevante (p. ej. con pocos
# documentos cargados), lo que puede hacer que un documento público pero ajeno a
# la consulta "tape" a uno protegido que sí es la respuesta correcta.
DOC_SEARCH_SCORE_THRESHOLD = 0.4


def search_documents_candidates(client_id: int, thread_id: str, query: str, k: int = 5):
    """Busca documentos por título/palabras clave (RAG) y marca cada resultado como
    accesible o no para el thread actual, según sus segmentos."""
    db = SessionLocal()
    try:
        try:
            vector_db = Chroma(persist_directory=CHROMA_PATH, embedding_function=embeddings)
            results_with_scores = vector_db.similarity_search_with_score(
                query, k=k,
                filter={"$and": [{"client_id": client_id}, {"doc_type": "library_document"}]}
            )
            results = [doc for doc, score in results_with_scores if score <= DOC_SEARCH_SCORE_THRESHOLD]
        except Exception as e:
            logging.error(f"[DocLibrary] Error buscando en Chroma: {e}")
            results = []

        doc_ids = []
        seen = set()
        for r in results:
            did = r.metadata.get("document_id")
            if did is not None and did not in seen:
                seen.add(did)
                doc_ids.append(did)

        if not doc_ids:
            return []

        docs = db.query(Document).filter(
            Document.client_id == client_id,
            Document.id.in_(doc_ids),
            Document.is_active == True
        ).all()
        docs_by_id = {d.id: d for d in docs}

        candidates = []
        for did in doc_ids:
            doc = docs_by_id.get(did)
            if not doc:
                continue

            segment_ids = [l.segment_id for l in db.query(DocumentSegmentLink).filter_by(document_id=doc.id).all()]
            segments = db.query(DocSegment).filter(
                DocSegment.id.in_(segment_ids), DocSegment.is_active == True
            ).all() if segment_ids else []

            accessible = False
            blocking_segment = None
            if not segments:
                accessible = True  # documento sin segmento asignado = público
            else:
                if any(s.is_public for s in segments):
                    accessible = True
                else:
                    for s in segments:
                        if thread_has_segment_access(db, client_id, thread_id, s.id):
                            accessible = True
                            break
                    if not accessible:
                        blocking_segment = segments[0]

            candidates.append({
                "id": doc.id,
                "title": doc.title,
                "description": doc.description or "",
                "accessible": accessible,
                "blocking_segment_name": blocking_segment.name if blocking_segment else None,
                "blocking_segment_auth_mode": blocking_segment.auth_mode if blocking_segment else None,
            })
        return candidates
    finally:
        db.close()


def get_authorized_document_file(client_id: int, thread_id: str, document_id: int):
    """Re-verifica el acceso desde la base de datos antes de entregar un archivo:
    nunca hay que confiar en que el LLM solo emitió el tag [SEND_DOC: ...] para un
    documento realmente autorizado para este thread."""
    db = SessionLocal()
    try:
        doc = db.query(Document).filter_by(client_id=client_id, id=document_id, is_active=True).first()
        if not doc or not doc.file_path:
            return None

        segment_ids = [l.segment_id for l in db.query(DocumentSegmentLink).filter_by(document_id=doc.id).all()]
        segments = db.query(DocSegment).filter(
            DocSegment.id.in_(segment_ids), DocSegment.is_active == True
        ).all() if segment_ids else []

        authorized = (
            not segments
            or any(s.is_public for s in segments)
            or any(thread_has_segment_access(db, client_id, thread_id, s.id) for s in segments if not s.is_public)
        )

        if not authorized:
            log_document_search(client_id, thread_id, query="[SEND_DOC bloqueado]", found=True,
                                 results_count=1, document_title=doc.title, auth_blocked=True)
            return None

        return {
            "file_path": doc.file_path,
            "title": doc.title,
            "source_type": doc.source_type,
            "external_file_id": doc.external_file_id,
        }
    finally:
        db.close()


# --- LOGGING Y REFUERZO DE FRASES GATILLO ---

def log_document_search(client_id: int, thread_id: str, query: str, found: bool, results_count: int = 0,
                         document_title: str = None, auth_blocked: bool = False):
    db = SessionLocal()
    try:
        db.add(DocSearchLog(
            client_id=client_id,
            thread_id=thread_id,
            query=(query or "")[:255],
            found=found,
            results_count=results_count,
            document_title=document_title,
            auth_blocked=auth_blocked,
        ))
        db.commit()
    except Exception as e:
        logging.error(f"[DocLibrary] Error guardando búsqueda de documento: {e}")
    finally:
        db.close()


def get_doc_trigger_keywords(db, client_id: int, settings):
    keywords = []
    if settings and settings.doc_library_trigger_phrases:
        try:
            keywords.extend([k.strip().lower() for k in json.loads(settings.doc_library_trigger_phrases) if k and k.strip()])
        except Exception:
            pass

    docs = db.query(Document).filter_by(client_id=client_id, is_active=True).all()
    for d in docs:
        if d.keywords:
            keywords.extend([k.strip().lower() for k in d.keywords.split(",") if k.strip()])

    return list(dict.fromkeys(keywords))


def get_segment_by_trigger(db, client_id: int, message_text: str):
    """Devuelve (segment, fields) si el mensaje matchea las frases gatillo propias de algún
    segmento activo que además tenga datos de búsqueda configurados (ambos campos son requeridos,
    si falta uno el segmento se ignora acá). Si varios matchean, gana el primero por id. None si
    ninguno matchea o si el cliente no tiene ningún segmento con esto configurado."""
    if not message_text:
        return None
    msg_lower = message_text.lower()
    segments = db.query(DocSegment).filter(
        DocSegment.client_id == client_id, DocSegment.is_active == True
    ).order_by(DocSegment.id).all()
    for s in segments:
        if not s.search_trigger_phrases or not s.search_fields:
            continue
        try:
            phrases = [p.strip().lower() for p in json.loads(s.search_trigger_phrases) if p and p.strip()]
            fields = [f.strip() for f in json.loads(s.search_fields) if f and f.strip()]
        except Exception:
            continue
        if not phrases or not fields:
            continue
        if any(p in msg_lower for p in phrases):
            return s, fields
    return None


def build_segment_search_query(base_query: str, collected_data: dict, fields: list) -> str:
    """Combina la consulta original que disparó el flujo con los campos recolectados, como pares
    'etiqueta: valor', para enriquecer la búsqueda de texto libre (Chroma). No filtra metadata
    estructurada: solo arma un mejor texto de entrada para la misma búsqueda por similitud."""
    parts = []
    if base_query and base_query.strip():
        parts.append(base_query.strip())
    for f in fields:
        val = collected_data.get(f)
        if val and str(val).strip():
            parts.append(f"{f}: {str(val).strip()}")
    return " ".join(parts).strip()


def process_doc_login_completion(client_id: int, thread_id: str, topic: str):
    """Solo aplica un tag de auditoría: la sesión ya se creó en validate_segment_credentials.
    A propósito NO persiste collected_data en data_submissions, porque puede contener
    rastros del usuario/clave ingresados por chat."""
    try:
        from src.database.tagging_manager import assign_tag_by_name
        assign_tag_by_name(client_id, thread_id, "🔐 Acceso a Documentos")
    except Exception as e:
        logging.error(f"[Tagging] Error aplicando tag en process_doc_login_completion: {e}")
