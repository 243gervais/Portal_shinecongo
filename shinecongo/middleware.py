"""
Middleware personnalisé pour gérer le cache et la sécurité
"""
from django.utils.deprecation import MiddlewareMixin
from django.conf import settings
import logging
from time import perf_counter


class RequestTimingMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        started = perf_counter()
        response = self.get_response(request)
        elapsed_ms = (perf_counter() - started) * 1000
        response['Server-Timing'] = f'app;dur={elapsed_ms:.1f}'
        if elapsed_ms >= 2000 and not request.path.startswith(('/media/', '/static/', '/portal-assets/')):
            logging.getLogger('shinecongo.performance').warning(
                'Slow request method=%s route=%s status=%s duration_ms=%.0f',
                request.method,
                getattr(getattr(request, 'resolver_match', None), 'view_name', 'unknown'),
                response.status_code, elapsed_ms,
            )
        return response


class NoCacheMiddleware(MiddlewareMixin):
    """
    Middleware pour empêcher la mise en cache des pages protégées
    Empêche l'accès via le bouton retour du navigateur après déconnexion
    """
    def process_response(self, request, response):
        # Les assets versionnés doivent rester cacheables, même avant connexion.
        cacheable_paths = ['/static/', '/media/', '/portal-assets/']
        if any(request.path.startswith(path) for path in cacheable_paths):
            return response

        # Liste des chemins publics qui peuvent être consultés sans connexion
        public_paths = ['/login/', '/logout/']
        
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
