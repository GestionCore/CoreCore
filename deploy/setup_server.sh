#!/usr/bin/env bash
# Setup inicial de CoreLux en un VPS Ubuntu recién creado (Hostinger,
# Vultr, o cualquier VPS con Ubuntu 22.04/24.04). Correr UNA sola vez,
# como root, apenas se tiene acceso SSH al servidor:
#
#   bash setup_server.sh
#
# Después de correrlo todavía falta a mano: crear el .env real y
# arrancar los servicios (el script te lo recuerda al final).
set -euo pipefail

REPO_URL="git@github.com:TU_USUARIO/TU_REPO.git"   # <-- completar antes de correr
DOMINIO="tudominio.com"                             # <-- completar antes de correr
APP_DIR="/opt/corelux"
APP_USER="corelux"

echo "== Actualizando el sistema =="
apt update && apt upgrade -y

echo "== Instalando dependencias =="
apt install -y python3 python3-venv python3-pip nginx redis-server git ufw certbot python3-certbot-nginx

echo "== Usuario dedicado (la app no corre como root) =="
id -u "$APP_USER" &>/dev/null || useradd -m -s /bin/bash "$APP_USER"

echo "== Clonando el repo =="
mkdir -p "$APP_DIR"
chown "$APP_USER":"$APP_USER" "$APP_DIR"
if [ -d "$APP_DIR/.git" ]; then
    sudo -u "$APP_USER" git -C "$APP_DIR" pull
else
    sudo -u "$APP_USER" git clone "$REPO_URL" "$APP_DIR"
fi

echo "== Entorno virtual + dependencias =="
sudo -u "$APP_USER" python3 -m venv "$APP_DIR/venv"
sudo -u "$APP_USER" "$APP_DIR/venv/bin/pip" install --upgrade pip
sudo -u "$APP_USER" "$APP_DIR/venv/bin/pip" install -r "$APP_DIR/requirements.txt"

echo "== Servicios systemd =="
cp "$APP_DIR/deploy/systemd/"*.service /etc/systemd/system/
systemctl daemon-reload
systemctl enable corelux corelux-celery-worker corelux-celery-beat redis-server
systemctl start redis-server

echo "== nginx =="
cp "$APP_DIR/deploy/nginx/corelux.conf" /etc/nginx/sites-available/corelux
sed -i "s/TU-DOMINIO.com/$DOMINIO/g" /etc/nginx/sites-available/corelux
ln -sf /etc/nginx/sites-available/corelux /etc/nginx/sites-enabled/corelux
rm -f /etc/nginx/sites-enabled/default
nginx -t && systemctl restart nginx

echo "== Firewall =="
ufw allow OpenSSH
ufw allow "Nginx Full"
ufw --force enable

echo "=========================================================="
echo "Setup base listo. Falta a mano, en este orden:"
echo "1) Crear $APP_DIR/.env con las credenciales reales (ver .env.example)"
echo "   chown $APP_USER:$APP_USER $APP_DIR/.env && chmod 600 $APP_DIR/.env"
echo "2) systemctl start corelux corelux-celery-worker corelux-celery-beat"
echo "3) Verificar que el DNS de $DOMINIO ya apunte a este servidor"
echo "4) Recién ahí: certbot --nginx -d $DOMINIO -d www.$DOMINIO"
echo "5) Actualizar MELI_REDIRECT_URI en .env y en MeLi Developers con"
echo "   el dominio real (ya no ngrok), y reiniciar corelux"
echo "=========================================================="
