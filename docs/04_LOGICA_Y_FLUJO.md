# 🧠 Lógica y Procesamiento del Agente

El núcleo del sistema es un grafo dirigido (LangGraph) que orquesta el pensamiento del bot.

## Flujo de Conversación
1. **Entrada:** El mensaje llega vía Webhook (WA) o Polling (TG).
2. **Nodo `call_model`:** El LLM analiza el mensaje comparándolo con el historial y las herramientas disponibles.
3. **Decisión:**
    - Si es una consulta general: El bot consulta la Base de Conocimiento (RAG) y responde.
    - Si es el inicio de un trámite: El bot activa el modo "Formulario".
4. **Nodo `process_form`:** El bot solicita uno a uno los datos faltantes del formulario activo.
5. **Finalización:** Una vez capturados todos los campos (incluyendo archivos), se dispara un evento para guardar la `submission` en la DB.

## Reglas Críticas del Agente
- **Identificación Obligatoria:** El bot no responderá consultas técnicas sin antes haber identificado al usuario con Nombre y Apellido.
- **Validación de Datos:** Antes de guardar un DNI o Correo, el bot verifica que el formato sea correcto.
- **Tratamiento de Archivos:** Los archivos enviados por el usuario son descargados localmente, renombrados con un ID de registro y vinculados al formulario correspondiente.
- **Filtro de Metadatos:** En el panel administrativo, se filtran los IDs técnicos de archivos (ej. `tg_...`) para mostrar solo el texto legible al administrador.

## Memoria de Corto y Largo Plazo
- **Corto Plazo:** El historial de la sesión actual (tokens).
- **Largo Plazo:** Los checkpoints guardados en `checkpoints.sqlite`, que permiten retomar una charla iniciada hace semanas.

---
ZSG System Group - Ingeniería de Prompts & Lógica
