# Lignes de Crêtes

### 🌄 Qu'est-ce que c'est ?

**Lignes de Crêtes** est une application web pour planifier des randonnées à la journée ou sur plusieurs jours, en **utilisant les transports en commun**.

- Choisissez un **point de départ** (ou départ + arrivée)
- Indiquez une **date**
- L’outil vous propose un enchaînement **transport → rando → transport retour**
- Vous pouvez **exporter la trace GPX** pour l’utiliser hors ligne [à venir]

Première région couverte : Rhône-Alpes.

### ⚙️ Technologies utilisées

- **Back-end :** Python, Django, PostGIS  
- **Front-end :** Templates Django + Leaflet (OSM)  
- **Cartographie :** OpenStreetMap, dénivelé, POI  
- **Données transport :** flux GTFS (SNCF, TER, réseaux régionaux)  
- **Export :** fichier GPX  

### 📦 Fonctionnalités de la version MVP

- 🚉 Calcul du trajet aller-retour en transport public  
- 🥾 Génération d’un itinéraire de rando optimisé (boucle ou A→B)  
- 🌍 Carte interactive avec sentiers, sources, points d’intérêt  
- 📤 Export GPX  
- ✅ Pas de création de compte nécessaire  

### 🛣 Feuille de route

À venir :

- Planification multi-jours avec hébergements (refuges)  
- Comptes utilisateurs, favoris, partages  
- Niveaux de difficulté et retours utilisateurs  
- Extension géographique  
- Financement via dons  

📍 **Voir notre [Backlog](https://github.com/aangelot/Lignes-de-cretes/projects?query=is%3Aopen)** pour plus de détails.

### 🌍 Open source & Licence

Le projet est **open source** sous **licence MIT**.

> ⚠️ L’usage de données IGN est à l’étude. Les mentions légales nécessaires seront affichées.  
> Les données géographiques proviennent principalement d’**OpenStreetMap**.

### 🤝 Contribuer

Toute aide est la bienvenue :

- Intégration des données GTFS  
- Amélioration des données OSM (POI, sources, refuges, sentiers)  
- Design UX/UI  
- Extension à d’autres massifs  

Envoyez une issue ou une pull request !


# Documentation technique

Voici le process de calcul du meilleur itinéraire :
<img width="6877" height="3375" alt="Process lignes de crêtes" src="https://github.com/user-attachments/assets/10166174-d3df-46a0-bd1f-c4c0b92c6e4d" />

## Pour reproduire
Télécharger le fichier GeoJSON des parcs naturels ici : https://data-interne.ademe.fr/datasets/pnr
Et l'enregistrer dans data/input/pnr.geojson

Télécharger ensuite tous les arrêts publics en France ici : https://transport.data.gouv.fr/datasets/arrets-de-transport-en-france
Et enregistrer le fichier CSV dans data/input/stops_france.csv
