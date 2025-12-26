from django.urls import path
from . import views

urlpatterns = [
    path('', views.index, name='index'),                  # Page d'accueil
    path('get_route/', views.get_route, name='get_route'),  # API GeoJSON
    path('gares/', views.gares_list, name='gares_list'),  # Liste des gares pour autocomplete
]
