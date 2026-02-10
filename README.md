# Shine Congo – Portail Opérations Employés

Application web interne pour la gestion des opérations des employés de Shine Congo, avec système de pointage par QR code, gestion des lavages de véhicules et signalement de problèmes.

## 🚀 Fonctionnalités

### Pour les Employés
- ✅ Pointage entrée/sortie via QR code du jour
- ✅ Ajout de lavages avec photos (avant/après)
- ✅ Signalement de problèmes (matériel, eau, sécurité, etc.)
- ✅ Consultation de l'historique (pointages, lavages, problèmes)
- ✅ Interface mobile-first optimisée pour smartphones

### Pour les Managers
- ✅ Dashboard avec statistiques du jour par site
- ✅ Génération et impression des QR codes du jour
- ✅ Visualisation des pointages avec filtres
- ✅ Correction des pointages avec motif obligatoire + audit
- ✅ Consultation des lavages avec totaux financiers
- ✅ Gestion des problèmes signalés (statuts: Ouvert/En cours/Résolu)

### Pour les Administrateurs
- ✅ Accès complet à tous les sites
- ✅ Gestion des utilisateurs et profils
- ✅ Interface Django Admin complète
- ✅ Journal d'audit de toutes les actions

## 📋 Prérequis

- Python 3.8 ou supérieur
- pip (gestionnaire de paquets Python)
- Accès à une base de données (SQLite par défaut, PostgreSQL recommandé en production)

## 🛠️ Installation Locale

### 1. Cloner le dépôt

```bash
git clone <url-du-repo>
cd portal_shinecongo
```

### 2. Créer un environnement virtuel

```bash
python3 -m venv venv
source venv/bin/activate  # Sur Windows: venv\Scripts\activate
```

### 3. Installer les dépendances

```bash
pip install -r requirements.txt
```

### 4. Configurer les variables d'environnement

Créer un fichier `.env` à la racine du projet :

```env
DJANGO_SECRET_KEY=votre-secret-key-tres-securise
DJANGO_SECRET_QR=votre-secret-qr-tres-securise
DEBUG=True
```

**⚠️ Important:** En production, utilisez des secrets forts et ne commitez jamais le fichier `.env` !

### 5. Appliquer les migrations

```bash
python manage.py migrate
```

### 6. Créer un superutilisateur

```bash
python manage.py createsuperuser
```

Suivez les instructions pour créer votre compte administrateur.

### 7. Lancer le serveur de développement

**⚠️ Important:** Assurez-vous d'avoir activé l'environnement virtuel avant de lancer le serveur !

```bash
# Activer l'environnement virtuel (si ce n'est pas déjà fait)
source venv/bin/activate  # Sur Windows: venv\Scripts\activate

# Lancer le serveur
python manage.py runserver
```

**Alternative:** Utilisez le script fourni qui active automatiquement l'environnement virtuel :

```bash
./runserver.sh
```

L'application sera accessible à l'adresse : `http://127.0.0.1:8000`

## 📱 Utilisation

### Connexion

1. Accédez à `http://127.0.0.1:8000/login/`
2. Connectez-vous avec vos identifiants

### Configuration initiale (Admin)

1. Connectez-vous en tant qu'administrateur
2. Créez des **Sites** (ex: Station Texaco Gombe, Station Total Lemba)
3. Créez des **Utilisateurs** et assignez-les :
   - Un **Rôle** (Employé, Manager, Admin)
   - Un **Site** (sauf pour Admin qui voit tous les sites)

### Pour les Managers

1. Accédez au dashboard manager
2. Pour chaque site, cliquez sur "QR du jour" pour générer/afficher le QR code
3. Imprimez le QR code et placez-le à l'entrée du site
4. Le QR code change automatiquement chaque jour

### Pour les Employés

1. Scannez le QR code du jour avec votre téléphone pour pointer l'entrée
2. Ajoutez les lavages effectués avec photos
3. En fin de journée, scannez à nouveau le QR pour pointer la sortie et confirmer le nombre de lavages

## 🌐 Déploiement sur Serveur (IP sans domaine)

### Option 1: Déploiement avec Gunicorn + Nginx

#### 1. Sur le serveur, installer les dépendances système

```bash
sudo apt update
sudo apt install python3-pip python3-venv nginx
```

#### 2. Cloner le projet sur le serveur

```bash
cd /opt  # ou un autre répertoire approprié
git clone <url-du-repo> portal_shinecongo
cd portal_shinecongo
```

#### 3. Créer l'environnement virtuel et installer les dépendances

