# 🚀 Plan de Acción: Despliegue en VPS y Evolución de Ambientes

Este documento es tu hoja de ruta para pasar el bot a tu VPS de muestra hoy mismo, y los pasos a seguir más adelante para tener una arquitectura profesional (Test, Producción y Multi-Cliente).

---

## FASE 1: Lo que hicimos hoy (Preparación Inmediata)

Para poder subir el proyecto al VPS "por ahora" sin romper nada ni sobreescribir datos por error mediante GitHub:

1.  **Protección de Bases de Datos (`.gitignore`):** Se modificó el archivo `.gitignore` para que **ningún** archivo `.sqlite` se suba al repositorio de GitHub. 
    *   *Por qué:* Si se subía `settings.sqlite`, al hacer `git pull` en el VPS podías pisar la configuración o perder datos de clientes reales.
2.  **Uso de Variables de Entorno:** El archivo `.env` ya estaba ignorado, lo cual es correcto.

### 👉 ¿Cómo subir al VPS AHORA MISMO?

1.  **Sube el código a GitHub:**
    ```bash
    git add .
    git commit -m "Preparación para VPS: ignorar DBs"
    git push origin main
    ```
2.  **En el VPS (Descarga de código):**
    *   Si es la primera vez: `git clone [tu-repo]`
    *   Si ya estaba clonado: `git pull origin main`
3.  **Transferencia Manual del "Cerebro" (Solo la primera vez o si cambias algo vital en local):**
    *   Usa un programa FTP (como FileZilla) o SCP para subir los siguientes archivos desde tu PC al VPS (reemplazando los del VPS):
        *   `settings.sqlite` (Contiene tus configuraciones, trámites, prompt)
        *   Carpeta `chroma_db/` (Base de datos vectorial)
        *   Carpeta `data/` (Tus PDFs y TXTs)
        *   Archivo `.env` (Configurado con IPs o dominios del VPS, no de localhost).
4.  **Reinicia el bot en el VPS:**
    *   Dependiendo de cómo lo corras (pm2, docker, etc.): `pm2 restart chatbot` (o el comando que uses).

> **Nota Crítica en el VPS:** Entra al Panel de Admin en el VPS y asegúrate de que la "Webhook Base URL" sea la IP o dominio del VPS, y haz clic en "Sincronizar Webhooks" para que Evolution/WhatsApp apunte allí.

---

## FASE 2: Separación Test vs Producción (Próximas Semanas)

Una vez que el cliente apruebe esta muestra, prepararemos el VPS definitivo con dos ambientes.

### 1. Reestructurar Carpetas
Tendremos dos copias del bot en el servidor:
*   `/var/www/chatbot-test`
*   `/var/www/chatbot-prod`

### 2. Archivos `.env` Distintos
Cada carpeta tendrá su propio archivo `.env`:
*   **Test `.env`:** Puerto 8001, conecta a la instancia de WhatsApp de "Pruebas".
*   **Prod `.env`:** Puerto 8000, conecta a la instancia de WhatsApp "Oficial".

### 3. Proxy Inverso (Nginx)
Configuraremos Nginx para redirigir el tráfico:
*   Peticiones a `test.tudominio.com` -> Puerto 8001
*   Peticiones a `app.tudominio.com` -> Puerto 8000

---

## FASE 3: Sistema Multi-Cliente (Escalabilidad)

Cuando comiences a vender el bot a distintos clientes.

### Opción Elegida (A definir)
1.  **Multi-Instancia (Docker):** Ejecutar varios contenedores en tu VPS actual, uno por cliente. Cada uno con su puerto y su base de datos aislada. (Más económico y muy organizado).
2.  **Un VPS por Cliente:** Contratar un VPS pequeño (ej. 4GB RAM) dedicado 100% para un cliente nuevo grande. (Más seguro y rendimiento aislado).

### Pasos Generales:
*   Si usamos la arquitectura actual (1 base de datos SQLite por instancia), la opción **Multi-Instancia (Docker)** es perfecta y muy rápida de desplegar. Cada cliente tendrá su propia carpeta `chroma_db` y su propio `settings.sqlite`.
*   Automatizar el despliegue con GitHub Actions para que al pushear a "main" se actualice automáticamente.
