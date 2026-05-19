# -*- coding: utf-8 -*-
"""
init_db_users.py
Script de migracion ONE-TIME para el sistema de Gestion de Usuarios y Permisos.
Crea las tablas admin_users, menu_items y user_permissions en settings.sqlite,
e inserta el superadmin inicial con contrasena hasheada.

Uso:
    python src/init_db_users.py

Ejecutar UNA SOLA VEZ antes de levantar el servidor con la nueva version.
"""
import os
import sys
import sqlite3
import bcrypt

# ── Rutas ─────────────────────────────────────────────────────────────────────
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
ROOT_DIR = os.path.dirname(BASE_DIR)
DB_PATH  = os.path.join(ROOT_DIR, "settings.sqlite")

# ── Configuración del superadmin inicial ─────────────────────────────────────
SUPERADMIN_USERNAME  = "superadmin"
SUPERADMIN_FULLNAME  = "Super Administrador"
SUPERADMIN_PASSWORD  = "Admin1234!"   # ← Cambiar en el primer login


def run_migration():
    print(f"[MIGRACION] Conectando a: {DB_PATH}")
    conn = sqlite3.connect(DB_PATH, timeout=30)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    # ── 1. Tabla: admin_users ─────────────────────────────────────────────────
    cur.execute("""
        CREATE TABLE IF NOT EXISTS admin_users (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            username      TEXT UNIQUE NOT NULL,
            full_name     TEXT NOT NULL,
            email         TEXT,
            password_hash TEXT NOT NULL,
            role          TEXT NOT NULL DEFAULT 'operator',
            is_active     INTEGER NOT NULL DEFAULT 1,
            created_by    INTEGER,
            created_at    TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            last_login    TIMESTAMP
        )
    """)
    print("[MIGRACION] OK Tabla admin_users lista.")

    # ── 2. Tabla: menu_items ──────────────────────────────────────────────────
    cur.execute("""
        CREATE TABLE IF NOT EXISTS menu_items (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            key        TEXT UNIQUE NOT NULL,
            label      TEXT NOT NULL,
            url        TEXT NOT NULL,
            icon       TEXT,
            section    TEXT,
            sort_order INTEGER DEFAULT 0
        )
    """)
    print("[MIGRACION] OK Tabla menu_items lista.")

    # ── 3. Tabla: user_permissions ────────────────────────────────────────────
    cur.execute("""
        CREATE TABLE IF NOT EXISTS user_permissions (
            user_id    INTEGER NOT NULL,
            menu_key   TEXT    NOT NULL,
            can_access INTEGER NOT NULL DEFAULT 0,
            PRIMARY KEY (user_id, menu_key)
        )
    """)
    print("[MIGRACION] OK Tabla user_permissions lista.")

    # ── 4. Seed: ítems de menú ────────────────────────────────────────────────
    menu_items = [
        ("dashboard",    "Dashboard",               "/admin",                "layout-dashboard", "principal", 1),
        ("history",      "Historial de Chats",      "/admin/history",        "message-square",   "principal", 2),
        ("analytics",    "Estadísticas",            "/admin/analytics",      "bar-chart-3",      "principal", 3),
        ("submissions",  "Trámites Recibidos",      "/admin/submissions",    "clipboard-list",   "gestion",   4),
        ("appointments", "Turnos",                  "/admin/appointments",   "calendar",         "gestion",   5),
        ("gaps",         "Preguntas sin Respuesta", "/admin/gaps",           "help-circle",      "gestion",   6),
        ("channels",     "Conectividad",            "/admin/channels",       "share-2",          "sistema",   7),
        ("config",       "Configuración",           "/admin/config",         "settings",         "sistema",   8),
        ("audit",        "Auditoría",               "/admin/audit",          "shield",           "sistema",   9),
        ("users",        "Gestión de Usuarios",     "/admin/users",          "users",            "sistema",   10),
        ("playground",   "Playground IA",           "/admin/playground",     "bot",              "sistema",   11),
        ("kanban",       "Kanban",                  "/admin/kanban",         "kanban",           "gestion",   12),
        ("proceedings",  "Expedientes",             "/admin/proceedings",    "file-text",        "gestion",   13),
    ]
    cur.executemany("""
        INSERT OR IGNORE INTO menu_items (key, label, url, icon, section, sort_order)
        VALUES (?, ?, ?, ?, ?, ?)
    """, menu_items)
    print(f"[MIGRACION] OK {len(menu_items)} items de menu registrados.")

    # ── 5. Seed: superadmin ───────────────────────────────────────────────────
    cur.execute("SELECT id FROM admin_users WHERE username = ?", (SUPERADMIN_USERNAME,))
    existing = cur.fetchone()

    if existing:
        print(f"[MIGRACION] AVISO: El usuario '{SUPERADMIN_USERNAME}' ya existe. No se modifica.")
    else:
        hashed = bcrypt.hashpw(SUPERADMIN_PASSWORD.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")
        cur.execute("""
            INSERT INTO admin_users (username, full_name, role, password_hash, is_active)
            VALUES (?, ?, 'superadmin', ?, 1)
        """, (SUPERADMIN_USERNAME, SUPERADMIN_FULLNAME, hashed))
        print(f"[MIGRACION] OK Superadmin '{SUPERADMIN_USERNAME}' creado con contrasena hasheada.")
        print(f"[MIGRACION] AVISO: Contrasena inicial: {SUPERADMIN_PASSWORD!r} - CAMBIALA EN EL PRIMER LOGIN.")

    conn.commit()
    conn.close()
    print("\n[MIGRACION] === MIGRACION COMPLETADA EXITOSAMENTE ===")
    print(f"[MIGRACION]    Usuario:    {SUPERADMIN_USERNAME}")
    print(f"[MIGRACION]    Contrasena: {SUPERADMIN_PASSWORD}")
    print(f"[MIGRACION]    Rol:        superadmin")


if __name__ == "__main__":
    run_migration()
