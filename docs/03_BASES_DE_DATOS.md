# 🗄️ Estructura de Datos

El sistema utiliza tres bases de datos SQLite independientes para separar las responsabilidades y optimizar el rendimiento.

## 1. settings.sqlite
Gestiona la configuración central y los datos recolectados.
- **form_submissions:** Almacena los formularios completados por los usuarios.
    - `id` (PK), `user_id`, `user_name`, `topic`, `parsed_data` (JSON con los datos extraídos), `files` (JSON con rutas de archivos), `created_at`.
- **system_settings:** Configuración dinámica del bot.
    - `key`, `value` (Permite activar/desactivar funciones desde el panel).
- **knowledge_base:** Fragmentos de información para el bot.

## 2. analytics.sqlite
Registra la actividad y el rendimiento para generar estadísticas.
- **message_logs:** Cada interacción enviada o recibida.
    - `timestamp`, `channel` (WA/TG), `user_id`, `role` (user/bot).
- **cost_logs:** Seguimiento de tokens utilizados y costo estimado por proveedor.
- **usage_stats:** Métricas diarias de usuarios activos y trámites iniciados.

## 3. checkpoints.sqlite
Utilizada exclusivamente por **LangGraph** para la persistencia de memoria.
- Almacena el historial de las conversaciones para que el bot pueda "recordar" el contexto incluso después de días o reinicios del servidor.
- Gestiona el `thread_id` único por usuario y canal.

## 4. Base Vectorial (ChromaDB)
Ubicada en la carpeta `/chroma_db`. No es una base relacional, sino un índice de vectores que permite al bot buscar información dentro de los documentos PDF cargados en la carpeta `/data`.

---
ZSG System Group - Gestión de Datos
