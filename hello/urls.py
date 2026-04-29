from django.urls import path
from . import views

urlpatterns = [
    path('', views.index, name='index'),                  # Page d'accueil
    path('get_route/', views.get_route, name='get_route'),  # API GeoJSON
    path('start_route/', views.start_route, name='start_route'),  # Lance le calcul en arrière-plan
    path('route_status/', views.route_status, name='route_status'),  # Suivi d'avancement du calcul
    path('gares/', views.gares_list, name='gares_list'),  # Liste des gares pour autocomplete
]

