# 🚀 Guía de Despliegue y Sincronización (Chatbot)

Para que tu bot siempre responda correctamente y no pierdas cambios, sigue este método.

## 1. El "Método Siempre Fiel" (Git)

Es la mejor forma de pasar el **CÓDIGO**.
1.  **En tu PC (Laragon):**
    ```bash
    git add .
    git commit -m "Mejoras en el cerebro y correcciones"
    git push origin main
    ```
2.  **En el VPS:**
    ```bash
    cd /ruta/a/tu/proyecto
    git pull
    pm2 restart chatbot  # Reiniciar para que tome cambios en src/
    ```

## 2. Sincronización del "Cerebro" (Ajustes y Conocimiento)

Si configuraste cosas en el Admin **local** y quieres que pasen al **VPS**, debes subir los archivos de base de datos. 

> [!IMPORTANT]
> **Cuidado:** Si subes la base de datos de local al VPS, borrarás lo que se haya registrado en el VPS (como chats de clientes reales). 

**Archivos a subir si quieres "clonar" el cerebro:**
*   `settings.sqlite`: Contiene el Prompt, Trámites y Conocimiento (Texto).
*   `chroma_db/`: (Carpeta) Contiene el conocimiento de los PDFs.
*   `data/`: (Carpeta) Contiene los archivos físicos (PDF/TXT).

---

## 3. Checklist Post-Despliegue (¡REVISAR SIEMPRE!)

Cada vez que subas cambios al VPS, entra al panel de administración del VPS y verifica:

1.  **Cerebro (Configuración):** Verifica que el Prompt de Sistema sea el correcto.
2.  **Canales (Webhook):**
    *   Asegúrate de que la **Webhook Base URL** apunte a tu dominio/IP del VPS y NO a localhost.
    *   Dale al botón **"Sincronizar Webhooks"** en el panel para avisarle a WhatsApp de la nueva URL.
3.  **Estado de Conexión:** Verifica que la instancia de WhatsApp diga "Connected" (Open).

---

## 4. Script de Diagnóstico Rápido

He creado `src/diagnostico_vps.py`. Si notas que el bot no responde bien, ejecútalo en el VPS:
```bash
python src/diagnostico_vps.py
```
Esto te dirá exactamente qué está leyendo el bot de la base de datos sin necesidad de usar WhatsApp.
