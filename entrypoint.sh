#!/bin/bash
set -e

# Attendre PostgreSQL
# echo "=> Waiting for PostgreSQL..."
# ./wait-for-it.sh db:5432 --timeout=30 --strict

# Créer le dossier staticfiles si inexistant
echo "=> Ensuring staticfiles directory exists..."
mkdir -p /app/staticfiles

# Migrations
# echo "=> Applying database migrations..."
# python manage.py migrate --noinput

# Collecte des fichiers statiques
echo "=> Collecting static files..."
python manage.py collectstatic --noinput || echo "collectstatic failed (maybe no STATIC_ROOT), continuing..."

# Lancement de Gunicorn
echo "=> Starting Gunicorn..."
exec gunicorn lignes_de_cretes.wsgi:application \
    --bind 0.0.0.0:${PORT:-8000} \
    --timeout 180 \
    --workers 3
