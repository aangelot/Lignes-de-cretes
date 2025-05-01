# Lignes de Crêtes

[🇫🇷 Lire en français](#-français--lignes-de-crêtes)

---

## 🇬🇧 English – Lignes de Crêtes

_A web application to plan day or multi-day hikes combining public transport and open data._

### 🌄 What is it?

**Lignes de Crêtes** helps you plan beautiful hikes — from your home, using only **public transport**. It targets experienced mountaineers but aims to stay accessible to casual hikers as well.

- Select a **starting point** (or both start and end)
- Choose a **date**
- The app finds the **best public transport + hike combo**, and the way back
- You can **export the GPX** track for offline use

Initial focus: the Rhône-Alpes region. Future expansions possible.

### ⚙️ Tech Stack

- **Back-end:** Python, Django, PostGIS  
- **Front-end:** Django templates + Leaflet (OSM-based maps)  
- **Mapping:** OpenStreetMap for trails, elevation, and POIs  
- **Transport data:** GTFS feeds (SNCF, regional networks)  
- **Export:** GPX file generation  

### 📦 MVP Features

- 🚆 Compute round-trips using public transportation  
- 🥾 Generate optimized hiking loops or point-to-point tracks (distance, elevation gain)  
- 🗺️ Interactive map with trails and POIs  
- 📤 GPX export  
- ✅ Anonymous usage (no account needed yet)  

### 🛣 Roadmap

Planned features:

- Multi-day hike planner with hut suggestions  
- Accounts and saved/shared hikes  
- Trail ratings, difficulty levels  
- Expanded geographic coverage  
- Donation-based sustainability  

📍 **See our [Backlog](https://github.com/aangelot/Lignes-de-cretes/projects?query=is%3Aopen)** for details.

### 🌍 Open Source & Licensing

This project is fully **open source**, licensed under the **MIT license**.

> ⚠️ Use of IGN data is under review. Legal disclaimers will be displayed as needed.  
> Main geographic data comes from the **OpenStreetMap community**.

### 🤝 How to Contribute

We welcome all contributions:

- Integrating GTFS feeds  
- Enhancing OSM data (POIs, water, huts, trails)  
- Improving UI/UX  
- Scaling to more regions  

Feel free to open an issue or a pull request!

---

## 🇫🇷 Français – Lignes de Crêtes

### 🌄 Qu'est-ce que c'est ?

**Lignes de Crêtes** est une application web pour planifier des randonnées à la journée ou sur plusieurs jours, en **utilisant les transports en commun**.

- Choisissez un **point de départ** (ou départ + arrivée)
- Indiquez une **date**
- L’outil vous propose un enchaînement **transport → rando → transport retour**
- Vous pouvez **exporter la trace GPX** pour l’utiliser hors ligne

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

### 🏕 Pourquoi “Lignes de Crêtes” ?

Les lignes de crêtes sont les chemins visibles sur les sommets. Elles symbolisent l’altitude, la progression et la clarté d’orientation. Un nom qui reflète notre ambition : naviguer entre nature, infrastructures et liberté.

