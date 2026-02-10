from django.db import models
import uuid
from decimal import Decimal


class Location(models.Model):
    """
    Site/Location de lavage (ex: Station Texaco Gombe, Station Total Lemba, etc.)
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    nom = models.CharField(max_length=200, verbose_name="Nom du site")
    adresse = models.TextField(blank=True, verbose_name="Adresse")
    ville = models.CharField(max_length=100, default="Kinshasa", verbose_name="Ville")
    telephone = models.CharField(max_length=20, blank=True, verbose_name="Téléphone")
    actif = models.BooleanField(default=True, verbose_name="Actif")
    
    # QR Code fixe par site
    site_token = models.UUIDField(default=uuid.uuid4, unique=True, editable=False, verbose_name="Token du site")
    
    # GPS optionnel (anti-fraude)
    latitude = models.DecimalField(
        max_digits=9, 
        decimal_places=6, 
        null=True, 
        blank=True,
        verbose_name="Latitude"
    )
    longitude = models.DecimalField(
        max_digits=9, 
        decimal_places=6, 
        null=True, 
        blank=True,
        verbose_name="Longitude"
    )
    rayon_autorisé_mètres = models.IntegerField(
        default=50,
        verbose_name="Rayon autorisé (mètres)",
        help_text="Rayon autour du site pour la vérification GPS"
    )
    gps_actif = models.BooleanField(
        default=False,
        verbose_name="GPS actif",
        help_text="Activer la vérification GPS pour ce site"
    )
    
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="Créé le")
    updated_at = models.DateTimeField(auto_now=True, verbose_name="Modifié le")
    
    class Meta:
        verbose_name = "Site"
        verbose_name_plural = "Sites"
        ordering = ["nom"]
    
    def __str__(self):
        return self.nom
    
    def get_qr_url(self):
        """
        Retourne l'URL du QR code fixe pour ce site
        """
        from django.urls import reverse
        return reverse('scan_qr_fixe', kwargs={'site_token': str(self.site_token)})
    
    def calculate_distance(self, lat, lon):
        """
        Calcule la distance en mètres entre le site et une position GPS donnée
        Utilise la formule de Haversine
        """
        if not self.latitude or not self.longitude:
            return None
        
        from math import radians, cos, sin, asin, sqrt
        
        # Convertir en radians
        lat1 = radians(float(self.latitude))
        lon1 = radians(float(self.longitude))
        lat2 = radians(float(lat))
        lon2 = radians(float(lon))
        
        # Formule de Haversine
        dlon = lon2 - lon1
        dlat = lat2 - lat1
        a = sin(dlat/2)**2 + cos(lat1) * cos(lat2) * sin(dlon/2)**2
        c = 2 * asin(sqrt(a))
        
        # Rayon de la Terre en mètres
        r = 6371000
        
        return c * r