# 🛠️ Stack Tecnológico

ZSG-Bot-iA utiliza un conjunto de herramientas modernas para garantizar escalabilidad, velocidad, multi-tenancy y una experiencia de usuario superior en su arquitectura SaaS.

## Backend (El Motor)
- **Python 3.11+:** Lenguaje base por su robustez en el ecosistema de IA.
- **FastAPI:** Framework web asíncrono de alto rendimiento para el Panel Admin, Panel Súper Admin y los Webhooks Multi-Cliente en el puerto 8001.
- **Uvicorn:** Servidor ASGI para ejecutar la aplicación FastAPI.
- **LangChain / LangGraph:** Orquestación de agentes de IA y flujos de trabajo cíclicos.
- **SQLAlchemy:** ORM utilizado para interactuar de forma segura con la base de datos centralizada.
- **Alembic:** Herramienta de migración para versionar y aplicar cambios de esquema en base de datos de manera automatizada.

## Base de Datos (Persistencia)
- **SQL Server (vía Docker):** Motor de base de datos relacional robusto centralizado para configuraciones de clientes, usuarios del panel, logs de chat, analíticas y agenda de turnos.
- **SQLite (checkpoints.sqlite):** Persistencia local ultrarrápida exclusiva para los puntos de control (checkpoints) de LangGraph de cada hilo de conversación.

## Inteligencia Artificial (El Cerebro)
- **OpenAI (GPT-4o / GPT-4o-mini):** Utilizado para tareas de razonamiento complejo, toma de decisiones y llamadas a herramientas.
- **Google Gemini (1.5 Flash / Pro):** Utilizado para soporte rápido y optimización de costos.
- **ChromaDB / RAG:** Base de datos vectorial para almacenar y consultar el conocimiento especializado extraído de documentos adjuntos (PDF/TXT) cargados por el cliente.

## Frontend (Panel Admin)
- **HTML5 / Jinja2:** Renderizado dinámico desde el servidor FastAPI.
- **Tailwind CSS & Vanilla CSS:** Framework y estilos personalizados (Glassmorphism, Bento Design, Dark Mode) para una UI/UX premium.
- **Lucide Icons:** Set de iconos minimalistas integrados.
- **JavaScript (Vanilla):** Lógica reactiva para chat en vivo y actualizaciones de excepciones y turnos vía AJAX.

## Integraciones (Comunicaciones Multi-Cliente)
- **Green-API / Evolution API:** APIs profesionales para el envío y recepción de mensajes y archivos multimedia en WhatsApp.
- **pyTelegramBotAPI:** Gestión nativa de bots de Telegram para múltiples clientes.

---
Zárate System Group - Stack Tecnológico v2.5.0 SaaS
