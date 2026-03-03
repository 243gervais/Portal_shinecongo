from django.db import models
import uuid
from decimal import Decimal
from django.contrib.auth.models import User
from django.core.validators import MinValueValidator
import os


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


class DailyBankDeposit(models.Model):
    """
    Dépôt bancaire quotidien par site
    Enregistre le montant déposé à la banque à la fin de chaque journée
    """
    site = models.ForeignKey(Location, on_delete=models.CASCADE, related_name="bank_deposits", verbose_name="Site")
    date = models.DateField(verbose_name="Date du dépôt")
    amount = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        validators=[MinValueValidator(0)],
        verbose_name="Montant déposé (FC)"
    )
    notes = models.TextField(blank=True, verbose_name="Notes")
    created_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="bank_deposits_created",
        verbose_name="Enregistré par"
    )
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="Créé le")
    updated_at = models.DateTimeField(auto_now=True, verbose_name="Modifié le")
    
    class Meta:
        verbose_name = "Dépôt Bancaire Quotidien"
        verbose_name_plural = "Dépôts Bancaires Quotidiens"
        unique_together = [["site", "date"]]
        ordering = ["-date", "-created_at"]
        indexes = [
            models.Index(fields=["site", "date"]),
            models.Index(fields=["-date"]),
        ]
    
    def __str__(self):
        return f"{self.site.nom} - {self.date} - {self.amount} FC"


def site_document_path(instance, filename):
    """Chemin de sauvegarde des documents du site"""
    site_id = str(instance.site.id)
    file_type = instance.file_type.lower()
    return f"sites/{site_id}/{file_type}/{filename}"


class SiteDocument(models.Model):
    """
    Documents et fichiers liés à un site
    Contrats, paiements, photos de construction, vidéos, etc.
    """
    FILE_TYPE_CHOICES = [
        ("CONTRAT", "Contrat avec le prêteur"),
        ("PAIEMENT", "Paiement de location"),
        ("COMPTE_BANCAIRE", "Photo compte bancaire du prêteur"),
        ("PHOTO_CONSTRUCTION", "Photo de construction"),
        ("VIDEO_CONSTRUCTION", "Vidéo de construction"),
        ("AUTRE_DOCUMENT", "Autre document"),
        ("AUTRE_PHOTO", "Autre photo"),
        ("AUTRE_VIDEO", "Autre vidéo"),
    ]
    
    site = models.ForeignKey(Location, on_delete=models.CASCADE, related_name="documents", verbose_name="Site")
    file_type = models.CharField(
        max_length=30,
        choices=FILE_TYPE_CHOICES,
        default="AUTRE_DOCUMENT",
        verbose_name="Type de fichier"
    )
    title = models.CharField(max_length=200, verbose_name="Titre")
    description = models.TextField(blank=True, verbose_name="Description")
    file = models.FileField(upload_to=site_document_path, verbose_name="Fichier")
    uploaded_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="site_documents_uploaded",
        verbose_name="Uploadé par"
    )
    uploaded_at = models.DateTimeField(auto_now_add=True, verbose_name="Uploadé le")
    updated_at = models.DateTimeField(auto_now=True, verbose_name="Modifié le")
    
    class Meta:
        verbose_name = "Document du Site"
        verbose_name_plural = "Documents du Site"
        ordering = ["-uploaded_at"]
        indexes = [
            models.Index(fields=["site", "file_type"]),
            models.Index(fields=["-uploaded_at"]),
        ]
    
    def __str__(self):
        return f"{self.site.nom} - {self.get_file_type_display()} - {self.title}"
    
    def filename(self):
        """Retourne le nom du fichier"""
        return os.path.basename(self.file.name)
    
    def is_image(self):
        """Vérifie si le fichier est une image"""
        ext = os.path.splitext(self.file.name)[1].lower()
        return ext in ['.jpg', '.jpeg', '.png', '.gif', '.webp', '.bmp']
    
    def is_video(self):
        """Vérifie si le fichier est une vidéo"""
        ext = os.path.splitext(self.file.name)[1].lower()
        return ext in ['.mp4', '.avi', '.mov', '.wmv', '.flv', '.webm', '.mkv']
    
    def is_pdf(self):
        """Vérifie si le fichier est un PDF"""
        return os.path.splitext(self.file.name)[1].lower() == '.pdf'
    
    def file_size_mb(self):
        """Retourne la taille du fichier en MB"""
        try:
            size = self.file.size
            return round(size / (1024 * 1024), 2)
        except:
            return 0
