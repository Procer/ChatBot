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
    
    company_address = Column(String(255))
    company_phone = Column(String(50))
    bot_name = Column(String(100))
    bot_tone = Column(String(50))
    out_of_office_enabled = Column(Boolean, default=False)
    out_of_office_message = Column(Text)
    welcome_message_enabled = Column(Boolean, default=False)
    welcome_message_text = Column(Text)
    welcome_threshold_days = Column(Integer, default=7)
    welcome_media_path = Column(String(255))
    
    test_mode_enabled = Column(Boolean, default=False)
    test_numbers = Column(String(255))
    
    webhook_base_url = Column(String(255))
    whatsapp_enabled = Column(Boolean, default=True)
    telegram_enabled = Column(Boolean, default=False)
    telegram_token = Column(String(255))
    
    feat_rag_enabled = Column(Boolean, default=False)
    feat_pdf_export = Column(Boolean, default=False)
    feat_human_handoff = Column(Boolean, default=False)
    
    # --- FEATURE FLAGS DE PANELES ---
    feat_dashboard = Column(Boolean, default=True)
    feat_history = Column(Boolean, default=True)
    feat_contacts = Column(Boolean, default=True)
    feat_submissions = Column(Boolean, default=True)
    feat_appointments = Column(Boolean, default=True)
    feat_gaps = Column(Boolean, default=True)
    feat_channels = Column(Boolean, default=True)
    feat_config = Column(Boolean, default=True)
    feat_audit = Column(Boolean, default=True)
    
    # --- FEATURE FLAGS DE CATÁLOGO ---
    feat_catalog = Column(Boolean, default=False)
    feat_catalog_dynamic_fields = Column(Boolean, default=False)

    # --- FEATURE FLAG DE BIBLIOTECA DE DOCUMENTOS ---
    feat_document_library = Column(Boolean, default=False)
    doc_library_trigger_phrases = Column(Text, nullable=True)  # JSON list, frases gatillo generales del cliente

    # --- PREGUNTA DE SALUDO (ofrecer un segmento de documentos en el primer mensaje) ---
    greeting_question_enabled = Column(Boolean, default=False, server_default='0')
    greeting_question_text = Column(Text, nullable=True)  # ej: "¿Querés descargar algún resultado o protocolo?"
    greeting_question_segment_id = Column(Integer, ForeignKey("data_doc_segments.id"), nullable=True)

    # --- MODOS DE RESPUESTA DEL CATÁLOGO (combinables) ---
    catalog_require_lead_before_price = Column(Boolean, default=False)
    catalog_lead_fields = Column(Text, nullable=True)  # JSON list, ej: ["Nombre y Apellido","Email","Teléfono"]
    catalog_send_pdf_quote = Column(Boolean, default=False)

    # --- TOMA DE PEDIDO DEL CATÁLOGO ---
    catalog_order_fields = Column(Text, nullable=True)  # JSON list, ej: ["Cantidad","Fecha de Entrega"]
    catalog_min_lead_days = Column(Integer, default=0)  # 0 = sin restricción
    catalog_confirm_attributes = Column(Boolean, default=False)
    catalog_include_images = Column(Boolean, default=True)
    catalog_response_style = Column(Text, nullable=True)  # instrucciones libres de tono/orden

    # --- NUEVAS COLUMNAS DE TURNOS (SAAS) ---
    scheduling_provider = Column(String(50), default="local")
    scheduling_days = Column(String(255), default="mon,tue,wed,thu,fri")
    scheduling_capacity = Column(Integer, default=1)
    appointment_duration = Column(Integer, default=30)
    google_calendar_id = Column(String(255), default="primary")
    enable_working_hours_for_scheduling = Column(Boolean, default=False)
    
    # --- AJUSTES DE RECORDATORIOS AUTOMÁTICOS ---
    reminder_24h_enabled = Column(Boolean, default=False)
    reminder_24h_template = Column(Text, nullable=True)
    reminder_24h_hours = Column(Integer, default=24, server_default='24')
    reminder_2h_enabled = Column(Boolean, default=False)
    reminder_2h_template = Column(Text, nullable=True)
    reminder_2h_hours = Column(Integer, default=2, server_default='2')

    # --- SINCRONIZACIÓN CON GOOGLE DRIVE (Biblioteca de Documentos) ---
    # Cuenta de servicio propia de ESTE cliente (no OAuth de usuario): el cliente comparte
    # su carpeta de Drive con el email de la cuenta de servicio, sin pantalla de consentimiento
    # ni vencimiento de token (a diferencia del refresh token OAuth que reemplazó esto).
    gdrive_service_account_json_encrypted = Column(Text, nullable=True)  # Fernet, nunca texto plano (más sensible que whatsapp_token/telegram_token)
    gdrive_service_account_email = Column(String(255), nullable=True)  # client_email cacheado del JSON, para mostrar en el panel sin desencriptar
    gdrive_root_folder_id = Column(String(255), nullable=True)
    gdrive_root_folder_name = Column(String(255), nullable=True)
    gdrive_last_sync_at = Column(DateTime, nullable=True)
    gdrive_last_sync_summary = Column(Text, nullable=True)  # JSON: {"created":N,"unmapped_folders":[...],"missing_in_drive":N}
    gdrive_share_revoked = Column(Boolean, default=False)  # la SA tiene credenciales válidas pero la carpeta ya no está compartida con ella
    gdrive_sync_interval_minutes = Column(Integer, nullable=False, default=480, server_default="480")  # cada cuánto corre el sync automático para ESTE cliente (default 8hs, igual que antes de hacerse configurable)

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
    role = Column(String(50), default="General", nullable=False)
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
    scheduling_hours = Column(Text, nullable=True)
    scheduling_days = Column(String(50), nullable=True)  # "mon,wed,fri"; NULL/vacío = usar los días generales del cliente (ClientSettings.scheduling_days)
    appointment_extra_fields = Column(Text, nullable=True)  # "Obra Social, DNI, Edad"; datos puntuales a pedir antes de confirmar el turno de este trámite
    appointment_duration = Column(Integer, nullable=True)
    scheduling_capacity = Column(Integer, default=1, nullable=True)
    interactive_options = Column(Text)
    media_path = Column(String(255))
    analyze_rag = Column(Boolean, default=True)
    send_as_file = Column(Boolean, default=True)
    required_role = Column(String(50), default="General", nullable=False)
    tags_to_apply = Column(String(512), nullable=True)
    
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

