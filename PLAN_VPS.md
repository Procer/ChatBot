# 🚀 Plan de Acción Definitivo: Migración a SaaS (Multi-Cliente con Base de Datos Única)

Este documento define la hoja de ruta paso a paso para transformar ZSG-Bot-iA de un proyecto stand-alone a un software SaaS escalable, utilizando un único servidor (VPS) y una única base de datos SQL Server estructurada por `client_id`.

---

## 🏗️ FASE 1: Refactorización de Base de Datos (El Cimiento)
**Objetivo:** Abandonar SQLite (o bases de datos dispersas) y centralizar todo en SQL Server con seguridad por inquilino (Multi-Tenant).

1. **Implementar Sistema de Migraciones:**
   - Si el backend usa Python (FastAPI), instalar y configurar **Alembic** junto con SQLAlchemy.
   - *Por qué:* Esto permitirá hacer cambios en las tablas (agregar columnas) mediante scripts de código, manteniendo sincronizados todos los ambientes.
2. **Crear el Esquema Base Multi-Cliente:**
   - Crear el primer script de migración para generar las tablas maestras descritas en la nueva arquitectura:
     - `ADM_Clients`
     - `ADM_ClientSettings` (Feature Flags)
     - `ADM_Users`
     - `BOT_Conversations` (con `client_id`)
     - `DATA_Submissions` (con `client_id`)
3. **Refactorizar las Consultas (Código):**
   - Modificar todo el código del backend y de LangGraph para que **ninguna** consulta a la base de datos se ejecute sin el filtro `WHERE client_id = ?`.
   - Modificar la lógica del Webhook de Evolution/Telegram para que, al recibir un mensaje, identifique inmediatamente a qué `client_id` pertenece esa instancia.

---

## 🎛️ FASE 2: Sistema de "Tildes" (Feature Flags)
**Objetivo:** Poder desplegar código para todos, pero activar funciones solo para quienes queramos.

1. **Panel Súper Admin (UI):**
   - Actualizar el panel "Modo Dios" para que al editar un cliente se puedan marcar checkboxes (ej. "Activar RAG", "Exportación a PDF", "Derivación a Humano").
   - Estos tildes se guardan en `ADM_ClientSettings`.
2. **Protección Lógica en LangGraph:**
   - En el grafo (cerebro del bot), agregar validaciones antes de los nodos clave.
   - *Ejemplo:* Antes de entrar al nodo `query_rag`, verificar `if current_client.settings.feat_rag_enabled == True`. Si es falso, saltar al nodo de respuesta básica.

---

## 🌿 FASE 3: Ambientes y Repositorio (Git Flow)
**Objetivo:** Dejar de probar código en el entorno donde operan los clientes reales.

1. **Organización en GitHub:**
   - Asegurarse de que el repositorio sea privado.
   - Crear dos ramas principales (Branches):
     - `main` (Producción - Código estable).
     - `test` (Pruebas - Donde subes lo que programas en tu PC).
2. **Configuración del VPS (El Servidor Físico):**
   - Crear dos carpetas / aplicaciones corriendo en paralelo:
     - `/var/www/chatbot-test` (Escuchando en el puerto ej: 8001).
     - `/var/www/chatbot-prod` (Escuchando en el puerto ej: 8000).
3. **Archivos de Entorno (`.env`):**
   - El `.env` de `chatbot-test` apuntará a la base de datos `ZSG_Master_Test` y a instancias de WhatsApp de prueba.
   - El `.env` de `chatbot-prod` apuntará a la base de datos `ZSG_Master_Prod` y a los números reales.

---

## 🚀 FASE 4: Flujo de Despliegue (DevOps)
**Objetivo:** Que actualizar el sistema tome 1 minuto y no rompa nada.

1. **Desarrollo y Prueba Local:**
   - Programas en tu PC -> Corres migración local -> Pruebas -> Haces push a la rama `test`.
2. **Despliegue a Test:**
   - Entras al VPS en la carpeta `chatbot-test`.
   - Ejecutas `git pull origin test`.
   - Ejecutas el comando de migración (`alembic upgrade head`) para actualizar la DB de prueba.
   - Reinicias el servicio de prueba. Pruebas con tu celular.
3. **Pase a Producción:**
   - Si todo fue bien, en GitHub unes (merge) `test` hacia `main`.
   - Entras a la carpeta `chatbot-prod` en el VPS.
   - Haces `git pull origin main`.
   - Ejecutas la migración (`alembic upgrade head`) para actualizar la DB real.
   - Reinicias Producción. Todo listo.
