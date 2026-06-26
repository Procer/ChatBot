# 🗄️ Estructura de Datos (SQL Server SaaS)

El sistema ZSG-Bot-iA ha sido migrado de múltiples archivos SQLite independientes a una base de datos relacional centralizada en **SQL Server** en Docker, permitiendo una arquitectura SaaS Multi-Tenant. Todas las consultas operativas están filtradas estrictamente mediante el campo `client_id` para garantizar el aislamiento de la información.

## 1. Arquitectura de Base de Datos
- **Motor:** Microsoft SQL Server (Docker).
- **ORM:** SQLAlchemy para Python.
- **Migraciones:** Alembic (`alembic upgrade head`).

---

## 2. Descripción de las Tablas Principales

### Capa de Administración (Multi-Tenant)
- **adm_clients (`Client`)**: Registro de empresas clientes (inquilinos) de la plataforma SaaS.
  - `id` (PK), `name` (Nombre de la empresa), `slug` (Ruta única de webhook), `active`, `created_at`.
- **adm_client_settings (`ClientSettings`)**: Configuración individual y feature flags de cada cliente.
  - `client_id` (FK), `working_hours`, `appointment_duration` (duración por defecto), `google_calendar_id`, `reminder_24h_enabled`, `reminder_24h_hours` (horas de antelación personalizables), `reminder_24h_template`, `reminder_2h_enabled`, `reminder_2h_hours`, `reminder_2h_template`, etc.
- **adm_users (`User`)**: Usuarios autorizados a ingresar al panel administrativo de cada cliente.
  - `id` (PK), `client_id` (FK), `username`, `password_hash`, `role` (`client_admin` o `superadmin`).

### Capa de Operación del Bot
- **bot_messages (`Message`)**: Registro unificado de la conversación (WhatsApp y Telegram).
  - `id` (PK), `client_id` (FK), `thread_id` (Identificador del chat/teléfono), `role` (`user` o `bot`), `content` (Texto del mensaje), `whatsapp_id`, `timestamp`.
- **bot_user_profiles (`UserProfile`)**: Perfiles detectados de los usuarios finales.
  - `client_id` (FK), `user_phone` (thread_id), `full_name` (Nombre y apellido del cliente), `created_at`.
- **bot_pauses (`Pause`)**: Indica si la IA está pausada para dar paso a un operador humano.
  - `client_id` (FK), `thread_id` (PK), `is_paused` (Boolean), `paused_at`.

### Capa de Trámites y Conocimiento
- **data_submissions (`Submission`)**: Formularios finalizados capturados por la IA.
  - `id` (PK), `client_id` (FK), `user_id` (thread_id), `user_name`, `topic` (Nombre del trámite), `parsed_data` (JSON con campos extraídos), `files` (JSON con rutas de archivos cargados), `created_at`.
- **data_knowledge (`Knowledge`)**: Base de conocimiento conversacional y configuración de temas específicos.
  - `id` (PK), `client_id` (FK), `topic`, `content` (Texto informativo), `has_form` (Boolean), `form_fields` (Campos a recolectar si tiene formulario), `interactive_options`, `media_path` (Ruta a PDF adjunto), `send_as_file`, `allow_scheduling` (Permite turnos para este trámite), `scheduling_hours` (Horarios específicos de atención para el servicio), `appointment_duration` (Duración del turno para el servicio).

### Capa de Agendamiento y Turnos
- **appointments (`Appointment`)**: Turnos agendados y confirmados.
  - `id` (PK), `client_id` (FK), `thread_id`, `client_name`, `date` (YYYY-MM-DD), `time` (HH:MM), `reason` (Trámite o motivo), `status` (`confirmed`, `pending`, `cancelled`), `created_at`.
- **scheduling_exceptions (`SchedulingException`)**: Feriados, vacaciones o bloqueos específicos de fecha.
  - `id` (PK), `client_id` (FK), `date` (YYYY-MM-DD), `start_time` (HH:MM, opcional), `end_time` (HH:MM, opcional), `reason` (Motivo del bloqueo).

### Capa de Auditoría y Analíticas
- **bot_audit_logs (`AuditLog`)**: Historial de acciones administrativas y eventos automatizados (ej: envío de recordatorios).
  - `id` (PK), `client_id` (FK), `user_id` (Quién lo ejecutó), `action` (Ej: `reminder_24h_sent`), `details` (ID del turno/registro), `timestamp`.
- **bot_token_usage (`TokenUsage`)**: Métricas de consumo de la API de LLMs.
  - `id` (PK), `client_id` (FK), `thread_id`, `prompt_tokens`, `completion_tokens`, `cost_usd`, `timestamp`.

---

## 3. Base Vectorial y Checkpoints Locales

- **ChromaDB:** Ubicada localmente en `/chroma_db`. Almacena los embeddings vectorizados de los documentos PDF de cada cliente, aislados por metadatos de `client_id` para realizar búsquedas semánticas precisas.
- **SQLite Checkpoints (`checkpoints.sqlite`)**: Almacena de forma local los estados internos del grafo de LangGraph. Su estructura interna (`checkpoints`, `writes`, `checkpoint_writes`) es administrada automáticamente por `SqliteSaver` para restaurar el contexto e historial reciente de mensajes de la IA de forma instantánea.

---
Zárate System Group - Estructura de Datos v2.5.0 SaaS
