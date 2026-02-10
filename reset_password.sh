#!/bin/bash
# Script pour réinitialiser le mot de passe d'un utilisateur

cd "$(dirname "$0")"
source venv/bin/activate

echo "=== Réinitialisation du mot de passe ==="
echo ""
echo "Utilisateur trouvé: gervaismbadu"
echo ""
echo "Pour réinitialiser le mot de passe, exécutez:"
echo "python manage.py changepassword gervaismbadu"
echo ""
read -p "Voulez-vous réinitialiser le mot de passe maintenant? (y/n) " -n 1 -r
echo
if [[ $REPLY =~ ^[Yy]$ ]]; then
    python manage.py changepassword gervaismbadu
else
    echo "Annulé."
fi
