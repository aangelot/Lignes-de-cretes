document.addEventListener('DOMContentLoaded', () => {

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

    // Slider randomness
    const slider = document.getElementById('randomness');
    const display = document.getElementById('randomness-value');
    display.textContent = slider.value;
    slider.addEventListener('input', () => display.textContent = slider.value);

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

        let firstCoords = null;
        let lastCoords = null;

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

            // fermer toutes les autres modales
            document.querySelectorAll('.floating-modal').forEach(m => {
                if (m !== modal) {
                    m.classList.add('collapsed');
                    const b = m.querySelector('.toggle-btn');
                    if (b) b.textContent = '▼';
                }
            });

            // bascule de l'état de la modale cliquée
            if (isCollapsed) {
                modal.classList.remove('collapsed');
                btn.textContent = '▲';
            } else {
                modal.classList.add('collapsed');
                btn.textContent = '▼';
            }
        });
    }

    document.querySelectorAll('.floating-modal').forEach(modal => {
        addToggleExclusive(modal);
    });

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
                    <button class="toggle-btn">▼</button>
                </div>
                <div class="modal-body">
                    <p><strong>Distance :</strong> ${(props.path_length/1000).toFixed(1)} km</p>
                    <p><strong>Dénivelé positif :</strong> ${props.path_elevation ?? 'N/A'} m</p>
                </div>
            `;

            // Modales Aller / Retour
            ['go','back'].forEach(type => {
                const modal = document.getElementById('modal-' + type);
                modal.innerHTML = `
                    <div class="modal-header">
                        <h3>${type === 'go' ? '➡️ Aller' : '⬅️ Retour'}</h3>
                        <button class="toggle-btn">▲</button>
                    </div>
                    <div class="modal-body"></div>
                `;
            

                if (props['transit_' + type]) 
                    afficherTransit(props['transit_' + type], modal.querySelector('.modal-body'));

                // Etat initial : Aller déplié, Résumé et Retour pliés
                if (type === 'go') {
                    modal.classList.remove('collapsed'); // déplié
                    modal.querySelector('.toggle-btn').textContent = '▲';
                } else {
                    modal.classList.add('collapsed'); // plié
                    modal.querySelector('.toggle-btn').textContent = '▼';
                }
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
