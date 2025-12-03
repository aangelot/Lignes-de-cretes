# Image de base : Python 3.12 sur Debian slim
FROM python:3.12-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    CPLUS_INCLUDE_PATH=/usr/include/gdal \
    C_INCLUDE_PATH=/usr/include/gdal

# Dépendances système pour GDAL / géospatial / build Python
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    gdal-bin \
    libgdal-dev \
    proj-bin \
    libproj-dev \
    libgeos-dev \
    libspatialindex-dev \
    curl \
 && rm -rf /var/lib/apt/lists/*

# Création de l'utilisateur non-root
RUN useradd -m appuser

WORKDIR /app

# Copier requirements et installer Python
COPY requirements.txt .
RUN pip install --upgrade pip \
 && pip install --no-cache-dir -r requirements.txt \
 && pip install gunicorn  # installer gunicorn

# Copier le code de l'application
COPY . .

# Ajouter wait-for-it pour PostgreSQL
COPY wait-for-it.sh /app/wait-for-it.sh
RUN chmod +x wait-for-it.sh entrypoint.sh

# S'assurer que l'utilisateur appuser peut accéder à tout
RUN chown -R appuser:appuser /app

# Passer à l'utilisateur non-root
USER appuser

# Variables par défaut
ENV DJANGO_SETTINGS_MODULE=lignes_de_cretes.settings \
    PORT=8000

EXPOSE 8000

# Script de démarrage
ENTRYPOINT ["./entrypoint.sh"]
