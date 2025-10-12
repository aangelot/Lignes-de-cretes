document.addEventListener('DOMContentLoaded', () => {
    // === Initialisation de la carte ===
    const map = L.map('map').setView([45.36, 5.79], 12);

    // Fonds de carte
    const osm = L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
        attribution: '&copy; OpenStreetMap contributors'
    });
    const satellite = L.tileLayer('https://{s}.google.com/vt/lyrs=s&x={x}&y={y}&z={z}', {
        maxZoom: 20,
        subdomains: ['mt0','mt1','mt2','mt3'],
        attribution: '&copy; <a href="https://www.google.com/earth/">Google</a>'
    });
    const topo = L.tileLayer('https://{s}.tile.opentopomap.org/{z}/{x}/{y}.png', {
        maxZoom: 17,
        attribution: 'Map data: &copy; <a href="https://www.opentopomap.org/">OpenTopoMap</a>, &copy; OpenStreetMap contributors'
    });

    osm.addTo(map);

    const baseMaps = { "OSM": osm, "Satellite": satellite, "OpenTopoMap": topo };
    L.control.layers(baseMaps).addTo(map);

    // === Variables globales pour gestion des overlays ===
    let currentLayer = null;
    let startMarker = null;
    let endMarker = null;
    let arrowDecorator = null;
    let controlElevation = null;

    const elevationOptions = {
        elevationDiv: "#elevation-div",
        theme: "steelblue-theme",
        width: 600,
        height: 180,
        collapsed: false,
        followMarker: true,
        autofitBounds: true,
        time: false,
        waypoints: false,
        speed: false,
        altitude: true,
        distance: true
    };

    // Initialisation du contrôle elevation
    function initElevationControl() {
        controlElevation = L.control.elevation(elevationOptions).addTo(map);
    }
    initElevationControl();

    // Slider randomness
    const slider = document.getElementById('randomness');
    const display = document.getElementById('randomness-value');
    display.textContent = slider.value;
    slider.addEventListener('input', () => {
        display.textContent = slider.value;
    });

    // === Fonction pour nettoyer la carte ===
    function clearMapOverlays() {
        if (currentLayer) { map.removeLayer(currentLayer); currentLayer = null; }
        if (startMarker) { map.removeLayer(startMarker); startMarker = null; }
        if (endMarker) { map.removeLayer(endMarker); endMarker = null; }
        if (arrowDecorator) { map.removeLayer(arrowDecorator); arrowDecorator = null; }
    }

    // === Fonction pour reset l’elevation control ===
    function resetElevationControl() {
        if (controlElevation && typeof controlElevation.remove === "function") {
            map.removeControl(controlElevation);
        }
        const elevDiv = document.querySelector("#elevation-div");
        if (elevDiv) elevDiv.innerHTML = "";
        initElevationControl();
    }

    // === Soumission du formulaire ===
    document.getElementById('trek-form').addEventListener('submit', async function (e) {
        e.preventDefault();

        const submitBtn = document.getElementById('submit-btn');
        submitBtn.disabled = true;
        const originalBtnText = submitBtn.textContent;
        submitBtn.textContent = 'Calcul en cours…';

        clearMapOverlays();
        resetElevationControl();

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

            const container = document.getElementById('transit-info');
            container.innerHTML = "";

            if (!data.features || data.features.length === 0) {
                container.innerHTML = "<p style='color:red;'>Désolé, aucun itinéraire n'a été trouvé, veuillez réessayer.</p>";
                return;
            }

            // Ajouter GeoJSON sur la carte
            currentLayer = L.geoJSON(data, {
                style: { color: '#ef8409', weight: 4, opacity: 0.9 }
            }).addTo(map);

            // Ajouter au plugin elevation
            controlElevation.addData(data);

            // Ajouter markers et flèches
            currentLayer.eachLayer(layer => {
                const coords = layer.getLatLngs();
                const startIcon = L.icon({
                    iconUrl: "https://raw.githubusercontent.com/pointhi/leaflet-color-markers/master/img/marker-icon-blue.png",
                    iconSize: [25, 41],
                    iconAnchor: [12, 41],
                    popupAnchor: [1, -34],
                    shadowUrl: "https://unpkg.com/leaflet@1.9.4/dist/images/marker-shadow.png"
                });
                const endIcon = L.icon({
                    iconUrl: "https://raw.githubusercontent.com/pointhi/leaflet-color-markers/master/img/marker-icon-orange.png",
                    iconSize: [25, 41],
                    iconAnchor: [12, 41],
                    popupAnchor: [1, -34],
                    shadowUrl: "https://unpkg.com/leaflet@1.9.4/dist/images/marker-shadow.png"
                });

                startMarker = L.marker(coords[0], { icon: startIcon }).addTo(map).bindPopup("Départ");
                endMarker = L.marker(coords[coords.length-1], { icon: endIcon }).addTo(map).bindPopup("Arrivée");

                if (L.PolylineDecorator) {
                    arrowDecorator = L.polylineDecorator(layer, {
                        patterns: [{
                            offset: 25,
                            repeat: 250,
                            symbol: L.Symbol.arrowHead({ pixelSize: 12, polygon: true, pathOptions: { color: '#ef8409', fillOpacity:1, weight:2 }})
                        }]
                    }).addTo(map);
                }
            });

            map.fitBounds(currentLayer.getBounds());

            // Affichage distance et dénivelé
            const props = data.features[0].properties;
            const distKm = (props.path_length / 1000).toFixed(1);
            container.innerHTML += `<p><strong>Distance :</strong> ${distKm} km</p>`;
            container.innerHTML += `<p><strong>Dénivelé positif :</strong> ${props.path_elevation ?? 'N/A'} m</p>`;

            // === Affichage transit (inchangé) ===
            function afficherTransit(transitData, titre) {
                let firstTransitStep = null;
                for (const leg of transitData.routes[0].legs) {
                    for (const step of leg.steps) {
                        if (step.travelMode === "TRANSIT") { firstTransitStep = step; break; }
                    }
                    if (firstTransitStep) break;
                }

                let dateStr = "";
                if (firstTransitStep) {
                    const depTimeObj = new Date(firstTransitStep.transitDetails.stopDetails.departureTime);
                    dateStr = depTimeObj.toLocaleDateString("fr-FR", {
                        weekday: "long", year: "numeric", month: "long", day: "numeric"
                    });
                }

                container.innerHTML += `<h2>${titre}${dateStr ? " – " + dateStr : ""}</h2>`;

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

                                container.innerHTML += `
                                    <p>
                                    Prendre le ${vehicle} ${line} à ${depStop} à ${depTime}, direction ${headsign}, arrivée à ${arrStop} à ${arrTime}. 
                                    Plus d'informations sur le <a href="${link}" target="_blank">site de l'agence</a>.
                                    </p>
                                `;
                            }
                        });
                    });
                });

                // Lien Google Maps (inchangé)
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
                container.innerHTML += `<hr>`;
            }


            data.features.forEach(feature => {
                if (feature.properties.transit_go) afficherTransit(feature.properties.transit_go, "Aller");
                if (feature.properties.transit_back) afficherTransit(feature.properties.transit_back, "Retour");
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
