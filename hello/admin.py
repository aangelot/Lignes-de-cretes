from django.contrib import admin
from django.contrib.gis.admin import GISModelAdmin
from .models import POI, Hike

@admin.register(POI)
class POIAdmin(GISModelAdmin):
    list_display = ('name', 'location')

@admin.register(Hike)
class HikeAdmin(GISModelAdmin):
    list_display = ('name', 'path')