class SchedulingException(Base):
    __tablename__ = "data_scheduling_exceptions"
    id = Column(Integer, primary_key=True, autoincrement=True)
    client_id = Column(Integer, ForeignKey("adm_clients.id"), nullable=False)
    date = Column(String(20), nullable=False) # YYYY-MM-DD
    start_time = Column(String(20), nullable=True) # HH:MM (None if all day)
    end_time = Column(String(20), nullable=True) # HH:MM (None if all day)
    description = Column(String(255), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

class Tag(Base):
    __tablename__ = "bot_tags"
    id = Column(Integer, primary_key=True, autoincrement=True)
    client_id = Column(Integer, ForeignKey("adm_clients.id"), nullable=False)
    name = Column(String(100), nullable=False)
    color = Column(String(10), default="#6B7280", nullable=False)
    is_system = Column(Boolean, default=False, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)

class UserTag(Base):
    __tablename__ = "bot_user_tags"
    id = Column(Integer, primary_key=True, autoincrement=True)
    client_id = Column(Integer, ForeignKey("adm_clients.id"), nullable=False)
    thread_id = Column(String(100), nullable=False)
    tag_id = Column(Integer, ForeignKey("bot_tags.id", ondelete="CASCADE"), nullable=False)
    assigned_at = Column(DateTime, default=datetime.utcnow)
    assigned_by = Column(String(100), default="system", nullable=False)

class CatalogProduct(Base):
    __tablename__ = "data_catalog_products"
    id = Column(Integer, primary_key=True, autoincrement=True)
    client_id = Column(Integer, ForeignKey("adm_clients.id"), nullable=False)
    sku = Column(String(100), nullable=True)
    name = Column(String(255), nullable=False)
    description = Column(Text, nullable=True)
    price = Column(Float, default=0.0)
    price_rules = Column(Text, nullable=True) # JSON para rangos de precios
    min_quantity = Column(Integer, default=1)
    image_path = Column(String(255), nullable=True)
    custom_attributes = Column(Text, nullable=True) # JSON para atributos dinámicos (Talle, Color, etc.)
    manage_stock = Column(Boolean, default=False)
    stock = Column(Integer, default=0)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)

class CatalogRequest(Base):
    __tablename__ = "data_catalog_requests"
    id = Column(Integer, primary_key=True, autoincrement=True)
    client_id = Column(Integer, ForeignKey("adm_clients.id"), nullable=False)
    thread_id = Column(String(100), nullable=False)
    tracking_number = Column(String(100), unique=True, nullable=False)
    tipo = Column(String(20), nullable=False)  # "Consulta" | "Pedido"
    producto_nombre = Column(String(255), nullable=True)
    producto_sku = Column(String(100), nullable=True)
    cantidad = Column(Integer, nullable=True)
    fecha_entrega = Column(String(20), nullable=True)
    contact_data = Column(Text, nullable=True)  # JSON: Nombre/Email/Teléfono/Empresa/etc.
    pdf_path = Column(String(255), nullable=True)
    status = Column(String(50), default="Pendiente")
    created_at = Column(DateTime, default=datetime.utcnow)

