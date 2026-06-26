-- MIGRACIÓN DE BASE DE DATOS (SQL Server) - SISTEMA DE ETIQUETAS Y ROLES
-- Siga este script para actualizar la estructura de la base de datos de ZSG-Bot-iA

-- 1. Agregar columna 'role' a bot_user_profiles
IF NOT EXISTS (SELECT * FROM sys.columns WHERE object_id = OBJECT_ID('bot_user_profiles') AND name = 'role')
BEGIN
    ALTER TABLE bot_user_profiles ADD role NVARCHAR(50) NOT NULL DEFAULT 'General';
END
GO

-- 2. Agregar columnas 'required_role' y 'tags_to_apply' a data_knowledge
IF NOT EXISTS (SELECT * FROM sys.columns WHERE object_id = OBJECT_ID('data_knowledge') AND name = 'required_role')
BEGIN
    ALTER TABLE data_knowledge ADD required_role NVARCHAR(50) NOT NULL DEFAULT 'General';
END
GO

IF NOT EXISTS (SELECT * FROM sys.columns WHERE object_id = OBJECT_ID('data_knowledge') AND name = 'tags_to_apply')
BEGIN
    ALTER TABLE data_knowledge ADD tags_to_apply NVARCHAR(512) NULL;
END
GO

-- 3. Crear tabla bot_tags
IF NOT EXISTS (SELECT * FROM sys.objects WHERE object_id = OBJECT_ID('bot_tags') AND type in (N'U'))
BEGIN
    CREATE TABLE bot_tags (
        id INT IDENTITY(1,1) PRIMARY KEY,
        client_id INT NOT NULL FOREIGN KEY REFERENCES adm_clients(id),
        name NVARCHAR(100) NOT NULL,
        color NVARCHAR(10) NOT NULL DEFAULT '#6B7280',
        is_system BIT NOT NULL DEFAULT 0,
        created_at DATETIME NOT NULL DEFAULT GETUTCDATE()
    );
END
GO

-- 4. Crear tabla de relación bot_user_tags
IF NOT EXISTS (SELECT * FROM sys.objects WHERE object_id = OBJECT_ID('bot_user_tags') AND type in (N'U'))
BEGIN
    CREATE TABLE bot_user_tags (
        id INT IDENTITY(1,1) PRIMARY KEY,
        client_id INT NOT NULL FOREIGN KEY REFERENCES adm_clients(id),
        thread_id NVARCHAR(100) NOT NULL,
        tag_id INT NOT NULL FOREIGN KEY REFERENCES bot_tags(id) ON DELETE CASCADE,
        assigned_at DATETIME NOT NULL DEFAULT GETUTCDATE(),
        assigned_by NVARCHAR(100) NOT NULL DEFAULT 'system'
    );
END
GO
