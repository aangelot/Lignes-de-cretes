function setDefaultDates() {
  const depInput = document.getElementById("departure_datetime");
  const retInput = document.getElementById("return_datetime");
  if (!depInput || !retInput) return;

  const now = new Date();

  // Trouver le prochain samedi (6 = samedi)
  const nextSaturday = new Date(now);
  nextSaturday.setDate(now.getDate() + ((6 - now.getDay() + 7) % 7));
  nextSaturday.setHours(8, 0, 0, 0);

  // Prochain dimanche
  const nextSunday = new Date(nextSaturday);
  nextSunday.setDate(nextSaturday.getDate() + 1);
  nextSunday.setHours(20, 0, 0, 0);

  // Formater en "YYYY-MM-DDTHH:MM" selon la timezone locale
  const fmtLocal = (d) => {
    const pad = (n) => n.toString().padStart(2, "0");
    return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}`;
  };

  depInput.value = fmtLocal(nextSaturday);
  retInput.value = fmtLocal(nextSunday);
}


document.addEventListener('DOMContentLoaded', () => {
    setDefaultDates();
    // === Modale info ===
    const infoBtn = document.getElementById('infoBtn');
    const infoModal = document.getElementById('infoModal');
    const closeModal = document.getElementById('closeModal');

    infoBtn.onclick = () => infoModal.style.display = 'flex';
    closeModal.onclick = () => infoModal.style.display = 'none';
    window.onclick = e => { if (e.target === infoModal) infoModal.style.display = 'none'; };

    // === Initialisation de la carte ===
    const map = L.map('map').setView([45.36, 5.79], 12);

    const osm = L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
        attribution: '&copy; OpenStreetMap contributors'
    }).addTo(map);

    const satellite = L.tileLayer('https://{s}.google.com/vt/lyrs=s&x={x}&y={y}&z={z}', {
        maxZoom: 20,
        subdomains: ['mt0','mt1','mt2','mt3'],
        attribution: '&copy; <a href="https://www.google.com/earth/">Google</a>'
    });

    const topo = L.tileLayer('https://{s}.tile.opentopomap.org/{z}/{x}/{y}.png', {
        maxZoom: 17,
        attribution: 'Map data: &copy; <a href="https://www.opentopomap.org/">OpenTopoMap</a>, &copy; OpenStreetMap contributors'
    });

    const baseMaps = { "OSM": osm, "Satellite": satellite, "OpenTopoMap": topo };
    L.control.layers(baseMaps, null, { position: 'bottomright' }).addTo(map);

    map.zoomControl.remove();
    L.control.zoom({ position: 'bottomright' }).addTo(map);


    // === Variables globales ===
    let currentLayer = null;
    let startMarker = null;
    let endMarker = null;
    let arrowDecorator = null;
    let controlElevation = null;

    // Vérification des dates
    const depInput = document.getElementById('departure_datetime');
    const retInput = document.getElementById('return_datetime');
    const submitBtn = document.getElementById('submit-btn');
    const errorDiv = document.getElementById('date-error');

    function validateDates() {
        const departure = new Date(depInput.value);
        const arrival = new Date(retInput.value);
        const now = new Date();
        const maxDate = new Date();
        maxDate.setDate(now.getDate() + 100);

        let message = '';
        let isValid = true;

        if (depInput.value && departure > maxDate) {
            message = "❌ La date de départ ne peut pas dépasser 100 jours à partir d'aujourd'hui.";
            isValid = false;
        } else if (retInput.value && arrival > maxDate) {
            message = "❌ La date de retour ne peut pas dépasser 100 jours à partir d'aujourd'hui.";
            isValid = false;
        } else if (depInput.value && retInput.value && departure >= arrival) {
            message = "❌ La date de départ doit être avant la date de retour.";
            isValid = false;
        } else if (depInput.value && retInput.value) {
            const diffDays = (arrival - departure) / (1000*60*60*24);
            if (diffDays > 10) {
                message = `❌ L'écart entre départ et retour ne peut pas dépasser 10 jours (vous avez choisi ${Math.round(diffDays)} jours).`;
                isValid = false;
            }
        }

        errorDiv.textContent = message;
        submitBtn.disabled = !isValid;
    }

    // Ecouteurs dynamiques
    depInput.addEventListener('input', validateDates);
    retInput.addEventListener('input', validateDates);

    // Crée le control d'élévation dans la modale Résumé
    function initElevationInSummary() {
        const summaryModal = document.getElementById('modal-summary');
        const elevDiv = summaryModal.querySelector("#elevation-div");
        const legendDiv = summaryModal.querySelector("#elevation-legend");
        if (!elevDiv || !legendDiv) return;

        // Supprimer l'ancien contrôle si existant
        if (controlElevation) {
            controlElevation.remove();
            controlElevation = null;
        }

        // Initialisation du contrôle
        controlElevation = L.control.elevation({
            elevationDiv: "#elevation-div",
            theme: "custom-elevation-theme",
            collapsed: false
        }).addTo(map);

        // Ajouter les données si elles existent
        if (currentLayer) controlElevation.addData(currentLayer.toGeoJSON());

        // Forcer le resize après rendu
        setTimeout(() => {
            if (controlElevation && typeof controlElevation.resize === "function") {
                controlElevation.resize();
            }

            // Mettre à jour la légende personnalisée
            const data = currentLayer ? currentLayer.toGeoJSON() : null;
            if (data) {
                let totalLength = 0, minEle = Infinity, maxEle = -Infinity, sumEle = 0, nPoints = 0;
                const props = data.features[0].properties;
                data.features.forEach(f => {
                    const coords = f.geometry.coordinates;
                    for (let i = 0; i < coords.length; i++) {
                        const ele = coords[i][2];
                        if (ele != null) {
                            minEle = Math.min(minEle, ele);
                            maxEle = Math.max(maxEle, ele);
                            sumEle += ele;
                            nPoints++;
                        }
                        if (i > 0) {
                            const prev = L.latLng(coords[i-1][1], coords[i-1][0]);
                            const curr = L.latLng(coords[i][1], coords[i][0]);
                            totalLength += prev.distanceTo(curr);
                        }
                    }
                });

                legendDiv.innerHTML = `
                    <p><strong>Distance totale :</strong> ${(totalLength/1000).toFixed(2)} km</p>
                    <p><strong>Dénivelé positif :</strong> ${props.path_elevation ?? 'N/A'} m</p>
                    <p><strong>Altitude minimale :</strong> ${minEle.toFixed(0)} m</p>
                    <p><strong>Altitude maximale :</strong> ${maxEle.toFixed(0)} m</p>
                `;
            }

        }, 100); // 100ms pour être sûr que le DOM a pris la taille
    }

    // === Nettoyage carte ===
    function clearMapOverlays() {
        if (currentLayer) { map.removeLayer(currentLayer); currentLayer = null; }
        if (startMarker) { map.removeLayer(startMarker); startMarker = null; }
        if (endMarker) { map.removeLayer(endMarker); endMarker = null; }
        if (arrowDecorator) { map.removeLayer(arrowDecorator); arrowDecorator = null; }
    }


    // === Fonction affichage transit ===
    function afficherTransit(transitData, container) {
        let firstStep = null;
        for (const leg of transitData.routes[0].legs) {
            for (const step of leg.steps) {
                if (step.travelMode === "TRANSIT") { firstStep = step; break; }
            }
            if (firstStep) break;
        }

        let dateStr = '';
        if (firstStep) {
            const depTimeObj = new Date(firstStep.transitDetails.stopDetails.departureTime);
            dateStr = depTimeObj.toLocaleDateString("fr-FR", {
                weekday: "long", year: "numeric", month: "long", day: "numeric"
            });
        }
        container.innerHTML += `<h4>${dateStr}</h4>`;

        transitData.routes.forEach(route => {
            route.legs.forEach(leg => {
                leg.steps.forEach(step => {
                    if (step.travelMode === "TRANSIT") {
                        const t = step.transitDetails;
                        const depStop = t.stopDetails.departureStop.name;
                        const arrStop = t.stopDetails.arrivalStop.name;
                        const depTime = new Date(t.stopDetails.departureTime).toLocaleTimeString('fr-FR', {hour:'2-digit', minute:'2-digit'});
                        const arrTime = new Date(t.stopDetails.arrivalTime).toLocaleTimeString('fr-FR', {hour:'2-digit', minute:'2-digit'});
                        const line = t.transitLine.nameShort + " " + t.transitLine.name;
                        const vehicle = t.transitLine.vehicle.name.text;
                        const headsign = t.headsign;
                        const link = t.transitLine.agencies[0].uri;

                        // Affichage infos
                        container.innerHTML += `<p>
                            Prendre le ${vehicle} ${line} à ${depStop} à ${depTime}, direction ${headsign}, arrivée à ${arrStop} à ${arrTime}. 
                            Plus d'informations sur le <a href="${link}" target="_blank">site de l'agence</a>.
                        </p>`;

                        
                    }
                });
            });
        });

        // Bouton Google Maps
        if (transitData.routes.length > 0) {
            const firstLeg = transitData.routes[0].legs[0];
            const lastLeg = transitData.routes[0].legs[transitData.routes[0].legs.length - 1];

            let firstCoords = null;
            let lastCoords = null;

            for (const step of firstLeg.steps) {
                if (step.travelMode === "TRANSIT") {
                    const loc = step.transitDetails.stopDetails.departureStop.location.latLng;
                    firstCoords = `${loc.latitude},${loc.longitude}`;
                    break;
                }
            }

            for (let i = lastLeg.steps.length - 1; i >= 0; i--) {
                const step = lastLeg.steps[i];
                if (step.travelMode === "TRANSIT") {
                    const loc = step.transitDetails.stopDetails.arrivalStop.location.latLng;
                    lastCoords = `${loc.latitude},${loc.longitude}`;
                    break;
                }
            }

            if (firstCoords && lastCoords) {
                const gmapsUrl = `https://www.google.com/maps/dir/?api=1&origin=${encodeURIComponent(firstCoords)}&destination=${encodeURIComponent(lastCoords)}&travelmode=transit&hl=fr`;
                container.innerHTML += `
                    <button class="gmaps-btn" onclick="window.open('${gmapsUrl}', '_blank')">
                        Autres itinéraires sur Google Maps
                    </button>
                `;
            }
        }
    }


    // === Toggle exclusif pour toutes les modales ===
    function addToggleExclusive(modal) {
        const btn = modal.querySelector('.toggle-btn');
        if (!btn) return;

        btn.addEventListener('click', () => {
            const isCollapsed = modal.classList.contains('collapsed');

            // Si on ouvre cette modale, on ferme toutes les autres
            document.querySelectorAll('.floating-modal').forEach(m => {
                const b = m.querySelector('.toggle-btn');
                if (m === modal) {
                    if (isCollapsed) {
                        m.classList.remove('collapsed');
                        if (b) b.textContent = '▲';
                        if (m.id === 'modal-summary') initElevationInSummary();
                    } else {
                        m.classList.add('collapsed');
                        if (b) b.textContent = '▼';
                    }
                } else {
                    m.classList.add('collapsed');
                    if (b) b.textContent = '▼';
                }
            });
        });
    }
    document.querySelectorAll('.floating-modal').forEach(addToggleExclusive);

    // === Soumission formulaire ===
    document.getElementById('trek-form').addEventListener('submit', async e => {
        e.preventDefault();

        const submitBtn = document.getElementById('submit-btn');
        submitBtn.disabled = true;
        const originalBtnText = submitBtn.textContent;
        submitBtn.textContent = 'Calcul en cours…';

        clearMapOverlays();

        const city = document.getElementById('city').value;
        const massif = document.getElementById('massif').value;
        const level = document.getElementById('level').value;
        const randomness = document.getElementById('randomness').value;
        const departure_datetime = document.getElementById('departure_datetime').value;
        const return_datetime = document.getElementById('return_datetime').value;

        const url = `/get_route/?city=${encodeURIComponent(city)}&massif=${encodeURIComponent(massif)}&level=${encodeURIComponent(level)}&randomness=${encodeURIComponent(randomness)}&departure_datetime=${encodeURIComponent(departure_datetime)}&return_datetime=${encodeURIComponent(return_datetime)}`;

        try {
            const response = await fetch(url);
            if (!response.ok) throw new Error('Erreur lors de la récupération du tracé');
            const data = await response.json();

            if (!data.features || data.features.length === 0) {
                alert("Aucun itinéraire trouvé !");
                return;
            }

            // GeoJSON
            currentLayer = L.geoJSON(data, { style: { color: '#ef8409', weight: 4, opacity: 0.9 } }).addTo(map);

            currentLayer.eachLayer(layer => {
                const coords = layer.getLatLngs();
                const startIcon = L.icon({ iconUrl: "https://raw.githubusercontent.com/pointhi/leaflet-color-markers/master/img/marker-icon-blue.png", iconSize: [25, 41], iconAnchor: [12, 41] });
                const endIcon = L.icon({ iconUrl: "https://raw.githubusercontent.com/pointhi/leaflet-color-markers/master/img/marker-icon-orange.png", iconSize: [25, 41], iconAnchor: [12, 41] });

                startMarker = L.marker(coords[0], { icon: startIcon }).addTo(map).bindPopup("Départ");
                endMarker = L.marker(coords[coords.length-1], { icon: endIcon }).addTo(map).bindPopup("Arrivée");

                if (L.PolylineDecorator) {
                    arrowDecorator = L.polylineDecorator(layer, {
                        patterns: [{ offset: 25, repeat: 250, symbol: L.Symbol.arrowHead({ pixelSize: 12, polygon: true, pathOptions: { color: '#ef8409', fillOpacity: 1, weight: 2 }})}]
                    }).addTo(map);
                }
            });

            map.fitBounds(currentLayer.getBounds());


            // Masquer formulaire
            const formModal = document.getElementById('form-modal');
            formModal.classList.add('collapsed');

            const props = data.features[0].properties;

            // === Modale Résumé ===
            const summaryModal = document.getElementById('modal-summary');
            summaryModal.innerHTML = `
                <div class="modal-header">
                    <h3>🗺️ Distance et dénivelé</h3>
                    <button class="toggle-btn">▲</button>
                </div>
                <div class="modal-body">
                    <div id="elevation-div"></div>
                    <div id="elevation-legend" class="custom-legend"></div>
                </div>
            `;
            initElevationInSummary();

            // État initial : Résumé déplié
            summaryModal.classList.remove('collapsed');
            summaryModal.querySelector('.toggle-btn').textContent = '▲';

            // === Modales Aller / Retour ===
            ['go', 'back'].forEach(type => {
                const modal = document.getElementById('modal-' + type);
                modal.innerHTML = `
                    <div class="modal-header">
                        <h3>${type === 'go' ? '➡️🚊 Aller' : '⬅️🚊 Retour'}</h3>
                        <button class="toggle-btn">▼</button>
                    </div>
                    <div class="modal-body"></div>
                `;

                if (props['transit_' + type]) {
                    afficherTransit(props['transit_' + type], modal.querySelector('.modal-body'));
                }

                // État initial : Aller et Retour repliés
                modal.classList.add('collapsed');
                modal.querySelector('.toggle-btn').textContent = '▼';
            });


            // === Attacher toggles exclusifs à toutes les modales ===
            ['go','back','summary'].forEach(type => {
                const modal = document.getElementById('modal-' + type);
                addToggleExclusive(modal);
            });

        } catch (err) {
            alert(err.message);
            console.error(err);
        } finally {
            submitBtn.disabled = false;
            submitBtn.textContent = originalBtnText;
        }
    });

});
