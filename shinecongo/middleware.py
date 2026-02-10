"""
Middleware personnalisé pour gérer le cache et la sécurité
"""
from django.utils.deprecation import MiddlewareMixin
from django.conf import settings


class NoCacheMiddleware(MiddlewareMixin):
    """
    Middleware pour empêcher la mise en cache des pages protégées
    Empêche l'accès via le bouton retour du navigateur après déconnexion
    """
    def process_response(self, request, response):
        # Liste des chemins publics qui peuvent être mis en cache
        public_paths = ['/login/', '/logout/', '/static/', '/media/']
        
        # Vérifier si c'est un chemin public
        is_public = any(request.path.startswith(path) for path in public_paths)
        
        # Si ce n'est pas un chemin public OU si l'utilisateur n'est pas authentifié
        # Ajouter des en-têtes pour empêcher la mise en cache
        if not is_public or not request.user.is_authenticated:
            response['Cache-Control'] = 'no-cache, no-store, must-revalidate, max-age=0'
            response['Pragma'] = 'no-cache'
            response['Expires'] = '0'
            # Empêcher la mise en cache même pour les navigateurs qui ignorent Cache-Control
            response['X-Content-Type-Options'] = 'nosniff'
        
        return response
