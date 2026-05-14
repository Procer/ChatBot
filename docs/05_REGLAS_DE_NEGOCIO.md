# 📋 Reglas de Negocio y Funciones Admin

Este documento detalla las normas operativas que rigen el comportamiento de la plataforma ZSG-Bot-iA.

## 1. Reglas de Atención al Cliente
- **Horarios de Atención:** El bot conoce los horarios oficiales y puede informar al usuario si la oficina está cerrada, pero sigue operando 24/7 para recolectar datos.
- **Tono de Voz:** Profesional, servicial y empático, evitando jerga técnica.
- **Escalado:** Si el bot no encuentra respuesta en su base de conocimientos después de dos intentos, sugiere al usuario esperar a un operador humano.

## 2. Gestión de Trámites (Formularios)
- **Unicidad:** Cada trámite completado genera un registro único. No se sobrescriben datos anteriores.
- **Archivos Obligatorios:** Algunos trámites requieren fotos del DNI o constancias. El bot no da por finalizado el trámite hasta recibir los adjuntos.
- **Confirmación:** Al finalizar, el bot envía un resumen de los datos capturados al usuario para su validación final.

## 3. Funciones del Panel Administrativo
- **Dashboard:** Visualización en tiempo real de mensajes, usuarios y costos de IA.
- **Centro de Inspección:** Vista detallada (Master-Detail) de los formularios capturados.
    - Filtrado de archivos adjuntos para una lectura limpia.
    - Acceso directo a la descarga de documentación.
    - Link directo para abrir el chat con el usuario en la sección de mensajería.
- **Mensajería Omnicanal:** Historial unificado de WhatsApp y Telegram en una sola vista tipo burbujas de chat.
- **Configuración de IA:** Permite ajustar el prompt del sistema y los parámetros del modelo sin tocar código.

## 4. Seguridad y Privacidad
- **Acceso Restringido:** El panel administrativo requiere credenciales de usuario y contraseña.
- **Persistencia Local:** Los datos se almacenan en el servidor del cliente (On-Premise), garantizando la soberanía de la información.
- **Trazabilidad:** Cada acción y mensaje queda registrado con marca de tiempo.

---
ZSG System Group - Reglas de Negocio v2.5
