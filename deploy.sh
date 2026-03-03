#!/bin/bash

# Script de déploiement pour AWS EC2
# Usage: ./deploy.sh

set -e

echo "🚀 Déploiement de ShineCongo sur AWS..."

# Vérifier que nous sommes sur le serveur
if [ ! -f "/etc/systemd/system/shinecongo.service" ]; then
    echo "❌ Ce script doit être exécuté sur le serveur EC2"
    exit 1
fi

# Activer l'environnement virtuel
source /home/ubuntu/portal_shinecongo/venv/bin/activate

# Aller dans le répertoire du projet
cd /home/ubuntu/portal_shinecongo

# Pull les dernières modifications (si vous utilisez Git)
echo "📥 Mise à jour du code..."
git pull origin main || echo "⚠️  Git pull échoué, continuons..."

# Installer/mettre à jour les dépendances
echo "📦 Installation des dépendances..."
pip install -r requirements.txt

# Appliquer les migrations
echo "🗄️  Application des migrations..."
python manage.py migrate --noinput

# Collecter les fichiers statiques
echo "📁 Collecte des fichiers statiques..."
python manage.py collectstatic --noinput

# Redémarrer le service Gunicorn
echo "🔄 Redémarrage du service..."
sudo systemctl restart shinecongo

# Vérifier le statut
echo "✅ Vérification du statut..."
sudo systemctl status shinecongo --no-pager

echo "✅ Déploiement terminé!"
