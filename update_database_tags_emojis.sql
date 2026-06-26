-- Cambiar el tipo de dato a NVARCHAR para soportar Emojis (UTF-16)
ALTER TABLE bot_tags ALTER COLUMN name NVARCHAR(100) NOT NULL;

-- Corregir los tags del sistema que ya quedaron guardados con '?'
UPDATE bot_tags SET name = '👋 Nuevo Contacto' WHERE name LIKE '%Nuevo Contacto%';
UPDATE bot_tags SET name = '📱 Canal: WhatsApp' WHERE name LIKE '%Canal: WhatsApp%';
UPDATE bot_tags SET name = '💬 Canal: Telegram' WHERE name LIKE '%Canal: Telegram%';
UPDATE bot_tags SET name = '⚡ Activo Reciente' WHERE name LIKE '%Activo Reciente%';
UPDATE bot_tags SET name = '🗓️ Turno Agendado' WHERE name LIKE '%Turno Agendado%';
UPDATE bot_tags SET name = '❌ Turno Cancelado' WHERE name LIKE '%Turno Cancelado%';
UPDATE bot_tags SET name = '📝 Trámite Iniciado' WHERE name LIKE '%Trámite Iniciado%';
UPDATE bot_tags SET name = '🎓 Trámite Completado' WHERE name LIKE '%Trámite Completado%';
UPDATE bot_tags SET name = '⚠️ Sin Responder' WHERE name LIKE '%Sin Responder%';
UPDATE bot_tags SET name = '👤 Humano Requerido' WHERE name LIKE '%Humano Requerido%';
