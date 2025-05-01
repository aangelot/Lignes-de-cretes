from django.urls import path
from hello import views

urlpatterns = [
    path("", views.home, name="home"),
    path("hello/<name>", views.hello_there, name="hello_there"),
    path("contact/", views.contact, name="contact"),
    path('plan_hike/', views.plan_hike, name='plan_hike'),
]