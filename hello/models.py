from django.contrib.gis.db import models as gis_models
from django.db import models

class POI(models.Model):
    name = models.CharField(max_length=200)
    location = gis_models.PointField()
    description = models.TextField(blank=True)

    def __str__(self):
        return self.name
    
class Hike(models.Model):
    name = models.CharField(max_length=255)
    path = gis_models.LineStringField(srid=4326)  # This represents the hike trail
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.name