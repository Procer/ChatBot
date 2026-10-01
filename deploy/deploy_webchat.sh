#!/bin/bash
# Sube los cambios del chat web al VPS (anka.ar) y reinicia. Correr desde la raíz del repo:  bash deploy/deploy_webchat.sh
set -e
KEY=~/.ssh/id_ed25519_anka
HOST=root@66.97.38.36
APP=/var/www/chatbot/ChatBot

echo "1/4 Migración nueva (columnas) ..."
scp -i $KEY alembic/versions/a3c9e5b1d7f4_add_web_attention_and_pending_notice.py $HOST:$APP/alembic/versions/
ssh -i $KEY $HOST "cd $APP && .venv/bin/python3 -m alembic upgrade head"

echo "2/4 Código ..."
scp -i $KEY src/main_saas.py src/web_results.py src/web_metrics.py $HOST:$APP/src/
scp -i $KEY src/database/models.py $HOST:$APP/src/database/models.py
scp -i $KEY src/agents/graph_saas.py $HOST:$APP/src/agents/graph_saas.py

echo "3/4 Plantillas ..."
scp -i $KEY templates/admin/layout.html templates/admin/web_chat.html $HOST:$APP/templates/admin/
scp -i $KEY templates/public/web_chat.html $HOST:$APP/templates/public/web_chat.html

echo "4/4 Reiniciando ..."
ssh -i $KEY $HOST "pm2 restart chatbot-saas"
echo "Listo. Esperá 1-2 minutos y recargá el panel (Ctrl+F5)."
