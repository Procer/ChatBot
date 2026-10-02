#!/bin/bash
# Sube al VPS (anka.ar): interruptor "el bot responde por canal" + verificador de protocolos.
# Correr desde la raíz del repo:  bash deploy/deploy_channels_and_check.sh
set -e
KEY=~/.ssh/id_ed25519_anka
HOST=root@66.97.38.36
APP=/var/www/chatbot/ChatBot
BAK=/root/chatbot-deploy-bak-$(date +%Y%m%d-%H%M)

echo "1/5 Backup en el VPS ($BAK) ..."
ssh -i $KEY $HOST "mkdir -p $BAK && cd $APP && cp src/database/models.py src/main_saas.py templates/admin/channels.html templates/admin/layout.html $BAK/"

echo "2/5 Migración + código ..."
scp -i $KEY alembic/versions/b7d2f4a9c1e6_add_bot_reply_per_channel.py $HOST:$APP/alembic/versions/
scp -i $KEY src/main_saas.py src/protocol_check.py $HOST:$APP/src/
scp -i $KEY src/database/models.py $HOST:$APP/src/database/models.py

echo "3/5 Plantillas ..."
scp -i $KEY templates/admin/channels.html templates/admin/layout.html templates/admin/protocol_check.html $HOST:$APP/templates/admin/

echo "4/5 Aplicando migración ..."
ssh -i $KEY $HOST "cd $APP && .venv/bin/python3 -m alembic upgrade head"

echo "5/5 Reiniciando (Telegram es otro proceso que importa main_saas) ..."
ssh -i $KEY $HOST "pm2 restart chatbot-saas chatbot-telegram"
echo "Listo. Esperá ~4 minutos (arranque lento por el sync de Drive) y recargá el panel con Ctrl+F5."
