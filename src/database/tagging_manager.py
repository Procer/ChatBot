import logging
from datetime import datetime
from src.database.session import SessionLocal
from src.database.models import Tag, UserTag, UserProfile

# Catálogo de etiquetas del sistema predefinidas
SYSTEM_TAGS = [
    {"name": "👋 Nuevo Contacto", "color": "#10B981"},
    {"name": "📱 Canal: WhatsApp", "color": "#25D366"},
    {"name": "💬 Canal: Telegram", "color": "#0088CC"},
    {"name": "⚡ Activo Reciente", "color": "#3B82F6"},
    {"name": "🗓️ Turno Agendado", "color": "#10B981"},
    {"name": "❌ Turno Cancelado", "color": "#6B7280"},
    {"name": "📝 Trámite Iniciado", "color": "#3B82F6"},
    {"name": "🎓 Trámite Completado", "color": "#8B5CF6"},
    {"name": "⚠️ Sin Responder", "color": "#F59E0B"},
    {"name": "👤 Humano Requerido", "color": "#EF4444"}
]

def ensure_default_tags(client_id: int):
    """Crea las etiquetas automáticas del sistema para un cliente si no existen."""
    db = SessionLocal()
    try:
        for t in SYSTEM_TAGS:
            exists = db.query(Tag).filter_by(client_id=client_id, name=t["name"]).first()
            if not exists:
                new_tag = Tag(
                    client_id=client_id,
                    name=t["name"],
                    color=t["color"],
                    is_system=True
                )
                db.add(new_tag)
        db.commit()
    except Exception as e:
        logging.error(f"[Tagging] Error ensuring default tags for client {client_id}: {e}")
        db.rollback()
    finally:
        db.close()

def assign_tag_by_name(client_id: int, thread_id: str, tag_name: str, assigned_by: str = 'system'):
    """Asigna una etiqueta a un usuario por nombre. Crea la etiqueta si no existe."""
    ensure_default_tags(client_id)
    db = SessionLocal()
    try:
        # Buscar o crear la etiqueta
        tag = db.query(Tag).filter_by(client_id=client_id, name=tag_name).first()
        if not tag:
            tag = Tag(
                client_id=client_id,
                name=tag_name,
                color="#6B7280",  # Gris por defecto para etiquetas creadas al vuelo
                is_system=False
            )
            db.add(tag)
            db.commit()
            db.refresh(tag)
            
        # Verificar si la asociación ya existe
        assoc = db.query(UserTag).filter_by(client_id=client_id, thread_id=thread_id, tag_id=tag.id).first()
        if not assoc:
            new_assoc = UserTag(
                client_id=client_id,
                thread_id=thread_id,
                tag_id=tag.id,
                assigned_by=assigned_by
            )
            db.add(new_assoc)
            db.commit()
            logging.info(f"[Tagging] Tag '{tag_name}' assigned to {thread_id} for client {client_id}")
    except Exception as e:
        logging.error(f"[Tagging] Error assigning tag '{tag_name}' to {thread_id}: {e}")
        db.rollback()
    finally:
        db.close()

def remove_tag_by_name(client_id: int, thread_id: str, tag_name: str):
    """Elimina la asociación de una etiqueta de un usuario por su nombre."""
    db = SessionLocal()
    try:
        tag = db.query(Tag).filter_by(client_id=client_id, name=tag_name).first()
        if tag:
            db.query(UserTag).filter_by(client_id=client_id, thread_id=thread_id, tag_id=tag.id).delete()
            db.commit()
            logging.info(f"[Tagging] Tag '{tag_name}' removed from {thread_id} for client {client_id}")
    except Exception as e:
        logging.error(f"[Tagging] Error removing tag '{tag_name}' from {thread_id}: {e}")
        db.rollback()
    finally:
        db.close()

def clear_user_tags(client_id: int, thread_id: str):
    """Elimina todas las asociaciones de etiquetas de un usuario."""
    db = SessionLocal()
    try:
        db.query(UserTag).filter_by(client_id=client_id, thread_id=thread_id).delete()
        db.commit()
        logging.info(f"[Tagging] All tags cleared from {thread_id} for client {client_id}")
    except Exception as e:
        logging.error(f"[Tagging] Error clearing tags from {thread_id}: {e}")
        db.rollback()
    finally:
        db.close()

def get_user_tags(client_id: int, thread_id: str):
    """Retorna la lista de etiquetas de un usuario."""
    db = SessionLocal()
    try:
        tags = db.query(Tag).join(UserTag, UserTag.tag_id == Tag.id).filter(
            UserTag.client_id == client_id,
            UserTag.thread_id == thread_id
        ).all()
        return [{"id": t.id, "name": t.name, "color": t.color, "is_system": t.is_system} for t in tags]
    except Exception as e:
        logging.error(f"[Tagging] Error fetching tags for user {thread_id}: {e}")
        return []
    finally:
        db.close()

def get_user_role(client_id: int, thread_id: str) -> str:
    """Retorna el rol/categoría de un usuario. Retorna 'General' si no se especifica."""
    db = SessionLocal()
    try:
        prof = db.query(UserProfile).filter_by(client_id=client_id, user_phone=thread_id).first()
        if prof and prof.role:
            return prof.role
        return "General"
    except Exception as e:
        logging.error(f"[Tagging] Error fetching role for user {thread_id}: {e}")
        return "General"
    finally:
        db.close()

def set_user_role(client_id: int, thread_id: str, role: str):
    """Establece el rol/categoría de un usuario."""
    db = SessionLocal()
    try:
        prof = db.query(UserProfile).filter_by(client_id=client_id, user_phone=thread_id).first()
        if not prof:
            prof = UserProfile(
                client_id=client_id,
                user_phone=thread_id,
                full_name="Cliente",
                role=role
            )
            db.add(prof)
        else:
            prof.role = role
        db.commit()
        logging.info(f"[Tagging] Role for user {thread_id} set to '{role}'")
    except Exception as e:
        logging.error(f"[Tagging] Error setting role '{role}' for user {thread_id}: {e}")
        db.rollback()
    finally:
        db.close()
