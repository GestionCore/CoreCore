#!/usr/bin/env bash
# Redeploy de CoreLux — correr como root en el servidor después de cada
# `git push` a main. Uso:
#
#   bash /opt/corelux/deploy/deploy.sh
#
# Si esta tanda trae una migración nueva en migrations/, correla a
# mano en el SQL Editor de Supabase ANTES de aceptar el prompt de acá
# abajo — el script no la corre solo (no tiene forma de saber si ya
# se aplicó o no, y correrla dos veces por accidente es peor que
# preguntar).
set -euo pipefail
cd /opt/corelux

echo "== git pull =="
sudo -u corelux git pull origin main

echo "== dependencias =="
sudo -u corelux venv/bin/pip install -r requirements.txt --quiet

echo ""
echo "¿Hay migraciones nuevas en migrations/ desde el último deploy?"
echo "Si las hay: ¿ya las corriste en el SQL Editor de Supabase?"
read -p "Confirmar para continuar [s/N]: " confirmar
if [[ "$confirmar" != "s" && "$confirmar" != "S" ]]; then
    echo "Deploy cancelado."
    exit 1
fi

echo "== Reiniciando servicios =="
systemctl restart corelux corelux-celery-worker corelux-celery-beat

echo "== Estado =="
systemctl --no-pager status corelux --lines=5
