from django.contrib import admin
from django.urls import include, path
from django.contrib.staticfiles.urls import staticfiles_urlpatterns
from django.views.static import serve
from django.conf import settings
from pathlib import Path

urlpatterns = [
    path("", include("hello.urls")),
    path('admin/', admin.site.urls),

    # 👉 AJOUT ICI
    path(
        'data/output/<path:path>',
        serve,
        {'document_root': Path(settings.BASE_DIR) / 'data/output'}
    ),
]

urlpatterns += staticfiles_urlpatterns()