class CatalogSearchLog(Base):
    __tablename__ = "data_catalog_search_logs"
    id = Column(Integer, primary_key=True, autoincrement=True)
    client_id = Column(Integer, ForeignKey("adm_clients.id"), nullable=False)
    thread_id = Column(String(100), nullable=False)
    query = Column(String(255), nullable=False)
    found = Column(Boolean, default=False)
    results_count = Column(Integer, default=0)
    producto_nombre = Column(String(255), nullable=True)
    producto_sku = Column(String(100), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

class CatalogPriceHistory(Base):
    __tablename__ = "data_catalog_price_history"
    id = Column(Integer, primary_key=True, autoincrement=True)
    client_id = Column(Integer, ForeignKey("adm_clients.id"), nullable=False)
    product_id = Column(Integer, ForeignKey("data_catalog_products.id", ondelete="CASCADE"), nullable=False)
    old_price = Column(Float, nullable=False)
    new_price = Column(Float, nullable=False)
    reason = Column(String(255), nullable=True) # ej: 'Ajuste Masivo +15%'
    created_at = Column(DateTime, default=datetime.utcnow)

# ==========================================
# CAPA 4: BIBLIOTECA DE DOCUMENTOS
# ==========================================

class DocSegment(Base):
    __tablename__ = "data_doc_segments"
    id = Column(Integer, primary_key=True, autoincrement=True)
    client_id = Column(Integer, ForeignKey("adm_clients.id"), nullable=False)
    name = Column(String(150), nullable=False)
    is_public = Column(Boolean, default=True)
    auth_mode = Column(String(20), default="generic")  # "generic" | "individual" (solo aplica si is_public=False)
    generic_password_hash = Column(String(255), nullable=True)
    session_expiry_days = Column(Integer, nullable=True)  # NULL = sesión permanente
    is_active = Column(Boolean, default=True)
    # Independiente de is_public/auth_mode: search_trigger_phrases decide en qué segmento buscar
    # (routing), search_fields son los únicos datos usados como texto de búsqueda dentro de ese
    # segmento (la frase gatillo no se incluye en la búsqueda). Ambas son listas JSON; NULL =
    # comportamiento de búsqueda libre de siempre, sin ningún dato extra.
    search_trigger_phrases = Column(Text, nullable=True)
    search_fields = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

class DocLibraryUser(Base):
    __tablename__ = "data_doc_library_users"
    id = Column(Integer, primary_key=True, autoincrement=True)
    client_id = Column(Integer, ForeignKey("adm_clients.id"), nullable=False)
    username = Column(String(100), nullable=False)
    password_hash = Column(String(255), nullable=False)
    full_name = Column(String(255), nullable=True)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)

class DocLibraryUserSegment(Base):
    __tablename__ = "data_doc_library_user_segments"
    id = Column(Integer, primary_key=True, autoincrement=True)
    client_id = Column(Integer, ForeignKey("adm_clients.id"), nullable=False)
    library_user_id = Column(Integer, ForeignKey("data_doc_library_users.id", ondelete="CASCADE"), nullable=False)
    segment_id = Column(Integer, ForeignKey("data_doc_segments.id", ondelete="CASCADE"), nullable=False)

class Document(Base):
    __tablename__ = "data_doc_documents"
    id = Column(Integer, primary_key=True, autoincrement=True)
    client_id = Column(Integer, ForeignKey("adm_clients.id"), nullable=False)
    title = Column(String(255), nullable=False)
    keywords = Column(Text, nullable=True)  # alias/palabras clave embebidas junto al título (NUNCA el contenido del archivo)
    description = Column(Text, nullable=True)  # solo uso admin, no se embebe
    file_path = Column(String(255), nullable=True)
    source_type = Column(String(20), default="local")  # "local" hoy; punto de extensión (sharepoint/gdrive/onedrive) a futuro
    external_file_id = Column(String(255), nullable=True)  # Drive fileId (u otro origen externo), para upsert idempotente en cada sync
    gdrive_last_seen_at = Column(DateTime, nullable=True)  # última vez que el sync lo encontró presente en Drive
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

