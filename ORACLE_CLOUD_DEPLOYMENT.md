# Déploiement sur Oracle Cloud - GRATUIT pour toujours

Oracle Cloud offre un **tier Always Free** qui inclut :
- **2 instances ARM** (4 vCPU, 24GB RAM chacune) - GRATUIT pour toujours
- **100GB storage** - GRATUIT
- **10TB transfert de données** - GRATUIT
- **Total : 0$/mois pour toujours** ✅

## 🚀 Guide de Déploiement Oracle Cloud

### Étape 1 : Créer un compte Oracle Cloud

1. Allez sur https://cloud.oracle.com/
2. Créez un compte gratuit
3. Vérifiez votre email
4. Connectez-vous à la console

### Étape 2 : Créer une instance Compute (ARM)

1. Menu → **Compute** → **Instances**
2. Cliquez sur **Create Instance**
3. **Name** : `shinecongo-server`
4. **Image** : Ubuntu 22.04 (ARM)
5. **Shape** : **VM.Standard.A1.Flex** (Always Free)
   - **OCPUs** : 2 (gratuit)
   - **Memory** : 12GB (gratuit)
6. **Networking** : Créez un VCN si nécessaire
7. **SSH Keys** : Uploadez votre clé publique SSH
8. Créez l'instance

### Étape 3 : Configurer les règles de sécurité

1. Allez dans **Networking** → **Security Lists**
2. Ajoutez des règles ingress :
   - **Port 22** (SSH) : Votre IP
   - **Port 80** (HTTP) : 0.0.0.0/0
   - **Port 443** (HTTPS) : 0.0.0.0/0

### Étape 4 : Configurer le serveur

Utilisez le même script `setup_aws.sh` (fonctionne aussi pour Oracle Cloud) :

```bash
ssh -i votre-cle.pem ubuntu@VOTRE_IP_PUBLIQUE
```

Puis exécutez :

```bash
cd /home/ubuntu
# Clonez votre projet ou uploadez-le
wget https://raw.githubusercontent.com/VOTRE_REPO/portal_shinecongo/main/setup_aws.sh
chmod +x setup_aws.sh
./setup_aws.sh
```

### Étape 5 : Configurer S3 (AWS) ou Object Storage (Oracle)

#### Option A : Continuer avec AWS S3 (recommandé)
- Gardez votre bucket S3 AWS
- Coût : ~0.023$/GB/mois (très économique)
- Pour 10GB : ~0.23$/mois

#### Option B : Utiliser Oracle Object Storage (gratuit)
- 10GB gratuit dans Oracle Cloud
- Configuration similaire à S3
- Total : **0$/mois** ✅

### Étape 6 : Configurer le domaine (optionnel)

1. Achetez un domaine sur Namecheap ou Cloudflare (~10$/an)
2. Configurez les DNS pour pointer vers votre IP Oracle
3. Utilisez Let's Encrypt pour SSL gratuit

## 💰 Coûts Oracle Cloud Always Free

### Pendant Always Free Tier :
- **Compute (ARM)** : 0$/mois ✅
- **Storage (100GB)** : 0$/mois ✅
- **Transfert (10TB)** : 0$/mois ✅
- **Total** : **0$/mois pour toujours** ✅✅✅

### Si vous dépassez les limites :
- Compute supplémentaire : Pay-as-you-go
- Storage supplémentaire : ~0.025$/GB/mois
- Transfert supplémentaire : ~0.0085$/GB

## 📊 Comparaison des Coûts

| Service | Pendant Free Tier | Après Free Tier |
|---------|------------------|-----------------|
| **AWS EC2** | 0$/mois (12 mois) | ~3.50-8.50$/mois |
| **Oracle Cloud** | 0$/mois | **0$/mois (toujours)** ⭐ |
| **Hetzner** | N/A | 3.50$/mois |
| **DigitalOcean** | N/A | 4$/mois |

## ✅ Avantages Oracle Cloud Always Free

1. **Gratuit pour toujours** (pas seulement 12 mois)
2. **Plus de ressources** (4 vCPU, 24GB RAM vs 1 vCPU, 1GB pour AWS)
3. **10TB de transfert** (vs 1GB pour AWS)
4. **100GB storage** (vs 5GB pour AWS)
5. **Même architecture** que AWS (compatible avec vos scripts)

## ⚠️ Limitations Oracle Cloud Always Free

1. **Seulement 2 instances ARM** (mais suffisant pour votre app)
2. **Régions limitées** (mais plusieurs disponibles)
3. **Support communautaire** (pas de support premium gratuit)

## 🎯 Recommandation Finale

**Pour votre cas d'usage (< 1$/mois) :**

1. **Commencez avec AWS Free Tier** (12 mois gratuits)
   - Apprenez AWS
   - Testez votre application
   - Coût : 0$/mois

2. **Migrez vers Oracle Cloud Always Free** (après 12 mois)
   - Même architecture
   - Plus de ressources
   - Gratuit pour toujours
   - Coût : 0$/mois ✅

3. **Utilisez AWS S3 pour les photos** (optionnel)
   - Très économique (~0.023$/GB/mois)
   - Pour 10GB : ~0.23$/mois
   - **Total final : ~0.23$/mois** ✅✅✅

**OU**

4. **Utilisez Oracle Object Storage**
   - 10GB gratuit
   - **Total final : 0$/mois** ✅✅✅✅

## 📝 Checklist Migration AWS → Oracle Cloud

- [ ] Créer un compte Oracle Cloud
- [ ] Créer une instance ARM Always Free
- [ ] Configurer les règles de sécurité
- [ ] Transférer votre code (Git clone)
- [ ] Configurer les variables d'environnement
- [ ] Migrer la base de données (SQLite peut être copié directement)
- [ ] Configurer Nginx et Gunicorn (même configuration)
- [ ] Tester l'application
- [ ] Configurer SSL (Let's Encrypt)
- [ ] Configurer les sauvegardes automatiques

## 🔄 Script de Migration

Créez un script `migrate_to_oracle.sh` pour faciliter la migration :

```bash
#!/bin/bash
# Script pour migrer de AWS vers Oracle Cloud

# 1. Sauvegarder la base de données
scp -i aws-key.pem ubuntu@aws-ip:/home/ubuntu/portal_shinecongo/db.sqlite3 ./backup/

# 2. Transférer vers Oracle Cloud
scp -i oracle-key.pem ./backup/db.sqlite3 ubuntu@oracle-ip:/home/ubuntu/portal_shinecongo/

# 3. Mettre à jour les variables d'environnement
# (modifier .env sur Oracle Cloud avec les nouvelles valeurs)

# 4. Redémarrer le service
ssh -i oracle-key.pem ubuntu@oracle-ip "sudo systemctl restart shinecongo"
```

---

**Conclusion : OUI, vous pouvez déployer pour < 1$/mois (même 0$/mois) avec Oracle Cloud Always Free !** ✅
