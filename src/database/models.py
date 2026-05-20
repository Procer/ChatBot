from sqlalchemy import Column, Integer, String, Boolean, DateTime, ForeignKey, Text, Float
from sqlalchemy.orm import declarative_base, relationship
from datetime import datetime

Base = declarative_base()

# ==========================================
# CAPA 1: ADMINISTRACIÓN Y CONFIGURACIÓN
# ==========================================

class Client(Base):
    __tablename__ = "adm_clients"
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    business_name = Column(String(100), nullable=False)
    slug = Column(String(50), unique=True, nullable=False)
    status = Column(String(20), default="active")
    created_at = Column(DateTime, default=datetime.utcnow)
    
    settings = relationship("ClientSettings", back_populates="client", uselist=False)
    users = relationship("User", back_populates="client")
    conversations = relationship("Conversation", back_populates="client")

class ClientSettings(Base):
    __tablename__ = "adm_client_settings"
    
    client_id = Column(Integer, ForeignKey("adm_clients.id"), primary_key=True)
    whatsapp_instance_id = Column(String(100))
    whatsapp_token = Column(String(255))
    bot_system_prompt = Column(Text)
    google_sheet_id = Column(String(255))
    working_hours = Column(Text)
    
    feat_rag_enabled = Column(Boolean, default=False)
    feat_pdf_export = Column(Boolean, default=False)
    feat_human_handoff = Column(Boolean, default=False)
    
    client = relationship("Client", back_populates="settings")

class User(Base):
    __tablename__ = "adm_users"
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    client_id = Column(Integer, ForeignKey("adm_clients.id"), nullable=True) # Null = Super Admin
    email = Column(String(150), unique=True, nullable=False)
    password_hash = Column(String(255), nullable=False)
    role_name = Column(String(50), default="client_admin")
    
    client = relationship("Client", back_populates="users")

class UserPermission(Base):
    __tablename__ = "adm_user_permissions"
    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("adm_users.id"), nullable=False)
    menu_key = Column(String(50), nullable=False)
    can_access = Column(Boolean, default=True)

class MenuItem(Base):
    __tablename__ = "adm_menu_items"
    key = Column(String(50), primary_key=True)
    label = Column(String(100), nullable=False)
    icon = Column(String(50))

class AuditLog(Base):
    __tablename__ = "adm_audit_logs"
    id = Column(Integer, primary_key=True, autoincrement=True)
    client_id = Column(Integer, ForeignKey("adm_clients.id"), nullable=False)
    user_id = Column(String(100)) # ID o Email de quien hizo la acción
    action = Column(String(255), nullable=False)
    details = Column(Text)
    timestamp = Column(DateTime, default=datetime.utcnow)

class TokenUsage(Base):
    __tablename__ = "adm_token_usage"
    id = Column(Integer, primary_key=True, autoincrement=True)
    client_id = Column(Integer, ForeignKey("adm_clients.id"), nullable=False)
    thread_id = Column(String(100), nullable=False)
    model = Column(String(100), nullable=False)
    prompt_tokens = Column(Integer, default=0)
    completion_tokens = Column(Integer, default=0)
    cost_usd = Column(Float, default=0.0)
    timestamp = Column(DateTime, default=datetime.utcnow)

# ==========================================
# CAPA 2: OPERACIÓN (CHATS Y MÉTRICAS)
# ==========================================

class Conversation(Base):
    __tablename__ = "bot_conversations"
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    client_id = Column(Integer, ForeignKey("adm_clients.id"), nullable=False)
    user_phone = Column(String(50), nullable=False)
    platform = Column(String(20), default="whatsapp")
    status = Column(String(20), default="active")
    last_interaction = Column(DateTime, default=datetime.utcnow)
    
    client = relationship("Client", back_populates="conversations")

class UserProfile(Base):
    __tablename__ = "bot_user_profiles"
    id = Column(Integer, primary_key=True, autoincrement=True)
    client_id = Column(Integer, ForeignKey("adm_clients.id"), nullable=False)
    user_phone = Column(String(100), nullable=False)
    full_name = Column(String(255))
    created_at = Column(DateTime, default=datetime.utcnow)

class Message(Base):
    __tablename__ = "bot_messages"
    id = Column(Integer, primary_key=True, autoincrement=True)
    client_id = Column(Integer, ForeignKey("adm_clients.id"), nullable=False)
    thread_id = Column(String(100), nullable=False)
    role = Column(String(20), nullable=False) # user, bot
    content = Column(Text)
    whatsapp_id = Column(String(255))
    status = Column(String(50)) # Sent, Delivered, Read, etc.
    timestamp = Column(DateTime, default=datetime.utcnow)

