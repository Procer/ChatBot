# 🤖 Chatbot WhatsApp (LangGraph + Evolution API + LangSmith)

Guía de implementación para un chatbot profesional de atención al cliente con capacidad RAG y persistencia de memoria.

## 📋 Checklist de Proyecto

- [ ] **Fase 1: Infraestructura Base**
    - [ ] Instalar Docker y configurar Evolution API.
    - [ ] Configurar instancia de WhatsApp en Evolution API.
    - [ ] Configurar entorno virtual de Python y dependencias (LangGraph, LangSmith, OpenAI, FastAPI).
    - [ ] Configurar variables de entorno (`.env`) para OpenAI y LangSmith.
- [ ] **Fase 2: Cerebro del Bot (LangGraph)**
    - [ ] Definir el `State` del agente (para memoria y contexto).
    - [ ] Implementar el nodo de "Decisor" (¿Conversación abierta o flujo guiado?).
    - [ ] Integrar persistencia (Checkpointer) para recordar usuarios entre días.
    - [ ] Configurar agente de Gemini (Gemini 1.5 Flash para optimizar costes).
    - [ ] **Prueba Local: Chat por consola para validar lógica.**
- [ ] **Fase 3: Conocimiento (RAG)**
    - [ ] Configurar base de datos vectorial local (Chroma o FAISS).
    - [ ] Crear script de ingesta de documentos (PDFs de información).
    - [ ] Implementar herramienta de recuperación (Retriever) dentro del grafo.
- [ ] **Fase 4: Comunicación (Evolution API)**
    - [ ] Crear un servidor Webhook (FastAPI) para recibir mensajes de WhatsApp.
    - [ ] Implementar lógica de envío de texto e imágenes/PDFs desde el bot.
    - [ ] Gestionar la recepción de archivos desde el usuario.
- [ ] **Fase 5: Observabilidad y Despliegue**
    - [ ] Activar tracing en LangSmith para depuración.
    - [ ] Pruebas de usuario y ajuste de prompts de atención al cliente.

## 📂 Estructura del Proyecto

```text
Chatbot/
├── data/               # Documentos para RAG (PDFs, etc.)
├── docker/             # Configuración de Evolution API
│   └── docker-compose.yml
├── src/                # Código fuente de Python
│   ├── agents/         # Nodos y lógica de LangGraph
│   ├── api/            # Servidor FastAPI para Webhooks
│   ├── database/       # Conexiones a BD Vectorial
│   └── main.py         # Punto de entrada principal
├── .env                # Variables de entorno
├── GEMINI.md           # Guía y checklist (este archivo)
└── requirements.txt    # Dependencias del proyecto
```

## 🛠️ Comandos Útiles

- Crear entorno virtual: `python -m venv .venv`
- Activar entorno: `.venv\Scripts\activate` (Windows)
- Instalar dependencias: `pip install -r requirements.txt`
