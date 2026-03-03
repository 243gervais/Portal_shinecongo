# Guide de Déploiement AWS - Budget Minimal (< 1$/mois)

Ce guide vous aidera à déployer votre application Django sur AWS avec un coût minimal, en utilisant le Free Tier et des services économiques.

## 🎯 Stratégie de Déploiement

### Option 1 : AWS Free Tier (GRATUIT pendant 12 mois) ⭐ RECOMMANDÉ

**Coût : 0$ pendant 12 mois, puis ~0.50-1$/mois**

#### Architecture :
- **EC2 t2.micro** : Serveur web (750h/mois gratuit pendant 12 mois)
- **S3** : Stockage des photos (5GB gratuit pendant 12 mois)
- **SQLite** : Base de données (gratuit, stockée sur EC2)
- **Route 53** : DNS (optionnel, gratuit pour 1 domaine)

#### Coûts après Free Tier :
- EC2 t2.micro : ~8.50$/mois OU utiliser t4g.nano (ARM) : ~3.50$/mois
- S3 : ~0.023$/GB/mois (très économique)
- Transfert de données : 1GB sortant gratuit/mois

### Option 2 : AWS Lightsail (3.50$/mois minimum)
Trop cher pour votre budget.

### Option 3 : Lambda + API Gateway (Complexe mais potentiellement gratuit)
Complexe à configurer pour Django, pas recommandé pour débuter.

---

## 📋 Prérequis

