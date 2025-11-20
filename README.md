# Lignes de Crêtes

### 🌄 Qu'est-ce que c'est ?

**Lignes de Crêtes** est une application web pour planifier des randonnées à la journée ou sur plusieurs jours, en **utilisant les transports en commun**.

- Choisissez un **point de départ** (ou départ + arrivée)
- Indiquez une **date**
- L’outil vous propose un enchaînement **transport → rando → transport retour**
- Vous pouvez **exporter la trace GPX** pour l’utiliser hors ligne 

Première région couverte : Rhône-Alpes.
Point de départ : Lyon

### ⚙️ Technologies utilisées

- **Back-end :** Python, Django, PostGIS  
- **Front-end :** Templates Django + Leaflet (OSM)  
- **Cartographie :** OpenStreetMap, dénivelé, POI  
- **Export :** fichier GPX  

### 📦 Fonctionnalités de la version MVP

- 🚉 Calcul du trajet aller-retour en transport public  
- 🥾 Génération d’un itinéraire de rando optimisé (boucle à venir ou A→B)  
- 🌍 Carte interactive avec sentiers, départ, arrivée  
- 📤 Export GPX  
- ✅ Pas de création de compte nécessaire  

### 🛣 Feuille de route

À venir :

- Ajout des points d'intérêt au tracé
- Planification multi-jours avec hébergements (refuges)
- Choix d'un arrêt de départ, d'un point d'intérêt à visiter 
- Comptes utilisateurs, favoris, partages  
- Extension géographique  

📍 **Voir notre [Backlog](https://github.com/aangelot/Lignes-de-cretes/projects?query=is%3Aopen)** pour plus de détails.

### 🌍 Open source & Licence

Le projet est **open source** sous **licence MIT**.

> ⚠️ L’usage de données IGN est à l’étude. Les mentions légales nécessaires seront affichées.  
> Les données géographiques proviennent principalement d’**OpenStreetMap**.

### 🤝 Contribuer

Toute aide est la bienvenue :

- Amélioration des données OSM (POI, sources, refuges, sentiers)  
- Design UX/UI  
- Extension à d’autres massifs  

Envoyez une issue ou une pull request !


# Documentation technique

Voici le process de calcul du meilleur itinéraire :
<img width="6877" height="3375" alt="Process lignes de crêtes" src="https://github.com/user-attachments/assets/10166174-d3df-46a0-bd1f-c4c0b92c6e4d" />

## Lancer l'application

### 1. Installer les dépendances système (GDAL)

```bash
sudo apt update
sudo apt install gdal-bin libgdal-dev
export CPLUS_INCLUDE_PATH=/usr/include/gdal
export C_INCLUDE_PATH=/usr/include/gdal
```

### 2. Créer et activer l’environnement virtuel

```bash
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

### 3. Configurer le fichier `.env`

Copiez le fichier `.env-example` d’exemple fourni, le renommer en `.env` et ajoutez votre clé Google API dans la variable prévue ainsi que les variables pour une base PostgreSQL. 

### 4. Préparation de PostgreSQL

Démarrer et activer PostgreSQL :

```bash
sudo systemctl start postgresql
sudo systemctl enable postgresql
```

Se connecter en tant que superutilisateur :

```bash
sudo -u postgres psql
```

Créer l’utilisateur, la base de données et attribuer les droits :

```sql
CREATE USER "nom_utilisateur" WITH PASSWORD 'mot_de_passe';
CREATE DATABASE nom_de_ta_base OWNER nom_utilisateur;
GRANT ALL PRIVILEGES ON DATABASE nom_de_ta_base TO "nom_utilisateur";
```

### 5. Appliquer les migrations Django

```bash
python manage.py migrate
```

### 6. Ajouter les fichiers pour calcul itinéraire
Dans data/output, ajouter les fichers disponibles depuis ce lien : https://drive.google.com/drive/folders/1BkE31PsgJABIiVLXBGiulQQ-MCorUeXK?usp=sharing 

### 7. Lancer le serveur

```bash
python manage.py runserver
```

### Notes utiles pour comprendre le projet plus vite

* Vérifiez que `ALLOWED_HOSTS` dans `settings.py` inclut votre machine ou domaine si vous passez en production.
* Si l’application manipule des données géospatiales, assurez-vous que la version de GDAL installée correspond bien à celle attendue dans `requirements.txt`.
* En cas d’erreur liée à GDAL au lancement du serveur, confirmez que l’environnement virtuel a bien accès aux bibliothèques installées dans `/usr/include/gdal`.


## Calculer les données d'un massif
Télécharger le fichier GeoJSON des parcs naturels ici : https://data-interne.ademe.fr/datasets/pnr
Et l'enregistrer dans data/input/pnr.geojson

Télécharger ensuite tous les arrêts publics en France ici : https://transport.data.gouv.fr/datasets/arrets-de-transport-en-france
Et enregistrer le fichier CSV dans data/input/stops_france.csv

[à continuer]
