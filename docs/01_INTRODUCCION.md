# 🤖 ZSG-Bot-iA: Ecosistema de Inteligencia Artificial

## Introducción
ZSG-Bot-iA es una plataforma avanzada de atención al cliente y automatización de procesos impulsada por Inteligencia Artificial. El sistema integra múltiples canales de comunicación (WhatsApp y Telegram) con un "cerebro" centralizado basado en modelos de lenguaje de última generación (OpenAI/Gemini) y un panel de administración premium para la supervisión y gestión de datos.

## Objetivos del Proyecto
- **Automatización Inteligente:** Reducir la carga operativa mediante agentes que comprenden el lenguaje natural.
- **Captura Estructurada de Datos:** Transformar conversaciones informales en registros estructurados para bases de datos.
- **Experiencia Premium:** Ofrecer una interfaz administrativa de vanguardia (Bento Design) para la toma de decisiones.
- **Omnicanalidad:** Mantener la coherencia del servicio en WhatsApp y Telegram de forma simultánea.

## Arquitectura de Alto Nivel
El sistema se divide en tres capas principales:
1. **Capa de Comunicación:** Evolution API (WhatsApp) y Telebot (Telegram) actúan como puentes entre el usuario y el sistema.
2. **Capa de Procesamiento (Cerebro):** Basada en **LangGraph**, que gestiona el estado de la conversación, la memoria y la lógica de decisión.
3. **Capa de Gestión (Panel Admin):** Un servidor FastAPI que sirve plantillas Jinja2 con una estética moderna para la visualización de formularios, métricas y configuración del bot.

---
© 2026 Zárate System Group
