-- MIGRACIÓN DE BASE DE DATOS (SQL Server)
-- Agregar columnas de configuración de canales (WhatsApp / Telegram) a adm_client_settings

IF NOT EXISTS (SELECT * FROM sys.columns WHERE object_id = OBJECT_ID('adm_client_settings') AND name = 'webhook_base_url')
BEGIN
    ALTER TABLE adm_client_settings ADD webhook_base_url NVARCHAR(255) NULL;
END
GO

IF NOT EXISTS (SELECT * FROM sys.columns WHERE object_id = OBJECT_ID('adm_client_settings') AND name = 'whatsapp_enabled')
BEGIN
    ALTER TABLE adm_client_settings ADD whatsapp_enabled BIT NOT NULL DEFAULT 1;
END
GO

IF NOT EXISTS (SELECT * FROM sys.columns WHERE object_id = OBJECT_ID('adm_client_settings') AND name = 'telegram_enabled')
BEGIN
    ALTER TABLE adm_client_settings ADD telegram_enabled BIT NOT NULL DEFAULT 0;
END
GO

IF NOT EXISTS (SELECT * FROM sys.columns WHERE object_id = OBJECT_ID('adm_client_settings') AND name = 'telegram_token')
BEGIN
    ALTER TABLE adm_client_settings ADD telegram_token NVARCHAR(255) NULL;
END
GO
