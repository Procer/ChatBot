# 📋 Reglas de Negocio y Funciones Admin (SaaS Multi-Tenant)

Este documento detalla las normas operativas que rigen el comportamiento de la plataforma ZSG-Bot-iA.

## 1. Reglas de Agendamiento de Turnos y Recordatorios

El sistema proporciona un motor de agendamiento flexible que los administradores pueden gestionar desde el panel de control (`/admin/config`):

### Recordatorios Automáticos de Turnos (Reminders)
El servicio planificador (`scheduler_reminders_loop` en `src/main_saas.py`) se ejecuta de manera continua en segundo plano y envía mensajes automáticos de alerta a los usuarios por WhatsApp o Telegram:
- **Recordatorio de 24 horas (u horas personalizadas):** Envía un mensaje con una antelación configurable (ej. 24 horas, 48 horas) utilizando una plantilla editable que admite comodines: `{nombre}`, `{fecha}`, `{hora}`, y `{motivo}`.
- **Recordatorio de 2 horas (u horas personalizadas):** Envía un segundo mensaje de aviso a los clientes con una antelación corta configurable (ej. 2 horas, 1 hora).
- **Control de Duplicados:** Cada recordatorio enviado queda registrado en la tabla `bot_audit_logs`. El planificador realiza una verificación de auditoría previa para garantizar que nunca se envíen avisos duplicados para el mismo turno.

### Excepciones y Bloqueos de Agenda
Los administradores pueden configurar fechas bloqueadas, feriados o vacaciones en el panel admin:
- **Bloqueo de Día Completo:** Si se añade una excepción sin horario de inicio ni de fin, el día queda marcado como no laborable (feriado/vacaciones) y el bot rechaza cualquier turno para esa fecha.
- **Bloqueo de Rango Horario:** Si se especifica un horario de inicio y fin (ej. de 14:00 a 16:00), solo se inhabilitan los turnos dentro de ese rango, dejando libres las horas restantes del día.

### Capacidad y Duración de Turnos
- Cada servicio o trámite en `data_knowledge` puede definir su propia duración de turno (ej. 15, 30, 60 minutos) y su propia capacidad por intervalo (cuántas personas pueden agendar en simultáneo el mismo slot).
- Si un trámite no tiene parámetros específicos, hereda la duración por defecto configurada en `adm_client_settings`.

---

## 2. Gestión de Trámites (Formularios)
- **Unicidad:** Cada trámite completado genera un registro único en la tabla `data_submissions`. No se sobrescriben datos anteriores.
- **Archivos Obligatorios:** Si el conocimiento base configurado para el trámite tiene la etiqueta `[CON_ARCHIVO]`, el bot exige el envío de la documentación complementaria (ej. foto del DNI, PDF de firmas) y adjunta dinámicamente la directiva `[SEND_FILE: topic]` para automatizar el despacho del archivo oficial de respuesta.

---

## 3. Funciones del Panel Administrativo (Multi-Tenant)

### Dashboard y Chat en Vivo
- **Historial Omnicanal:** Visualización de conversaciones en tiempo real en formato burbuja. Los administradores pueden ver los datos del perfil cargados y el historial del chat.
- **Notas de Chat:** Permite guardar notas internas asociadas al chat de un usuario para el seguimiento del equipo.
- **Pausa de IA:** Los administradores pueden pausar la IA de un chat específico con un solo clic. Mientras esté pausada, el bot no responderá y el operador humano podrá interactuar de forma directa y exclusiva.

### Configuración del Inquilino (`/admin/config`)
- Permite configurar datos de la empresa, activar/desactivar canales (WhatsApp/Telegram).
- Permite definir horarios generales y configurar los parámetros del planificador (habilitar/deshabilitar recordatorios, definir horas de offset y redactar plantillas).
- Administra el conocimiento del bot (RAG y temas), permitiendo cargar PDFs y asociarles formularios para la recolección de datos y turnos específicos.

---
Zárate System Group - Reglas de Negocio v2.5.0 SaaS