class DocumentSegmentLink(Base):
    __tablename__ = "data_doc_document_segments"
    id = Column(Integer, primary_key=True, autoincrement=True)
    client_id = Column(Integer, ForeignKey("adm_clients.id"), nullable=False)
    document_id = Column(Integer, ForeignKey("data_doc_documents.id", ondelete="CASCADE"), nullable=False)
    segment_id = Column(Integer, ForeignKey("data_doc_segments.id", ondelete="CASCADE"), nullable=False)

class DocSession(Base):
    __tablename__ = "data_doc_sessions"
    id = Column(Integer, primary_key=True, autoincrement=True)
    client_id = Column(Integer, ForeignKey("adm_clients.id"), nullable=False)
    thread_id = Column(String(100), nullable=False)
    segment_id = Column(Integer, ForeignKey("data_doc_segments.id", ondelete="CASCADE"), nullable=False)
    library_user_id = Column(Integer, ForeignKey("data_doc_library_users.id"), nullable=True)  # NULL si auth genérica
    authenticated_at = Column(DateTime, default=datetime.utcnow)
    expires_at = Column(DateTime, nullable=True)  # NULL = permanente
    created_at = Column(DateTime, default=datetime.utcnow)

class DocSearchLog(Base):
    __tablename__ = "data_doc_search_logs"
    id = Column(Integer, primary_key=True, autoincrement=True)
    client_id = Column(Integer, ForeignKey("adm_clients.id"), nullable=False)
    thread_id = Column(String(100), nullable=False)
    query = Column(String(255), nullable=False)
    found = Column(Boolean, default=False)
    results_count = Column(Integer, default=0)
    document_title = Column(String(255), nullable=True)
    auth_blocked = Column(Boolean, default=False)  # hubo match pero bloqueado por falta de acceso
    created_at = Column(DateTime, default=datetime.utcnow)

# ==========================================
# CAPA 5: MENSAJES DE SEGUIMIENTO POR INACTIVIDAD
# ==========================================

class FollowupContent(Base):
    __tablename__ = "data_followup_content"
    id = Column(Integer, primary_key=True, autoincrement=True)
    client_id = Column(Integer, ForeignKey("adm_clients.id"), nullable=False)
    name = Column(String(150), nullable=False)
    message_text = Column(Text, nullable=False)
    media_path = Column(String(255), nullable=True)
    interval_minutes = Column(Integer, nullable=False, default=120)
    valid_from = Column(String(20), nullable=False)  # YYYY-MM-DD
    valid_until = Column(String(20), nullable=False)  # YYYY-MM-DD
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)

class FollowupLog(Base):
    __tablename__ = "bot_followup_log"
    id = Column(Integer, primary_key=True, autoincrement=True)
    client_id = Column(Integer, ForeignKey("adm_clients.id"), nullable=False)
    thread_id = Column(String(100), nullable=False)
    content_id = Column(Integer, ForeignKey("data_followup_content.id", ondelete="CASCADE"), nullable=False)
    sent_at = Column(DateTime, default=datetime.utcnow)

# ==========================================
# CAPA 6: PRICING / CALCULADORA SAAS (SUPER ADMIN)
# ==========================================

class ClientPricing(Base):
    __tablename__ = "adm_client_pricing"
    id = Column(Integer, primary_key=True, autoincrement=True)
    client_id = Column(Integer, ForeignKey("adm_clients.id"), unique=True, nullable=False)
    abono_usd = Column(Float, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

class ClientPricingHistory(Base):
    __tablename__ = "adm_client_pricing_history"
    id = Column(Integer, primary_key=True, autoincrement=True)
    client_id = Column(Integer, ForeignKey("adm_clients.id"), nullable=False)
    old_abono_usd = Column(Float, nullable=True)
    new_abono_usd = Column(Float, nullable=False)
    reason = Column(String(255), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

class PricingSimulation(Base):
    __tablename__ = "adm_pricing_simulations"
    id = Column(Integer, primary_key=True, autoincrement=True)
    client_id = Column(Integer, ForeignKey("adm_clients.id"), nullable=True)
    label = Column(String(150), nullable=True)
    tipo_cambio = Column(Float, nullable=False)
    clientes = Column(Integer, nullable=False)
    abono_usd = Column(Float, nullable=False)
    green_api_usd = Column(Float, nullable=False)
    openai_usd = Column(Float, nullable=False)
    server_tramo1 = Column(Float, nullable=False)
    server_tramo2 = Column(Float, nullable=False)
    server_tramo3 = Column(Float, nullable=False)
    ganancia_ars = Column(Float, nullable=False)
    status = Column(String(20), nullable=False, default="borrador")  # borrador | enviada | aprobada | rechazada
    status_updated_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
