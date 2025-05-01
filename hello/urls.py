from django.urls import path
from hello import views

urlpatterns = [
    path("", views.index, name="index"),
    path("hello/<name>", views.hello_there, name="hello_there"),
    ]