1. Compte AWS (créer sur aws.amazon.com)
2. Clé SSH pour accéder à EC2
3. Nom de domaine (optionnel, peut utiliser l'IP publique)

---

## 🚀 Déploiement Étape par Étape

### Étape 1 : Préparer l'application Django

#### 1.1 Installer les dépendances AWS

```bash
pip install boto3 django-storages
```

#### 1.2 Créer un fichier `requirements.txt` à la racine du projet

```bash
cd /Users/gervaismbadu/GervaisMbadu/repo/portal_shinecongo
pip freeze > requirements.txt
```

#### 1.3 Configurer S3 pour les fichiers statiques et médias

Créez un fichier `storages_backends.py` :

```python
# storages_backends.py
from storages.backends.s3boto3 import S3Boto3Storage

class StaticStorage(S3Boto3Storage):
    location = 'static'
    default_acl = 'public-read'

class MediaStorage(S3Boto3Storage):
    location = 'media'
    default_acl = 'public-read'
    file_overwrite = False
```

#### 1.4 Modifier `settings.py` pour utiliser S3

Ajoutez à la fin de `settings.py` :

```python
# AWS S3 Configuration
USE_S3 = os.getenv('USE_S3', 'False') == 'True'

if USE_S3:
    # AWS settings
    AWS_ACCESS_KEY_ID = os.getenv('AWS_ACCESS_KEY_ID')
    AWS_SECRET_ACCESS_KEY = os.getenv('AWS_SECRET_ACCESS_KEY')
    AWS_STORAGE_BUCKET_NAME = os.getenv('AWS_STORAGE_BUCKET_NAME')
    AWS_S3_REGION_NAME = os.getenv('AWS_S3_REGION_NAME', 'us-east-1')
    AWS_S3_CUSTOM_DOMAIN = f'{AWS_STORAGE_BUCKET_NAME}.s3.amazonaws.com'
    AWS_DEFAULT_ACL = 'public-read'
    
    # Static files
    STATICFILES_STORAGE = 'storages_backends.StaticStorage'
    STATIC_URL = f'https://{AWS_S3_CUSTOM_DOMAIN}/static/'
    
    # Media files
    DEFAULT_FILE_STORAGE = 'storages_backends.MediaStorage'
    MEDIA_URL = f'https://{AWS_S3_CUSTOM_DOMAIN}/media/'
    
    # S3 settings
    AWS_S3_OBJECT_PARAMETERS = {
        'CacheControl': 'max-age=86400',
    }
    AWS_LOCATION = ''
else:
    # Local development
    STATIC_URL = '/static/'
    MEDIA_URL = '/media/'
    STATIC_ROOT = os.path.join(BASE_DIR, 'staticfiles')
    MEDIA_ROOT = os.path.join(BASE_DIR, 'media')
```

#### 1.5 Ajouter `storages` à INSTALLED_APPS

```python
INSTALLED_APPS = [
    # ... autres apps
    'storages',
]
```

### Étape 2 : Créer un bucket S3 sur AWS

1. Connectez-vous à la console AWS
2. Allez dans **S3** → **Create bucket**
3. Nom du bucket : `shinecongo-media-[votre-nom-unique]` (doit être unique globalement)
4. Région : `us-east-1` (la moins chère)
5. **Désactivez** "Block all public access" (pour les fichiers publics)
6. Créez le bucket

#### Configuration CORS pour S3 :

Dans les propriétés du bucket → CORS :

```json
[
    {
        "AllowedHeaders": ["*"],
        "AllowedMethods": ["GET", "PUT", "POST", "DELETE", "HEAD"],
        "AllowedOrigins": ["*"],
        "ExposeHeaders": []
    }
]
```

### Étape 3 : Créer un utilisateur IAM pour S3

1. Allez dans **IAM** → **Users** → **Create user**
2. Nom : `shinecongo-s3-user`
3. Accès : **Programmatic access**
4. Permissions : Attachez la politique `AmazonS3FullAccess` (ou créez une politique plus restrictive)
5. **SAUVEZ** les clés d'accès (Access Key ID et Secret Access Key)

### Étape 4 : Créer une instance EC2

1. Allez dans **EC2** → **Launch Instance**
2. **Nom** : `shinecongo-server`
3. **AMI** : Ubuntu Server 22.04 LTS (Free Tier eligible)
4. **Instance type** : `t2.micro` (Free Tier)
5. **Key pair** : Créez une nouvelle clé SSH (téléchargez le fichier .pem)
6. **Network settings** :
   - Auto-assign Public IP : Enable
   - Security group : Créez un nouveau avec :
     - SSH (22) : Votre IP
     - HTTP (80) : 0.0.0.0/0
     - HTTPS (443) : 0.0.0.0/0
     - Custom TCP (8000) : 0.0.0.0/0 (pour tester)
7. **Storage** : 8GB gp3 (gratuit dans Free Tier)
8. Lancez l'instance

### Étape 5 : Configurer le serveur EC2

#### 5.1 Se connecter à l'instance

```bash
chmod 400 votre-cle.pem
ssh -i votre-cle.pem ubuntu@VOTRE_IP_PUBLIQUE
```

#### 5.2 Mettre à jour le système

```bash
sudo apt update && sudo apt upgrade -y
```

#### 5.3 Installer les dépendances

```bash
# Python et pip
sudo apt install python3-pip python3-venv -y

# Nginx
sudo apt install nginx -y

# PostgreSQL (optionnel, on utilisera SQLite pour économiser)
# sudo apt install postgresql postgresql-contrib -y

# Git
sudo apt install git -y
```

#### 5.4 Cloner votre projet

```bash
cd /home/ubuntu
git clone https://github.com/VOTRE_REPO/portal_shinecongo.git
cd portal_shinecongo
```

#### 5.5 Créer un environnement virtuel

```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
pip install gunicorn
```

#### 5.6 Configurer les variables d'environnement

```bash
nano .env
```

Ajoutez :

```bash
DEBUG=False
SECRET_KEY=votre-secret-key-tres-long-et-aleatoire
ALLOWED_HOSTS=votre-ip-publique,votre-domaine.com
USE_S3=True
AWS_ACCESS_KEY_ID=votre-access-key
AWS_SECRET_ACCESS_KEY=votre-secret-key
AWS_STORAGE_BUCKET_NAME=shinecongo-media-votre-nom
AWS_S3_REGION_NAME=us-east-1
```

#### 5.7 Modifier settings.py pour lire .env

Installez python-dotenv :

```bash
pip install python-dotenv
```

Ajoutez au début de `settings.py` :

```python
from dotenv import load_dotenv
load_dotenv()

SECRET_KEY = os.getenv('SECRET_KEY', 'django-insecure-change-me')
DEBUG = os.getenv('DEBUG', 'False') == 'True'
ALLOWED_HOSTS = os.getenv('ALLOWED_HOSTS', '').split(',')
```

#### 5.8 Collecter les fichiers statiques et les uploader vers S3

```bash
python manage.py collectstatic --noinput
```

#### 5.9 Créer un service systemd pour Gunicorn

```bash
sudo nano /etc/systemd/system/shinecongo.service
```

Contenu :

```ini
[Unit]
Description=ShineCongo Gunicorn daemon
After=network.target

[Service]
User=ubuntu
Group=www-data
WorkingDirectory=/home/ubuntu/portal_shinecongo
Environment="PATH=/home/ubuntu/portal_shinecongo/venv/bin"
ExecStart=/home/ubuntu/portal_shinecongo/venv/bin/gunicorn \
    --access-logfile - \
    --workers 3 \
    --bind unix:/home/ubuntu/portal_shinecongo/shinecongo.sock \
    shinecongo.wsgi:application

[Install]
WantedBy=multi-user.target
```

Activer et démarrer :

```bash
sudo systemctl daemon-reload
sudo systemctl enable shinecongo
sudo systemctl start shinecongo
```

#### 5.10 Configurer Nginx

```bash
sudo nano /etc/nginx/sites-available/shinecongo
```

Contenu :

```nginx
server {
    listen 80;
    server_name votre-ip-publique ou votre-domaine.com;

    client_max_body_size 100M;

    location /static/ {
        alias /home/ubuntu/portal_shinecongo/staticfiles/;
    }

    location /media/ {
        alias /home/ubuntu/portal_shinecongo/media/;
    }

    location / {
        include proxy_params;
        proxy_pass http://unix:/home/ubuntu/portal_shinecongo/shinecongo.sock;
    }
}
```

Activer le site :

```bash
sudo ln -s /etc/nginx/sites-available/shinecongo /etc/nginx/sites-enabled/
sudo nginx -t
sudo systemctl restart nginx
```

### Étape 6 : Appliquer les migrations

```bash
cd /home/ubuntu/portal_shinecongo
source venv/bin/activate
python manage.py migrate
python manage.py createsuperuser
```

### Étape 7 : Sécuriser avec SSL (optionnel mais recommandé)

Utilisez Let's Encrypt (gratuit) :

```bash
sudo apt install certbot python3-certbot-nginx -y
sudo certbot --nginx -d votre-domaine.com
```

---

## 💰 Estimation des Coûts RÉELS

### ⭐ Pendant Free Tier (12 premiers mois) :
- **EC2 t2.micro** : 0$ (750h/mois gratuit)
- **S3** : 0$ (5GB gratuit)
- **Transfert de données** : 0$ (1GB sortant gratuit)
- **Total** : **0$/mois** ✅✅✅

### ⚠️ Après Free Tier - RÉALITÉ AWS :
**Malheureusement, AWS n'a pas d'instance EC2 gratuite après le Free Tier.**

- **EC2 t2.micro** : ~8.50$/mois (minimum)
- **EC2 t4g.nano** (ARM) : ~3.50$/mois (le moins cher)
- **S3** : ~0.023$/GB/mois (très économique)
- **Transfert** : ~0.09$/GB (au-delà de 1GB gratuit)
- **Total minimum AWS** : **~3.50-4$/mois** (avec t4g.nano)

### ❌ Conclusion : AWS seul ne peut pas être < 1$/mois après Free Tier

**MAIS** voici des solutions pour rester sous 1$/mois :

---

## 🔧 Optimisations pour Réduire les Coûts

### 1. Utiliser SQLite au lieu de RDS
✅ Déjà fait - SQLite est gratuit et suffisant pour commencer

### 2. Compresser les images avant upload
Ajoutez dans votre code Django :

```python
from PIL import Image
from io import BytesIO
from django.core.files.uploadedfile import InMemoryUploadedFile
import sys

def compress_image(image_field, quality=85):
    img = Image.open(image_field)
    output = BytesIO()
    img.save(output, format='JPEG', quality=quality, optimize=True)
    output.seek(0)
    return InMemoryUploadedFile(
        output, 'ImageField', image_field.name,
        'image/jpeg', sys.getsizeof(output), None
    )
```

### 3. Utiliser CloudFront (optionnel)
Pour réduire les coûts de transfert S3, mais ajoute de la complexité.

### 4. Mettre en place une politique de lifecycle S3
Supprimer automatiquement les anciennes photos après X jours.

### 5. Utiliser Elastic IP (gratuit si attaché à une instance)
Pour avoir une IP fixe.

---

## 📊 Monitoring des Coûts

1. Activez **AWS Cost Explorer** (gratuit)
2. Configurez des **budget alerts** dans AWS Budgets
3. Surveillez régulièrement votre utilisation

---

## 🚨 Important : Sécurité

1. **Ne commitez JAMAIS** vos clés AWS dans Git
2. Utilisez `.env` et ajoutez-le à `.gitignore`
3. Limitez les permissions IAM au strict nécessaire
4. Configurez des sauvegardes régulières de votre base de données
5. Activez MFA sur votre compte AWS

---

## 📝 Checklist de Déploiement

- [ ] Créer un compte AWS
- [ ] Créer un bucket S3
- [ ] Créer un utilisateur IAM avec accès S3
- [ ] Créer une instance EC2 t2.micro
- [ ] Configurer le serveur (Python, Nginx, Gunicorn)
- [ ] Cloner et configurer l'application Django
- [ ] Configurer les variables d'environnement
- [ ] Uploader les fichiers statiques vers S3
- [ ] Configurer Nginx
- [ ] Tester l'application
- [ ] Configurer SSL (Let's Encrypt)
- [ ] Configurer les sauvegardes
- [ ] Configurer les alertes de coût

---

## 🆘 Support et Ressources

- Documentation AWS Free Tier : https://aws.amazon.com/free/
- Documentation Django sur AWS : https://docs.djangoproject.com/en/stable/howto/deployment/
- Calculatrice de coûts AWS : https://calculator.aws/

---

## 💡 Solutions pour < 1$/mois APRÈS Free Tier

### Option 1 : AWS Lambda + API Gateway (Complexe mais GRATUIT) ⭐
- **Lambda** : 1M requêtes/mois gratuit
- **API Gateway** : 1M requêtes/mois gratuit  
- **S3** : ~0.023$/GB/mois
- **Total** : **~0.10-0.50$/mois** ✅
- **Inconvénient** : Nécessite de refactoriser Django en serverless (Zappa ou Serverless Framework)

### Option 2 : VPS Low-Cost (Plus simple) ⭐⭐ RECOMMANDÉ
- **Hetzner Cloud** : 3.29€/mois (~3.50$/mois) - 1 vCPU, 2GB RAM
- **Contabo** : 3.99€/mois (~4.30$/mois) - 2 vCPU, 4GB RAM
- **DigitalOcean** : 4$/mois - 1 vCPU, 512MB RAM
- **Vultr** : 2.50$/mois - 1 vCPU, 512MB RAM
- **Oracle Cloud** : **GRATUIT pour toujours** - 2 instances ARM (4 vCPU, 24GB RAM) ✅✅✅

### Option 3 : Oracle Cloud Always Free (MEILLEURE OPTION) ⭐⭐⭐
- **2 instances ARM** : GRATUIT pour toujours (pas seulement 12 mois)
- **100GB storage** : GRATUIT
- **10TB transfert** : GRATUIT
- **Total** : **0$/mois pour toujours** ✅✅✅
- **Guide** : Voir section ci-dessous

### Option 4 : Railway.app / Render.com (Platform as a Service)
- **Railway** : 5$/mois crédit gratuit, puis pay-as-you-go
- **Render** : Gratuit avec limitations, puis ~7$/mois
- Plus simple mais plus cher

## 🎯 RECOMMANDATION FINALE

**Pour < 1$/mois :**
1. **Pendant 12 mois** : Utilisez AWS Free Tier (0$/mois)
2. **Après 12 mois** : Migrez vers **Oracle Cloud Always Free** (0$/mois pour toujours)

**Pour rester sur AWS après Free Tier :**
- Minimum : ~3.50$/mois avec t4g.nano
- Pas possible de rester sous 1$/mois avec EC2 seul

---

**Note** : Ce guide suppose que vous avez déjà une application Django fonctionnelle. Adaptez les chemins et configurations selon votre structure de projet.

---

## ❓ Réponse à votre question : "Payerai-je moins d'un dollar par mois ?"

### Réponse courte : **OUI, mais avec une stratégie en 2 étapes**

1. **Pendant 12 mois** : **0$/mois** avec AWS Free Tier ✅
2. **Après 12 mois** : Migrez vers **Oracle Cloud Always Free** = **0$/mois pour toujours** ✅

### Si vous restez sur AWS après Free Tier :
- **Minimum** : ~3.50$/mois (t4g.nano)
- **Pas possible** de rester sous 1$/mois avec EC2 seul

### Solution recommandée pour < 1$/mois :
- **Oracle Cloud Always Free** : 0$/mois (compute + storage)
- **AWS S3** (optionnel) : ~0.23$/mois pour 10GB de photos
- **Total** : **~0.23$/mois** ✅✅✅

**Voir `ORACLE_CLOUD_DEPLOYMENT.md` pour le guide complet Oracle Cloud.**
