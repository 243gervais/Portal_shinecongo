#!/bin/bash

# Script de configuration initiale pour AWS EC2
# À exécuter une seule fois après avoir créé l'instance EC2

set -e

echo "🔧 Configuration initiale de ShineCongo sur AWS EC2..."

# Mettre à jour le système
echo "📦 Mise à jour du système..."
sudo apt update && sudo apt upgrade -y

# Installer les dépendances système
echo "📦 Installation des dépendances..."
sudo apt install -y python3-pip python3-venv python3-dev nginx git nodejs npm

# Créer le répertoire de l'application
echo "📁 Création du répertoire..."
mkdir -p /home/ubuntu/portal_shinecongo
cd /home/ubuntu/portal_shinecongo

# Cloner le projet (remplacez par votre repo Git)
echo "📥 Clonage du projet..."
# git clone https://github.com/VOTRE_REPO/portal_shinecongo.git .

# Créer l'environnement virtuel
echo "🐍 Création de l'environnement virtuel..."
python3 -m venv venv
source venv/bin/activate

# Installer les dépendances Python
echo "📦 Installation des dépendances Python..."
pip install --upgrade pip
pip install -r requirements.txt

# Créer le fichier .env
echo "⚙️  Configuration des variables d'environnement..."
if [ ! -f .env ]; then
    cat > .env << EOF
# Django Settings
SECRET_KEY=$(python3 -c 'from django.core.management.utils import get_random_secret_key; print(get_random_secret_key())')
DEBUG=False
ALLOWED_HOSTS=localhost,127.0.0.1

# AWS S3 Configuration
USE_S3=True
AWS_ACCESS_KEY_ID=votre-access-key-id
AWS_SECRET_ACCESS_KEY=votre-secret-access-key
AWS_STORAGE_BUCKET_NAME=votre-bucket-name
AWS_S3_REGION_NAME=us-east-1

# QR Code Security
DJANGO_SECRET_QR=$(python3 -c 'from django.core.management.utils import get_random_secret_key; print(get_random_secret_key())')
EOF
    echo "✅ Fichier .env créé. Veuillez le modifier avec vos vraies valeurs AWS."
else
    echo "⚠️  Le fichier .env existe déjà."
fi

# Appliquer les migrations
echo "🗄️  Application des migrations..."
python manage.py migrate

# Créer le superutilisateur (interactif)
echo "👤 Création du superutilisateur..."
python manage.py createsuperuser || echo "⚠️  Superutilisateur non créé (peut-être existe déjà)"

# Collecter les fichiers statiques
echo "📁 Collecte des fichiers statiques..."
(cd frontend && npm ci && npm run build)
python manage.py collectstatic --noinput

# Créer le service systemd pour Gunicorn
echo "🔧 Configuration du service Gunicorn..."
sudo tee /etc/systemd/system/shinecongo.service > /dev/null << EOF
[Unit]
Description=ShineCongo Gunicorn daemon
After=network.target

[Service]
User=ubuntu
Group=www-data
WorkingDirectory=/home/ubuntu/portal_shinecongo
Environment="PATH=/home/ubuntu/portal_shinecongo/venv/bin"
ExecStart=/home/ubuntu/portal_shinecongo/venv/bin/gunicorn \\
    --access-logfile - \\
    --workers 3 \\
    --bind unix:/home/ubuntu/portal_shinecongo/shinecongo.sock \\
    shinecongo.wsgi:application

[Install]
WantedBy=multi-user.target
EOF

# Activer et démarrer le service
echo "🚀 Démarrage du service Gunicorn..."
sudo systemctl daemon-reload
sudo systemctl enable shinecongo
sudo systemctl start shinecongo

# Configurer Nginx
echo "🌐 Configuration de Nginx..."
PUBLIC_IP=$(curl -s http://169.254.169.254/latest/meta-data/public-ipv4 || echo "localhost")

sudo tee /etc/nginx/sites-available/shinecongo > /dev/null << EOF
server {
    listen 80;
    server_name $PUBLIC_IP;

    client_max_body_size 100M;
    gzip on;
    gzip_comp_level 5;
    gzip_min_length 256;
    gzip_types text/plain text/css application/json application/javascript text/xml application/xml image/svg+xml;

    proxy_set_header Host \$host;
    proxy_set_header X-Real-IP \$remote_addr;
    proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto \$scheme;

    location /static/ {
        alias /home/ubuntu/portal_shinecongo/staticfiles/;
        expires 30d;
        add_header Cache-Control "public";
    }

    location /media/ {
        alias /home/ubuntu/portal_shinecongo/media/;
        expires 7d;
        add_header Cache-Control "public";
    }

    location /api/ {
        include proxy_params;
        proxy_pass http://unix:/home/ubuntu/portal_shinecongo/shinecongo.sock;
    }

    location /admin/ {
        include proxy_params;
        proxy_pass http://unix:/home/ubuntu/portal_shinecongo/shinecongo.sock;
    }

    location / {
        include proxy_params;
        proxy_pass http://unix:/home/ubuntu/portal_shinecongo/shinecongo.sock;
    }
}
EOF

# Activer le site Nginx
sudo ln -sf /etc/nginx/sites-available/shinecongo /etc/nginx/sites-enabled/
sudo rm -f /etc/nginx/sites-enabled/default
sudo nginx -t
sudo systemctl restart nginx

echo ""
echo "✅ Configuration terminée!"
echo ""
echo "📝 Prochaines étapes:"
echo "1. Modifiez /home/ubuntu/portal_shinecongo/.env avec vos vraies clés AWS"
echo "2. Redémarrez le service: sudo systemctl restart shinecongo"
echo "3. Vérifiez les logs: sudo journalctl -u shinecongo -f"
echo "4. Accédez à votre application: http://$PUBLIC_IP"
echo ""
echo "🔒 Pour SSL (Let's Encrypt):"
echo "   sudo apt install certbot python3-certbot-nginx"
echo "   sudo certbot --nginx -d votre-domaine.com"
