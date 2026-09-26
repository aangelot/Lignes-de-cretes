from django.urls import path
from . import views, views_manual

urlpatterns = [
    # Mode manuel (cf. views_manual.py)
    path('manual/stops/', views_manual.manual_stops, name='manual_stops'),
    path('manual/transit_go/', views_manual.manual_transit_go, name='manual_transit_go'),
    path('manual/pois/', views_manual.manual_pois, name='manual_pois'),
    path('manual/hike/', views_manual.manual_hike, name='manual_hike'),
    path('manual/finish/', views_manual.manual_finish, name='manual_finish'),

    path('', views.index, name='index'),                  # Page d'accueil
    path('get_route/', views.get_route, name='get_route'),  # API GeoJSON
    path('start_route/', views.start_route, name='start_route'),  # Lance le calcul en arrière-plan
    path('route_status/', views.route_status, name='route_status'),  # Suivi d'avancement du calcul
    path('gares/', views.gares_list, name='gares_list'),  # Liste des gares pour autocomplete
    path('massifs/', views.massifs_actifs, name='massifs_actifs'),  # Contours des massifs ouverts
]

