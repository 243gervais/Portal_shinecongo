from django.contrib.auth.decorators import login_required
from django.contrib.auth import logout, login
from django.shortcuts import render, redirect
from django.utils import timezone
from django.views.decorators.http import require_http_methods
from functools import wraps
from django.http import HttpResponse
from django.contrib import messages
from .forms import UserRegistrationForm


def no_cache_view(view_func):
    """
    Décorateur pour ajouter des en-têtes no-cache à une vue
    Empêche la mise en cache des pages protégées
    """
    @wraps(view_func)
    def _wrapped_view(request, *args, **kwargs):
        response = view_func(request, *args, **kwargs)
        if isinstance(response, HttpResponse):
            response['Cache-Control'] = 'no-cache, no-store, must-revalidate, max-age=0'
            response['Pragma'] = 'no-cache'
            response['Expires'] = '0'
            response['X-Content-Type-Options'] = 'nosniff'
        return response
    return _wrapped_view


@login_required
@no_cache_view
def dashboard(request):
    """
    Dashboard principal qui redirige selon le rôle de l'utilisateur
    """
    user = request.user
    
    # Vérifier si l'utilisateur a un profil
    if not hasattr(user, 'userprofile'):
        from django.contrib import messages
        messages.error(request, 'Profil utilisateur non trouvé. Contactez un administrateur.')
        return redirect('admin:index')
    
    profile = user.userprofile
    
    # Rediriger selon le rôle
    if profile.is_admin():
        # Pour les admins, rediriger vers l'interface Django Admin
        return redirect('admin:index')
    elif profile.is_manager():
        return redirect('manager_dashboard')
    else:  # Employé
        return redirect('employe_dashboard')


@require_http_methods(["GET", "POST"])
def logout_view(request):
    """
    Vue de déconnexion personnalisée qui redirige vers la page de connexion
    """
    logout(request)
    messages.info(request, 'Vous avez été déconnecté avec succès. Veuillez vous reconnecter pour continuer.')
    
    # Créer une réponse de redirection avec des en-têtes pour empêcher la mise en cache
    response = redirect('login')
    response['Cache-Control'] = 'no-cache, no-store, must-revalidate'
    response['Pragma'] = 'no-cache'
    response['Expires'] = '0'
    return response


def register_view(request):
    """
    Vue d'inscription pour créer un nouveau compte utilisateur
    """
    if request.user.is_authenticated:
        return redirect('dashboard')
    
    if request.method == 'POST':
        form = UserRegistrationForm(request.POST)
        if form.is_valid():
            user = form.save()
            messages.success(request, f'Compte créé avec succès ! Bienvenue {user.username}. Vous pouvez maintenant vous connecter.')
            # Optionnel : connecter automatiquement l'utilisateur après inscription
            # login(request, user)
            # return redirect('dashboard')
            return redirect('login')
    else:
        form = UserRegistrationForm()
    
    return render(request, 'auth/register.html', {
        'form': form
    })