```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

#### 4. Configurer les variables d'environnement

```bash
nano .env
```

Ajoutez :
```env
DJANGO_SECRET_KEY=<secret-key-production>
DJANGO_SECRET_QR=<secret-qr-production>
DEBUG=False
ALLOWED_HOSTS=votre-ip-serveur,127.0.0.1
```

#### 5. Modifier `settings.py` pour la production

Ajoutez dans `shinecongo/settings.py` :

```python
import os
from dotenv import load_dotenv

load_dotenv()

SECRET_KEY = os.getenv("DJANGO_SECRET_KEY", "fallback-key")
DEBUG = os.getenv("DEBUG", "False") == "True"
ALLOWED_HOSTS = os.getenv("ALLOWED_HOSTS", "").split(",") if os.getenv("ALLOWED_HOSTS") else []
```

#### 6. Appliquer les migrations et collecter les fichiers statiques

```bash
python manage.py migrate
python manage.py collectstatic --noinput
```

#### 7. Créer un fichier de service systemd pour Gunicorn

```bash
sudo nano /etc/systemd/system/shinecongo.service
```

Contenu :
```ini
[Unit]
Description=Shine Congo Gunicorn daemon
After=network.target

[Service]
User=www-data
Group=www-data
WorkingDirectory=/opt/portal_shinecongo
Environment="PATH=/opt/portal_shinecongo/venv/bin"
ExecStart=/opt/portal_shinecongo/venv/bin/gunicorn --workers 3 --bind unix:/opt/portal_shinecongo/shinecongo.sock shinecongo.wsgi:application

[Install]
WantedBy=multi-user.target
```

#### 8. Configurer Nginx

```bash
sudo nano /etc/nginx/sites-available/shinecongo
```

Contenu :
```nginx
server {
    listen 80;
    server_name votre-ip-serveur;

    location /static/ {
        alias /opt/portal_shinecongo/staticfiles/;
    }

    location /media/ {
        alias /opt/portal_shinecongo/media/;
    }

    location / {
        include proxy_params;
        proxy_pass http://unix:/opt/portal_shinecongo/shinecongo.sock;
    }
}
```

Activer le site :
```bash
sudo ln -s /etc/nginx/sites-available/shinecongo /etc/nginx/sites-enabled/
sudo nginx -t
sudo systemctl restart nginx
```

#### 9. Démarrer le service Gunicorn

```bash
sudo systemctl start shinecongo
sudo systemctl enable shinecongo
```

### Option 2: Déploiement simple avec Gunicorn (sans Nginx)

Pour un déploiement rapide sans Nginx :

```bash
# Dans le répertoire du projet
source venv/bin/activate
gunicorn --bind 0.0.0.0:8000 shinecongo.wsgi:application
```

⚠️ **Note:** Cette méthode n'est pas recommandée pour la production car elle ne sert pas les fichiers statiques efficacement.

## 🔐 Sécurité

### Variables d'environnement importantes

- `DJANGO_SECRET_KEY`: Clé secrète Django (générer avec `python -c 'from django.core.management.utils import get_random_secret_key; print(get_random_secret_key())'`)
- `DJANGO_SECRET_QR`: Clé secrète pour la génération des tokens QR (utiliser une chaîne aléatoire forte)
- `DEBUG`: Toujours `False` en production
- `ALLOWED_HOSTS`: Liste des domaines/IP autorisés (séparés par des virgules)

### Recommandations de sécurité

1. ✅ Utiliser HTTPS en production (certificat Let's Encrypt gratuit)
2. ✅ Changer les secrets par défaut
3. ✅ Configurer un pare-feu (UFW)
4. ✅ Sauvegarder régulièrement la base de données
5. ✅ Limiter l'accès SSH au serveur

## 📁 Structure du Projet

```
portal_shinecongo/
├── comptes/          # Gestion des utilisateurs et profils
├── sites/            # Modèle des sites/locations
├── pointage/         # Système de pointage QR + ShiftDay
├── lavages/          # Gestion des lavages de véhicules
├── problemes/        # Signalement de problèmes
├── audit/            # Journal d'audit
├── templates/        # Templates HTML
├── static/           # Fichiers statiques (CSS, JS, images)
├── media/            # Fichiers uploadés (photos)
└── shinecongo/       # Configuration Django
```

## 🔧 Commandes Utiles

### Créer un superutilisateur
```bash
python manage.py createsuperuser
```

### Appliquer les migrations
```bash
python manage.py migrate
```

### Créer de nouvelles migrations
```bash
python manage.py makemigrations
```

### Collecter les fichiers statiques
```bash
python manage.py collectstatic
```

### Accéder au shell Django
```bash
python manage.py shell
```

## 📞 Support

Pour toute question ou problème, contactez l'équipe technique.

## 📄 Licence

Propriétaire - Shine Congo

---

**Version:** 1.0.0  
**Dernière mise à jour:** 2025
