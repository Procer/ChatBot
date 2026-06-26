# 🤖 ZSG-Bot-iA | Guía de Referencia para IA

> [!IMPORTANT]
> Toda la información técnica, lógica de negocio, arquitectura y manuales del sistema se encuentran centralizados en la carpeta **`/docs`**.

---

## ⚡ ESTADO ACTUAL DEL PROYECTO (v2.5.0 — Multi-Tenant SaaS)

**Arquitectura actual:** El sistema ha sido migrado de un bot de instancia única (SQLite) a una plataforma **Multi-Tenant SaaS** centralizada en **SQL Server**. Toda la lógica nueva vive en los archivos `_saas.py`. Los archivos "legacy" (`main.py`, `graph.py`, etc.) existen aún como referencia histórica pero **NO son el sistema activo**.

### Sistema Activo (Producción Local):
| Componente | Archivo Activo | Descripción |
|---|---|---|
| **Servidor Principal** | `src/main_saas.py` | FastAPI en Puerto **8001**. Gestiona Login, Dashboard, Webhook Multi-Cliente y Panel Súper Admin. |
| **Cerebro IA (LangGraph)** | `src/agents/graph_saas.py` | Grafo de estados que transporta `client_id` en todo el flujo. Personalidad dinámica por cliente. |
| **Motor de Analíticas** | `src/database/analytics_engine_saas.py` | Lee/escribe en SQL Server filtrando por `client_id`. |
| **Motor de Formularios** | `src/database/forms_saas.py` | Guarda Trámites y Expedientes en SQL Server. Conecta Google Sheets por cliente. |
| **Modelos ORM** | `src/database/models.py` | Esquema SQLAlchemy completo. 3 Capas: Administración, Operación, Datos. |
| **Sesión de DB** | `src/database/session.py` | Fábrica de conexiones SQLAlchemy a SQL Server (Docker local). |

### Rutas del Servidor SaaS (Puerto 8001):
| Ruta | Descripción |
|---|---|
| `GET /` | Redirige a `/admin` |
| `GET /admin/login` | Pantalla de Login |
| `POST /acceso` | Procesa credenciales |
| `GET /admin` | Dashboard del cliente logueado (protegido) |
| `GET /super-admin` | Panel Modo Dios para gestionar todos los inquilinos |
| `POST /api/superadmin/clients` | API: Crear nuevo cliente |
| `GET /api/superadmin/clients/{id}` | API: Obtener datos de un cliente |
| `PUT /api/superadmin/clients/{id}/settings` | API: Actualizar Feature Flags y credenciales |
| `POST /webhook/{client_slug}/greenapi` | Webhook WhatsApp Multi-Cliente |

---

## 📂 Directorio de Documentación Maestra

Para comprender, mantener o escalar este proyecto, consulta los siguientes archivos en orden:

1. **[01_INTRODUCCION.md](docs/01_INTRODUCCION.md)**: Visión general, objetivos y arquitectura de alto nivel.
2. **[02_TECNOLOGIA.md](docs/02_TECNOLOGIA.md)**: Detalle del Stack Tecnológico (FastAPI, LangGraph, SQLAlchemy, SQL Server).
3. **[03_BASES_DE_DATOS.md](docs/03_BASES_DE_DATOS.md)**: Estructura de tablas y persistencia de datos. **(Actualizar: Ahora es SQL Server con Alembic).**
4. **[04_LOGICA_Y_FLUJO.md](docs/04_LOGICA_Y_FLUJO.md)**: Funcionamiento del cerebro del bot y nodos de decisión.
5. **[05_REGLAS_DE_NEGOCIO.md](docs/05_REGLAS_DE_NEGOCIO.md)**: Normas operativas y funciones del Panel Admin.
6. **[06_SUPER_ADMIN.md](docs/06_SUPER_ADMIN.md)**: Manual del Panel Súper Admin (Modo Dios) para gestión de inquilinos.

---

## 🗄️ Base de Datos (SQL Server via Docker)

- **Motor:** SQL Server en Docker (Puerto 1434 local, credenciales en `.env`)
- **Migraciones:** Alembic (`alembic upgrade head`)
- **Tablas Clave:**
  - `adm_clients` — Registro de empresas (inquilinos)
  - `adm_client_settings` — Feature Flags y credenciales por cliente
  - `adm_users` — Usuarios del panel (role: `client_admin` o `superadmin`)
  - `bot_messages` — Historial de conversaciones
  - `data_submissions` — Trámites/Formularios completados
  - `data_knowledge` — Base de conocimiento por cliente
- **Checkpoints LangGraph:** Sigue en `checkpoints.sqlite` local (intencional, no migrar)

---

## 🌿 Git Flow

- **Rama `main`:** Producción. Código estable.
- **Rama `test`:** Desarrollo activo. Aquí viven los cambios actuales.
- **Arrancar el sistema nuevo:** Doble clic en `run_saas.bat`

---

## 🚀 Instrucción Crítica para el Agente AI

Cuando trabajes en este repositorio:
- **USAR SIEMPRE** los archivos `_saas.py` como referencia. Los archivos sin ese sufijo son **legacy**.
- **NO** crear nuevos scripts de actualización de SQLite (`update_*.py`). Usar **Alembic** para cambios de esquema.
- **SIEMPRE** filtrar consultas por `client_id`. Ninguna consulta debe ser sin ese filtro.
- **MANTÉN** la estética premium (Bento Design / Glassmorphism / TailwindCSS Dark) en los templates.
- El servidor SaaS corre en **puerto 8001**. El legado corre en **8000**.

---

© 2026 Zárate System Group | v2.5.0 — SaaS Multi-Tenant