class SessionAnalytics(Base):
    __tablename__ = "bot_session_analytics"
    id = Column(Integer, primary_key=True, autoincrement=True)
    client_id = Column(Integer, ForeignKey("adm_clients.id"), nullable=False)
    thread_id = Column(String(100), nullable=False)
    total_tokens = Column(Integer, default=0)
    total_cost_usd = Column(Float, default=0.0)
    intent = Column(String(100))
    is_deflected = Column(Boolean, default=True)
    last_activity = Column(DateTime, default=datetime.utcnow)

class Alert(Base):
    __tablename__ = "bot_alerts"
    id = Column(Integer, primary_key=True, autoincrement=True)
    client_id = Column(Integer, ForeignKey("adm_clients.id"), nullable=False)
    motivo = Column(String(255), nullable=False)
    leida = Column(Boolean, default=False)
    fecha = Column(DateTime, default=datetime.utcnow)

class ChatNote(Base):
    __tablename__ = "bot_chat_notes"
    id = Column(Integer, primary_key=True, autoincrement=True)
    client_id = Column(Integer, ForeignKey("adm_clients.id"), nullable=False)
    thread_id = Column(String(100), nullable=False)
    notes = Column(Text)

class Pause(Base):
    __tablename__ = "bot_pauses"
    id = Column(Integer, primary_key=True, autoincrement=True)
    client_id = Column(Integer, ForeignKey("adm_clients.id"), nullable=False)
    user_id = Column(String(100), nullable=False)
    paused_until = Column(DateTime, nullable=False)

class Attachment(Base):
    __tablename__ = "bot_attachments"
    id = Column(Integer, primary_key=True, autoincrement=True)
    client_id = Column(Integer, ForeignKey("adm_clients.id"), nullable=False)
    thread_id = Column(String(100), nullable=False)
    file_path = Column(String(255), nullable=False)
    file_name = Column(String(255))
    file_type = Column(String(50))
    context = Column(Text)
    form_id = Column(Integer, nullable=True) # Ligado a data_submissions
    created_at = Column(DateTime, default=datetime.utcnow)

# ==========================================
# CAPA 3: DATOS CAPTURADOS (TRÁMITES Y CONOCIMIENTO)
# ==========================================

class Submission(Base):
    __tablename__ = "data_submissions"
    id = Column(Integer, primary_key=True, autoincrement=True)
    client_id = Column(Integer, ForeignKey("adm_clients.id"), nullable=False)
    conversation_id = Column(Integer, ForeignKey("bot_conversations.id"), nullable=True)
    thread_id = Column(String(100))
    topic = Column(String(255))
    status = Column(String(50), default="pending")
    payload_json = Column(Text)
    created_at = Column(DateTime, default=datetime.utcnow)

class Knowledge(Base):
    __tablename__ = "data_knowledge"
    id = Column(Integer, primary_key=True, autoincrement=True)
    client_id = Column(Integer, ForeignKey("adm_clients.id"), nullable=False)
    topic = Column(String(255), nullable=False)
    content = Column(Text, nullable=False)
    category = Column(String(100))
    has_form = Column(Boolean, default=False)
    form_fields = Column(Text)
    storage_dest = Column(String(50), default="database")
    allow_scheduling = Column(Boolean, default=False)
    interactive_options = Column(Text)
    media_path = Column(String(255))
    
class KnowledgeGap(Base):
    __tablename__ = "data_knowledge_gaps"
    id = Column(Integer, primary_key=True, autoincrement=True)
    client_id = Column(Integer, ForeignKey("adm_clients.id"), nullable=False)
    topic = Column(String(255), nullable=False)
    frequency = Column(Integer, default=1)
    status = Column(String(50), default="pending")
    
class Appointment(Base):
    __tablename__ = "data_appointments"
    id = Column(Integer, primary_key=True, autoincrement=True)
    client_id = Column(Integer, ForeignKey("adm_clients.id"), nullable=False)
    thread_id = Column(String(100), nullable=False)
    client_name = Column(String(255))
    date = Column(String(20))
    time = Column(String(20))
    service = Column(String(255))
    reason = Column(Text)
    status = Column(String(50), default="pending")
    created_at = Column(DateTime, default=datetime.utcnow)

class Proceeding(Base):
    __tablename__ = "data_proceedings"
    id = Column(Integer, primary_key=True, autoincrement=True)
    client_id = Column(Integer, ForeignKey("adm_clients.id"), nullable=False)
    tracking_number = Column(String(100), nullable=False, unique=True)
    client_name = Column(String(255))
    topic = Column(String(255))
    status = Column(String(50))
    notes = Column(Text)
    updated_at = Column(DateTime, default=datetime.utcnow)
