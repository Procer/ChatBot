-- MIGRACIÓN DE BASE DE DATOS (SQL Server)
-- Siga este script para actualizar la estructura de la base de datos de ZSG-Bot-iA

-- 1. Agregar columnas de recordatorios automáticos a adm_client_settings
IF NOT EXISTS (SELECT * FROM sys.columns WHERE object_id = OBJECT_ID('adm_client_settings') AND name = 'reminder_24h_enabled')
BEGIN
    ALTER TABLE adm_client_settings ADD reminder_24h_enabled BIT NOT NULL DEFAULT 0;
    ALTER TABLE adm_client_settings ADD reminder_24h_template NVARCHAR(MAX) NULL;
    ALTER TABLE adm_client_settings ADD reminder_2h_enabled BIT NOT NULL DEFAULT 0;
    ALTER TABLE adm_client_settings ADD reminder_2h_template NVARCHAR(MAX) NULL;
END
GO

-- 2. Agregar columna scheduling_capacity a data_knowledge
IF NOT EXISTS (SELECT * FROM sys.columns WHERE object_id = OBJECT_ID('data_knowledge') AND name = 'scheduling_capacity')
BEGIN
    ALTER TABLE data_knowledge ADD scheduling_capacity INT NULL DEFAULT 1;
END
GO

-- 3. Crear tabla de excepciones horarias (data_scheduling_exceptions)
IF NOT EXISTS (SELECT * FROM sys.objects WHERE object_id = OBJECT_ID('data_scheduling_exceptions') AND type in (N'U'))
BEGIN
    CREATE TABLE data_scheduling_exceptions (
        id INT IDENTITY(1,1) PRIMARY KEY,
        client_id INT NOT NULL FOREIGN KEY REFERENCES adm_clients(id),
        date NVARCHAR(20) NOT NULL,
        start_time NVARCHAR(20) NULL,
        end_time NVARCHAR(20) NULL,
        description NVARCHAR(255) NULL,
        created_at DATETIME NOT NULL DEFAULT GETUTCDATE()
    );
END
GO
