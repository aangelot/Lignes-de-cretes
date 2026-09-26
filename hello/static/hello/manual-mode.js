/**
 * Mode manuel : l'utilisateur construit son trek étape par étape.
 *
 *   1. Départ : les arrêts du massif sont colorés selon le temps estimé depuis sa
 *      gare ; il en choisit un, le trajet aller est calculé et affiché aussitôt.
 *   2. Tracé  : les points d'intérêt du massif s'affichent ; chaque POI ajouté
 *      prolonge le tracé, distance et dénivelé se mettent à jour.
 *   3. Retour : les arrêts s'affichent de nouveau ; au clic, la marche depuis le
 *      dernier POI est prévisualisée. L'arrêt validé, le trajet retour est calculé
 *      et le trek complet s'affiche comme en mode automatique (renderRoute).
 *
 * Les étapes s'affichent dans la modale formulaire ; les résultats arrivent au fil
 * de l'eau dans les modales existantes (aller, résumé, retour). L'affichage des
 * trajets réutilise les briques d'index.js exposées sur window.lignesDeCretes.
 */
(function () {
  // Rampe séquentielle bleue (une teinte, clair → foncé) : plus c'est foncé, plus
  // c'est loin. Le clair démarre au pas 250 pour rester visible sur le fond de carte.
  const RAMP = ['#86b6ef', '#6da7ec', '#5598e7', '#3987e5', '#2a78d6',
                '#256abf', '#1c5cab', '#184f95', '#104281', '#0d366b'];
  const UNKNOWN_COLOR = '#9a9a9a';
  const FAILED_COLOR = '#d32f2f';
  const HIGHLIGHT_COLOR = '#ef8409';

  const STEPS = [
    { key: 'go', label: 'Départ' },
    { key: 'hike', label: 'Tracé' },
    { key: 'back', label: 'Retour' },
  ];

  document.addEventListener('DOMContentLoaded', () => {
    const api = window.lignesDeCretes;
    const form = document.getElementById('trek-form');
    const panel = document.getElementById('manual-panel');
    if (!api || !form || !panel) return;

    const map = api.map;
    const massifSelect = document.getElementById('massif');
    const addressInput = document.getElementById('address');
    const depInput = document.getElementById('departure_datetime');
    const retInput = document.getElementById('return_datetime');
    const dateError = document.getElementById('date-error');

    // Canvas : plusieurs centaines d'arrêts restent fluides au zoom et au survol.
    const stopsRenderer = L.canvas({ padding: 0.5 });

    const initialState = () => ({
      step: 'go',
      stops: null,          // réponse de /manual/stops/
      stopsLoading: false,
      go: null,             // réponse de /manual/transit_go/
      goLoadingId: null,    // arrêt dont le trajet aller est en cours de calcul
      failedStops: new Set(),
      pois: null,           // POI du massif (/manual/pois/)
      hikeStack: [],        // un tracé par point ajouté : annuler = dépiler, sans appel
      hikeLoadingId: null,  // POI dont l'ajout est en cours de calcul
      failedBackStops: new Set(),
      backPreviews: new Map(),   // arrêt → { hike } ou { error } : marche depuis le dernier POI
      previewLoading: new Set(),
      backLoadingId: null,  // arrêt dont le trajet retour est en cours de calcul
      final: null,          // réponse de /manual/finish/ : trek complet affiché
      error: '',
    });
    const state = initialState();

    let stopsLayer = null;
    let selectedStopId = null;
    const markersById = new Map();
    let startMarker = null;

    let poiLayer = null;
    const poiMarkersById = new Map();
    let trackLayer = null;
    let trackArrows = null;
    let previewLayer = null;

    // ------------------------------------------------------------------ utils

    const isManual = () => form.classList.contains('mode-manual');

    function escapeHtml(s) {
      return String(s ?? '').replace(/[&<>"']/g, c => ({
        '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;',
      }[c]));
    }

    function formatDuration(min) {
      if (min == null) return '?';
      const m = Math.round(min);
      if (m < 60) return `${m} min`;
      return `${Math.floor(m / 60)} h ${String(m % 60).padStart(2, '0')}`;
    }

    function formatKm(m) {
      return (m / 1000).toLocaleString('fr-FR', { minimumFractionDigits: 1, maximumFractionDigits: 1 }) + ' km';
    }

    function formatTime(iso) {
      return new Date(iso).toLocaleTimeString('fr-FR', { hour: '2-digit', minute: '2-digit' });
    }

    function hexToRgb(hex) {
      const n = parseInt(hex.slice(1), 16);
      return [(n >> 16) & 255, (n >> 8) & 255, n & 255];
    }

    /** Couleur de la rampe pour t ∈ [0, 1], interpolée entre deux pas. */
    function rampColor(t) {
      const x = Math.min(1, Math.max(0, t)) * (RAMP.length - 1);
      const i = Math.min(Math.floor(x), RAMP.length - 2);
      const f = x - i;
      const a = hexToRgb(RAMP[i]);
      const b = hexToRgb(RAMP[i + 1]);
      const c = a.map((v, k) => Math.round(v + (b[k] - v) * f));
      return `rgb(${c[0]}, ${c[1]}, ${c[2]})`;
    }

    /**
     * Position de chaque durée dans la distribution (0 = la plus courte, 1 = la plus
     * longue). On colore par rang plutôt que par valeur : quelques durées aberrantes
     * (plus de 20 h) écraseraient sinon tout le dégradé sur ses premières teintes.
     * Conséquence utile : la médiane tombe pile au milieu de la légende.
     */
    function rankPositions(durations) {
      const sorted = [...durations].sort((a, b) => a - b);
      const n = sorted.length;
      const lowerBound = v => { let lo = 0, hi = n; while (lo < hi) { const m = (lo + hi) >> 1; if (sorted[m] < v) lo = m + 1; else hi = m; } return lo; };
      const upperBound = v => { let lo = 0, hi = n; while (lo < hi) { const m = (lo + hi) >> 1; if (sorted[m] <= v) lo = m + 1; else hi = m; } return lo; };
      return v => {
        if (n <= 1) return 0;
        const mid = (lowerBound(v) + upperBound(v) - 1) / 2;
        return mid / (n - 1);
      };
    }

    function formReady() {
      return Boolean(
        massifSelect.value && addressInput.value.trim()
        && depInput.value && retInput.value && !dateError.textContent
      );
    }

    function queryParams(extra) {
      const params = new URLSearchParams({
        massif: massifSelect.value,
        address: addressInput.value.trim(),
        departure_datetime: depInput.value,
        return_datetime: retInput.value,
        ...extra,
      });
      return params.toString();
    }

    async function fetchJson(url) {
      const resp = await fetch(url);
      const data = await resp.json().catch(() => ({}));
      if (!resp.ok) {
        const err = new Error(data.error || 'Erreur serveur.');
        err.payload = data;
        throw err;
      }
      return data;
    }

    // --------------------------------------------------------------- modales

    function clearResultModal(type) {
      const modal = document.getElementById('modal-' + type);
      if (!modal) return;
      modal.innerHTML = '';
      modal.classList.add('collapsed');
    }

    function warningsHtml(warnings) {
      if (!warnings || !warnings.length) return '';
      return `<div class="manual-warning">${warnings
        .map(w => `<p>⚠️ ${escapeHtml(w)}</p>`).join('')}</div>`;
    }

    function renderGoModal(go) {
      const modal = document.getElementById('modal-go');
      modal.innerHTML = `
        <div class="modal-header">
          <h3>➡️🚊 Aller en transports</h3>
          <button class="toggle-btn" type="button">▼</button>
        </div>
        <div class="modal-body">${warningsHtml(go.warnings)}</div>
      `;
      api.afficherTransit(go.transit_go, modal.querySelector('.modal-body'));
      api.addToggleExclusive(modal);
      // Repliée : le formulaire, qui porte la suite des étapes, reste au premier plan.
      modal.classList.add('collapsed');
    }

    // ----------------------------------------------------------------- arrêts

    /** Arrêts sans trajet possible : on ne les confond pas entre aller et retour. */
    const failedSet = () => (state.step === 'back' ? state.failedBackStops : state.failedStops);

    function styleFor(stop) {
      const selected = stop.id === selectedStopId;
      const failed = failedSet().has(stop.id);
      return {
        renderer: stopsRenderer,
        radius: selected ? 9 : 6,
        color: selected ? HIGHLIGHT_COLOR : '#ffffff',
        weight: selected ? 3 : 1.5,
        fillColor: failed ? FAILED_COLOR : stop._color,
        fillOpacity: failed ? 0.5 : 0.95,
      };
    }

    function refreshMarker(stopId) {
      const entry = markersById.get(stopId);
      if (entry) entry.marker.setStyle(styleFor(entry.stop));
    }

    function selectStop(stopId) {
      const previous = selectedStopId;
      selectedStopId = stopId;
      if (previous) refreshMarker(previous);
      if (stopId) {
        refreshMarker(stopId);
        const entry = markersById.get(stopId);
        if (entry) entry.marker.bringToFront();
      }
    }

    /** « ≈ 2 h 06 depuis Lyon » à l'aller, « ≈ 2 h 06 vers Lyon » au retour. */
    function durationLabel(stop) {
      if (stop.duration_min == null) return 'Durée inconnue';
      const direction = state.step === 'back' ? 'vers' : 'depuis';
      return `≈ ${formatDuration(stop.duration_min)} ${direction} ${state.stops.hub}`;
    }

    function stopInfoElement(stop) {
      const el = document.createElement('div');
      el.className = 'manual-stop-popup';
      const lines = [`<strong>${escapeHtml(durationLabel(stop))}</strong>`];
      if (stop.elevation != null) lines.push(`Altitude : ${Math.round(stop.elevation)} m`);
      el.innerHTML = lines.map(l => `<div>${l}</div>`).join('');
      return el;
    }

    /**
     * Clic sur un bouton de popup. Le traitement redessine aussitôt la popup (état
     * « en cours ») : le bouton quitte le DOM pendant le clic, Leaflet le prend alors
     * pour un clic sur la carte et ferme la popup. On arrête donc sa propagation.
     */
    function onPopupButton(btn, handler) {
      btn.addEventListener('click', e => {
        L.DomEvent.stop(e);
        handler();
      });
    }

    function refreshStopPopup(stopId) {
      const entry = markersById.get(stopId);
      if (entry && entry.marker.isPopupOpen()) {
        entry.marker.setPopupContent(() => stopPopupContent(entry.stop));
      }
      // Arrêt de départ choisi comme arrêt retour : sa popup est celle du « D »
      if (startMarker && state.go && stopId === state.go.stop.id && startMarker.isPopupOpen()) {
        startMarker.getPopup().update();
      }
    }

    function stopPopupContent(stop) {
      if (state.step === 'back') return backStopPopupContent(stop);
      const el = stopInfoElement(stop);

      if (state.failedStops.has(stop.id)) {
        const p = document.createElement('div');
        p.className = 'manual-stop-popup-error';
        p.textContent = 'Aucun trajet trouvé vers cet arrêt à cette date.';
        el.appendChild(p);
        return el;
      }

      const btn = document.createElement('button');
      btn.type = 'button';
      const loading = state.goLoadingId === stop.id;
      btn.textContent = loading ? 'Recherche du trajet…' : 'Partir de cet arrêt';
      btn.disabled = Boolean(state.goLoadingId);
      onPopupButton(btn, () => validateGoStop(stop));
      el.appendChild(btn);
      return el;
    }

    function drawStops() {
      removeStopsLayer();
      const { stops } = state.stops;
      const known = stops.filter(s => s.duration_min != null).map(s => s.duration_min);
      const position = rankPositions(known);

      // Les plus lointains d'abord : les arrêts proches, les plus utiles, restent au-dessus.
      const ordered = [...stops].sort((a, b) =>
        (b.duration_min ?? Infinity) - (a.duration_min ?? Infinity));

      stopsLayer = L.layerGroup();
      ordered.forEach(stop => {
        stop._color = stop.duration_min == null ? UNKNOWN_COLOR : rampColor(position(stop.duration_min));
        const marker = L.circleMarker([stop.lat, stop.lon], styleFor(stop));
        marker.bindTooltip(escapeHtml(durationLabel(stop)), { direction: 'top', offset: [0, -6] });
        marker.bindPopup(() => stopPopupContent(stop), {
          closeButton: false,
          className: 'manual-popup-wrapper',
        });
        marker.on('click', () => {
          selectStop(stop.id);
          if (state.step === 'back') previewBack(stop);
        });
        marker.on('popupclose', () => {
          if (selectedStopId !== stop.id) return;
          selectStop(null);
          removePreview();
        });
        markersById.set(stop.id, { marker, stop });
        stopsLayer.addLayer(marker);
      });
      stopsLayer.addTo(map);

      // Les arrêts prennent la carte : les contours des massifs capteraient les clics.
      if (window.massifOverlay) window.massifOverlay.hide();
    }

    function removeStopsLayer() {
      if (stopsLayer) map.removeLayer(stopsLayer);
      stopsLayer = null;
      markersById.clear();
      selectedStopId = null;
    }

    function setFormCollapsed(collapsed) {
      const formModal = document.getElementById('form-modal');
      formModal.classList.toggle('collapsed', collapsed);
      const btn = formModal.querySelector('.toggle-btn');
      if (btn) btn.textContent = collapsed ? '▼' : '▲';
    }

    /**
     * Sur mobile le formulaire recouvre la carte : on le replie pour laisser
     * choisir l'arrêt (la légende reste accessible en le rouvrant).
     */
    function collapseFormOnMobile() {
      if (window.matchMedia('(max-width: 768px)').matches) setFormCollapsed(true);
    }

    async function loadStops() {
      if (!formReady() || state.stopsLoading) return;
      state.stopsLoading = true;
      state.error = '';
      renderPanel();
      try {
        state.stops = await fetchJson(`/manual/stops/?${queryParams()}`);
        drawStops();
        collapseFormOnMobile();
      } catch (err) {
        state.error = err.message;
        console.error(err);
      } finally {
        state.stopsLoading = false;
        renderPanel();
      }
    }

    // ---------------------------------------------------------- trajet aller

    function showStartMarker(stop) {
      if (startMarker) map.removeLayer(startMarker);
      startMarker = L.marker([stop.lat, stop.lon], {
        icon: L.icon({
          iconUrl: '/static/hello/path_to_start_image.png',
          iconSize: [50, 50],
          iconAnchor: [25, 25],
          popupAnchor: [0, -25],
        }),
      }).addTo(map);

      // À l'étape retour, le « D » recouvre l'arrêt de départ : il en reprend la
      // popup, pour pouvoir y finir la randonnée (boucle).
      startMarker.bindPopup(() => {
        const departure = departureStop();
        return state.step === 'back' && departure
          ? backStopPopupContent(departure)
          : 'Départ : ' + escapeHtml(stop.name || 'arrêt choisi');
      }, { closeButton: false, className: 'manual-popup-wrapper' });
      startMarker.on('click', () => {
        const departure = departureStop();
        if (state.step !== 'back' || !departure) return;
        selectStop(departure.id);
        previewBack(departure);
      });
      startMarker.on('popupclose', () => {
        if (state.step !== 'back' || selectedStopId !== state.go.stop.id) return;
        selectStop(null);
        removePreview();
      });
    }

    /** Arrêt de départ tel que listé par /manual/stops/ (durée, altitude). */
    function departureStop() {
      if (!state.go || !state.stops) return null;
      return state.stops.stops.find(s => s.id === state.go.stop.id) || null;
    }

    async function validateGoStop(stop) {
      if (state.goLoadingId) return;
      state.goLoadingId = stop.id;
      state.error = '';
      renderPanel();
      const entry = markersById.get(stop.id);
      if (entry) entry.marker.setPopupContent(() => stopPopupContent(stop));

      try {
        const go = await fetchJson(`/manual/transit_go/?${queryParams({ stop_id: stop.id })}`);
        state.go = go;
        state.step = 'hike';
        map.closePopup();
        removeStopsLayer();
        showStartMarker(go.stop);
        renderGoModal(go);
        enterHikeStep();
      } catch (err) {
        if (err.payload && err.payload.no_transit) {
          state.failedStops.add(stop.id);
          refreshMarker(stop.id);
          state.error = 'Aucun trajet en transport en commun trouvé vers cet arrêt à cette date. Choisissez-en un autre.';
        } else {
          state.error = err.message;
          console.error(err);
        }
      } finally {
        state.goLoadingId = null;
        if (entry && map.hasLayer(entry.marker) && entry.marker.isPopupOpen()) {
          entry.marker.setPopupContent(() => stopPopupContent(stop));
        }
        renderPanel();
      }
    }

    /** Revient au choix de l'arrêt de départ, arrêts déjà chargés conservés. */
    function backToGoStep() {
      clearFinal();
      clearBack();
      clearHike();
      state.go = null;
      state.step = 'go';
      state.error = '';
      if (startMarker) { map.removeLayer(startMarker); startMarker = null; }
      clearResultModal('go');
      if (state.stops) drawStops();
      renderPanel();
    }

    // ----------------------------------------------------------------- tracé

    const currentHike = () => state.hikeStack[state.hikeStack.length - 1] || null;
    const currentPoiIds = () => (currentHike() ? currentHike().poiIds : []);

    function hikeParams(poiIds) {
      return new URLSearchParams({
        massif: massifSelect.value,
        stop_id: state.go.stop.id,
        pois: poiIds.join(','),
      }).toString();
    }

    function enterHikeStep() {
      state.hikeStack = [];
      loadPois();
      // Tracé vide : charge le graphe du massif côté serveur pendant que
      // l'utilisateur choisit son premier point, pour que ce clic soit rapide.
      fetch(`/manual/hike/?${hikeParams([])}`).catch(() => {});
    }

    async function loadPois() {
      try {
        const data = await fetchJson(`/manual/pois/?${new URLSearchParams({ massif: massifSelect.value })}`);
        if (state.step !== 'hike') return;
        state.pois = data.pois;
        drawPois();
      } catch (err) {
        state.error = err.message;
        console.error(err);
      }
      renderPanel();
    }

    /** Numéros d'ordre d'un POI dans le tracé (un POI peut être repris plus tard). */
    function positionsOf(poiId) {
      return currentPoiIds().reduce((acc, id, i) => (id === poiId ? [...acc, i + 1] : acc), []);
    }

    function poiIcon(poi) {
      const positions = positionsOf(poi.id);
      if (positions.length) {
        return L.divIcon({
          className: 'manual-poi-badge',
          html: `<span>${positions.join('·')}</span>`,
          iconSize: null,
          iconAnchor: [13, 13],
          popupAnchor: [0, -14],
        });
      }
      return L.icon({
        iconUrl: poi.type === 'summit' ? '/static/hello/summit.png' : '/static/hello/POI.png',
        iconSize: [28, 28],
        iconAnchor: [14, 14],
        popupAnchor: [0, -14],
      });
    }

    function poiLabel(poi) {
      return poi.type === 'summit' && poi.elevation
        ? `${poi.titre} (${poi.elevation} m)`
        : poi.titre;
    }

    function poiPopupContent(poi) {
      const el = document.createElement('div');
      el.className = 'manual-stop-popup';

      const title = document.createElement('strong');
      title.textContent = poiLabel(poi);
      el.appendChild(title);

      const positions = positionsOf(poi.id);
      if (positions.length) {
        const info = document.createElement('div');
        info.className = 'manual-popup-muted';
        info.textContent = `Déjà dans le tracé (point ${positions.join(', ')})`;
        el.appendChild(info);
      }

      const ids = currentPoiIds();
      const isLast = ids.length > 0 && ids[ids.length - 1] === poi.id;
      const btn = document.createElement('button');
      btn.type = 'button';
      btn.textContent = state.hikeLoadingId === poi.id
        ? 'Calcul du tracé…'
        : isLast ? 'Dernier point du tracé' : 'Ajouter au tracé';
      btn.disabled = isLast || state.hikeLoadingId !== null;
      onPopupButton(btn, () => addPoi(poi));
      el.appendChild(btn);
      return el;
    }

    function drawPois() {
      removePoiLayer();
      poiLayer = L.layerGroup();
      state.pois.forEach(poi => {
        const marker = L.marker([poi.lat, poi.lon], { icon: poiIcon(poi) });
        marker.bindTooltip(escapeHtml(poiLabel(poi)), { direction: 'top', offset: [0, -12] });
        marker.bindPopup(() => poiPopupContent(poi), {
          closeButton: false,
          className: 'manual-popup-wrapper',
        });
        poiMarkersById.set(poi.id, { marker, poi });
        poiLayer.addLayer(marker);
      });
      poiLayer.addTo(map);
    }

    /** Met à jour numéros et popups ouvertes après un ajout ou une annulation. */
    function refreshPois() {
      poiMarkersById.forEach(({ marker, poi }) => {
        marker.setIcon(poiIcon(poi));
        marker.setZIndexOffset(positionsOf(poi.id).length ? 1000 : 0);
        // Toujours une fonction : un contenu figé resterait affiché aux ouvertures suivantes
        if (marker.isPopupOpen()) marker.setPopupContent(() => poiPopupContent(poi));
      });
    }

    function removePoiLayer() {
      if (poiLayer) map.removeLayer(poiLayer);
      poiLayer = null;
      poiMarkersById.clear();
    }

    function removeTrack() {
      if (trackLayer) { map.removeLayer(trackLayer); trackLayer = null; }
      if (trackArrows) { map.removeLayer(trackArrows); trackArrows = null; }
    }

    function drawTrack() {
      removeTrack();
      const hike = currentHike();
      if (!hike || hike.coordinates.length < 2) return;

      const latlngs = hike.coordinates.map(([lon, lat]) => [lat, lon]);
      trackLayer = L.polyline(latlngs, { color: HIGHLIGHT_COLOR, weight: 4, opacity: 0.9 }).addTo(map);
      if (L.polylineDecorator) {
        // Mêmes flèches de sens que le tracé du mode automatique
        trackArrows = L.polylineDecorator(trackLayer, {
          patterns: [{ offset: 25, repeat: 250, symbol: L.Symbol.arrowHead({
            pixelSize: 12, polygon: true,
            pathOptions: { color: HIGHLIGHT_COLOR, fillOpacity: 1, weight: 2 },
          }) }],
        }).addTo(map);
      }
    }

    async function addPoi(poi) {
      if (state.hikeLoadingId !== null) return;
      const poiIds = [...currentPoiIds(), poi.id];
      state.hikeLoadingId = poi.id;
      state.error = '';
      refreshPois();
      renderPanel();
      try {
        const hike = await fetchJson(`/manual/hike/?${hikeParams(poiIds)}`);
        if (state.step !== 'hike') return;
        state.hikeStack.push({ ...hike, poiIds });
        map.closePopup();
        drawTrack();
      } catch (err) {
        state.error = err.payload && err.payload.unreachable
          ? `${poi.titre} : ce point n'est pas relié au tracé par les sentiers connus. Choisissez-en un autre.`
          : err.message;
        console.error(err);
      } finally {
        state.hikeLoadingId = null;
        refreshPois();
        renderPanel();
      }
    }

    function undoPoi() {
      if (state.hikeLoadingId !== null) return;
      state.hikeStack.pop();
      state.error = '';
      drawTrack();
      refreshPois();
      renderPanel();
    }

    function restartHike() {
      if (state.hikeLoadingId !== null) return;
      state.hikeStack = [];
      state.error = '';
      drawTrack();
      refreshPois();
      renderPanel();
    }

    /** Efface POI et tracé de la carte. */
    function clearHike() {
      state.hikeStack = [];
      state.hikeLoadingId = null;
      state.pois = null;
      removePoiLayer();
      drawTrack();
    }

    // ---------------------------------------------------------------- retour

    function enterBackStep() {
      if (!currentPoiIds().length || state.hikeLoadingId !== null) return;
      state.step = 'back';
      state.error = '';
      state.backPreviews = new Map();
      map.closePopup();
      removePoiLayer();
      drawStops();
      collapseFormOnMobile();
      renderPanel();
    }

    /** Retour à l'étape tracé, pour ajouter ou retirer des points. */
    function backToHikeStep() {
      clearBack();
      state.step = 'hike';
      state.error = '';
      if (state.pois) drawPois(); else loadPois();
      renderPanel();
    }

    async function previewBack(stop) {
      const id = stop.id;
      if (state.backPreviews.has(id)) { drawPreview(id); return; }
      if (state.previewLoading.has(id)) return;

      state.previewLoading.add(id);
      refreshStopPopup(id);
      try {
        const hike = await fetchJson(
          `/manual/hike/?${hikeParams(currentPoiIds())}&${new URLSearchParams({ end_stop_id: id })}`
        );
        state.backPreviews.set(id, { hike });
      } catch (err) {
        state.backPreviews.set(id, {
          error: err.payload && err.payload.unreachable
            ? 'Cet arrêt n\'est pas relié au tracé par les sentiers connus.'
            : err.message,
        });
      } finally {
        state.previewLoading.delete(id);
      }
      if (state.step !== 'back') return;
      refreshStopPopup(id);
      if (selectedStopId === id) drawPreview(id);
    }

    /** Tronçon dernier POI → arrêt, en pointillés tant qu'il n'est pas validé. */
    function drawPreview(stopId) {
      removePreview();
      const preview = state.backPreviews.get(stopId);
      const hike = currentHike();
      if (!preview || !preview.hike || !hike) return;
      const segment = preview.hike.coordinates.slice(hike.coordinates.length - 1);
      if (segment.length < 2) return;
      previewLayer = L.polyline(segment.map(([lon, lat]) => [lat, lon]), {
        color: HIGHLIGHT_COLOR, weight: 4, opacity: 0.85, dashArray: '6 8',
      }).addTo(map);
    }

    function removePreview() {
      if (previewLayer) map.removeLayer(previewLayer);
      previewLayer = null;
    }

    function backStopPopupContent(stop) {
      const el = stopInfoElement(stop);
      const hike = currentHike();
      const preview = state.backPreviews.get(stop.id);

      const walk = document.createElement('div');
      walk.className = 'manual-popup-walk';
      if (!preview) {
        walk.textContent = 'Calcul de la marche depuis le dernier point…';
      } else if (preview.error) {
        walk.className = 'manual-stop-popup-error';
        walk.textContent = preview.error;
      } else {
        const extraDistance = Math.max(0, preview.hike.distance_m - hike.distance_m);
        const extraAscent = Math.max(0, preview.hike.ascent_m - hike.ascent_m);
        walk.innerHTML = `
          <div>Marche depuis le dernier point : <strong>+ ${formatKm(extraDistance)}</strong>, + ${extraAscent} m D+</div>
          <div class="manual-popup-muted">Total : ${formatKm(preview.hike.distance_m)} · ${preview.hike.ascent_m} m D+</div>`;
      }
      el.appendChild(walk);

      if (state.failedBackStops.has(stop.id)) {
        const p = document.createElement('div');
        p.className = 'manual-stop-popup-error';
        p.textContent = 'Aucun trajet retour trouvé depuis cet arrêt.';
        el.appendChild(p);
        return el;
      }
      if (!preview || preview.error) return el;

      const btn = document.createElement('button');
      btn.type = 'button';
      btn.textContent = state.backLoadingId === stop.id ? 'Recherche du trajet retour…' : 'Finir à cet arrêt';
      btn.disabled = state.backLoadingId !== null;
      onPopupButton(btn, () => validateBackStop(stop));
      el.appendChild(btn);
      return el;
    }

    async function validateBackStop(stop) {
      if (state.backLoadingId !== null) return;
      state.backLoadingId = stop.id;
      state.error = '';
      refreshStopPopup(stop.id);
      renderPanel();

      try {
        const data = await fetchJson(`/manual/finish/?${queryParams({
          stop_id: state.go.stop.id,
          pois: currentPoiIds().join(','),
          return_stop_id: stop.id,
        })}`);
        if (state.step !== 'back') return;
        // Le serveur ne recalcule pas l'aller : on réinjecte celui déjà obtenu.
        data.result.features[0].properties.transit_go = state.go.transit_go;

        map.closePopup();
        clearBack();
        removeTrack();
        if (startMarker) { map.removeLayer(startMarker); startMarker = null; }
        state.final = data;
        state.step = 'done';
        await api.renderRoute(data.result);
        // renderRoute replie le formulaire sans mettre à jour son chevron
        setFormCollapsed(true);
      } catch (err) {
        if (err.payload && err.payload.no_transit) {
          state.failedBackStops.add(stop.id);
          refreshMarker(stop.id);
        }
        state.error = err.message;
        console.error(err);
      } finally {
        state.backLoadingId = null;
        refreshStopPopup(stop.id);
        renderPanel();
      }
    }

    /** Efface arrêts, aperçu et calculs de l'étape retour. */
    function clearBack() {
      removeStopsLayer();
      removePreview();
      state.backPreviews = new Map();
      state.previewLoading = new Set();
      state.backLoadingId = null;
    }

    /** Efface le trek complet affiché par renderRoute (couches, modales, GPX). */
    function clearFinal() {
      if (!state.final) return;
      state.final = null;
      api.resetResults();
      // resetResults réaffiche les contours des massifs : le trek garde la carte.
      if (window.massifOverlay) window.massifOverlay.hide();
    }

    /** Quitte le résultat final pour revenir à l'étape `step` ('hike' ou 'back'). */
    function reopenStep(step) {
      clearFinal();
      renderGoModal(state.go);
      showStartMarker(state.go.stop);
      drawTrack();
      if (step === 'back') {
        state.step = 'hike'; // enterBackStep part de l'étape tracé
        enterBackStep();
      } else {
        backToHikeStep();
      }
    }

    // -------------------------------------------------------------- panneau

    function stepperHtml() {
      const current = state.step === 'done'
        ? STEPS.length
        : STEPS.findIndex(s => s.key === state.step);
      return `<ol class="manual-stepper">${STEPS.map((s, i) => {
        const cls = i < current ? 'is-done' : i === current ? 'is-active' : '';
        return `<li class="${cls}"><span>${i + 1}</span>${s.label}</li>`;
      }).join('')}</ol>`;
    }

    function legendHtml() {
      const { hub, stats, stops } = state.stops;
      const titlePrefix = state.step === 'back'
        ? 'Temps de trajet retour estimé vers'
        : 'Temps de trajet estimé depuis';
      const unknown = stops.filter(s => s.duration_min == null).length;
      const address = addressInput.value.trim();
      const proxyNote = hub && hub.toLowerCase() !== address.toLowerCase()
        ? `<div class="manual-legend-note">Estimation depuis ${escapeHtml(hub)}, la gare de référence la plus proche de ${escapeHtml(address)}.</div>`
        : '';

      if (!stats) {
        return `<div class="manual-legend">
          <div class="manual-legend-title">Aucune durée estimable depuis ${escapeHtml(hub)} : tous les arrêts sont en gris.</div>
        </div>`;
      }

      return `<div class="manual-legend">
        <div class="manual-legend-title">${titlePrefix} <strong>${escapeHtml(hub)}</strong></div>
        <div class="manual-legend-bar" style="background: linear-gradient(to right, ${RAMP.join(', ')});"></div>
        <div class="manual-legend-ticks">
          <span>min<b>${formatDuration(stats.min)}</b></span>
          <span>médiane<b>${formatDuration(stats.median)}</b></span>
          <span>max<b>${formatDuration(stats.max)}</b></span>
        </div>
        ${unknown ? `<div class="manual-legend-note"><i class="manual-dot" style="background:${UNKNOWN_COLOR}"></i>${unknown} arrêt${unknown > 1 ? 's' : ''} sans estimation</div>` : ''}
        ${proxyNote}
      </div>`;
    }

    function goStepHtml() {
      if (!state.stops) {
        return `
          <p class="manual-hint">Choisissez un massif, votre gare et vos dates, puis affichez les arrêts de transport en commun du massif.</p>
          <button type="button" class="manual-primary" data-action="load-stops" ${formReady() && !state.stopsLoading ? '' : 'disabled'}>
            ${state.stopsLoading ? 'Chargement des arrêts…' : 'Afficher les arrêts du massif'}
          </button>`;
      }
      return `
        ${legendHtml()}
        <p class="manual-hint">${state.goLoadingId
          ? 'Recherche du trajet aller…'
          : 'Cliquez sur un arrêt de la carte pour en faire votre point de départ.'}</p>`;
    }

    function goSummaryHtml() {
      const go = state.go;
      const steps = go.transit_go.routes[0].legs[0].steps.filter(s => s.travelMode === 'TRANSIT');
      const arrival = steps.length ? formatTime(steps[steps.length - 1].transitDetails.stopDetails.arrivalTime) : '';
      return `
        <div class="manual-done">
          ✅ Départ : <strong>${escapeHtml(go.stop.name || 'arrêt choisi')}</strong>
          ${arrival ? `<span>arrivée à ${arrival}</span>` : ''}
          <button type="button" class="manual-link" data-action="change-go">Changer d'arrêt de départ</button>
        </div>
        ${warningsHtml(go.warnings)}`;
    }

    function counterHtml(distanceM, ascentM, points) {
      return `
        <div class="manual-counter">
          <div><b>${formatKm(distanceM)}</b><span>distance</span></div>
          <div><b>${ascentM} m</b><span>dénivelé +</span></div>
          <div><b>${points}</b><span>point${points > 1 ? 's' : ''}</span></div>
        </div>`;
    }

    function hikeStepHtml() {
      const hike = currentHike();
      const ids = currentPoiIds();
      const busy = state.hikeLoadingId !== null;
      const poisById = new Map((state.pois || []).map(p => [p.id, p]));

      const counter = counterHtml(hike ? hike.distance_m : 0, hike ? hike.ascent_m : 0, ids.length);

      const list = ids.length
        ? `<ol class="manual-poi-list">${ids.map(id =>
            `<li>${escapeHtml(poiLabel(poisById.get(id) || { titre: 'Point' }))}</li>`).join('')}</ol>`
        : '';

      const hint = busy
        ? 'Calcul du tracé…'
        : !state.pois
          ? 'Chargement des points d\'intérêt…'
          : ids.length
            ? 'Ajoutez un autre point d\'intérêt, ou terminez le tracé.'
            : 'Cliquez sur un point d\'intérêt de la carte pour l\'ajouter à votre tracé.';

      const elevationWarning = hike && hike.elevation_failed
        ? warningsHtml(['Altitudes indisponibles : le dénivelé n\'est pas fiable.'])
        : '';

      return `
        <h4 class="manual-subtitle">Tracé de la randonnée</h4>
        ${counter}
        ${elevationWarning}
        ${list}
        <p class="manual-hint">${hint}</p>
        ${ids.length ? `
          <div class="manual-actions">
            <button type="button" class="manual-link" data-action="undo-poi" ${busy ? 'disabled' : ''}>Annuler le dernier point</button>
            <button type="button" class="manual-link" data-action="restart-hike" ${busy ? 'disabled' : ''}>Recommencer le tracé</button>
          </div>` : ''}
        <button type="button" class="manual-primary" data-action="finish-hike" ${ids.length && !busy ? '' : 'disabled'}>
          Terminer le tracé et choisir l'arrêt retour
        </button>`;
    }

    /** Tracé figé (étapes retour et résultat) : compteur et lien pour le modifier. */
    function hikeSummaryHtml(distanceM, ascentM) {
      return `
        <h4 class="manual-subtitle">Tracé de la randonnée</h4>
        ${counterHtml(distanceM, ascentM, currentPoiIds().length)}
        <div class="manual-actions">
          <button type="button" class="manual-link" data-action="edit-hike">Modifier le tracé</button>
        </div>`;
    }

    function backStepHtml() {
      const hike = currentHike();
      const busy = state.backLoadingId !== null;
      return `
        ${hikeSummaryHtml(hike.distance_m, hike.ascent_m)}
        <h4 class="manual-subtitle">Arrêt retour</h4>
        ${legendHtml()}
        <p class="manual-hint">${busy
          ? 'Recherche du trajet retour…'
          : 'Cliquez sur un arrêt de la carte pour y terminer la randonnée, ou sur le « D » pour une boucle.'}</p>`;
    }

    function transitArrival(transit) {
      const steps = transit.routes[0].legs[0].steps.filter(s => s.travelMode === 'TRANSIT');
      return steps.length ? steps[steps.length - 1].transitDetails.stopDetails.arrivalTime : null;
    }

    function doneStepHtml() {
      const { result, stop } = state.final;
      const props = result.features[0].properties;
      const warnings = [];
      const goArrival = transitArrival(state.go.transit_go);
      if (goArrival && stop.departure_time && new Date(stop.departure_time) < new Date(goArrival)) {
        warnings.push('Le trajet retour part avant votre arrivée dans le massif : choisissez un autre arrêt retour ou modifiez vos dates.');
      }
      return `
        ${hikeSummaryHtml(props.path_length, props.path_elevation)}
        <div class="manual-done">
          ✅ Retour : <strong>${escapeHtml(stop.name || 'arrêt choisi')}</strong>
          ${stop.departure_time ? `<span>départ à ${formatTime(stop.departure_time)}</span>` : ''}
          <button type="button" class="manual-link" data-action="change-back">Changer d'arrêt retour</button>
        </div>
        ${warningsHtml(warnings)}
        <p class="manual-hint">Votre trek est prêt : profil altimétrique et GPX dans « Distance et dénivelé ».</p>`;
    }

    function renderPanel() {
      let body = '';
      if (state.step === 'go') {
        body = goStepHtml();
      } else {
        body = goSummaryHtml() + ({
          hike: hikeStepHtml,
          back: backStepHtml,
          done: doneStepHtml,
        }[state.step])();
      }
      const html = stepperHtml()
        + `<div class="manual-step">${body}</div>`
        + (state.error ? `<div class="manual-error">${escapeHtml(state.error)}</div>` : '');
      // Ne reconstruire que si le contenu change : quitter le champ gare (événement
      // `change`) au moment de cliquer un bouton du panneau le remplacerait entre
      // mousedown et mouseup, et le clic serait perdu.
      if (html === lastPanelHtml) return;
      lastPanelHtml = html;
      panel.innerHTML = html;
    }
    let lastPanelHtml = null;

    panel.addEventListener('click', e => {
      const action = e.target.closest('[data-action]')?.dataset.action;
      if (action === 'load-stops') loadStops();
      else if (action === 'change-go') backToGoStep();
      else if (action === 'undo-poi') undoPoi();
      else if (action === 'restart-hike') restartHike();
      else if (action === 'finish-hike') enterBackStep();
      else if (action === 'edit-hike') {
        if (state.step === 'done') reopenStep('hike'); else backToHikeStep();
      } else if (action === 'change-back') reopenStep('back');
    });

    // --------------------------------------------------------- cycle de vie

    /** Efface tout le trek manuel en cours. */
    function resetManual() {
      clearFinal();
      clearBack();
      clearHike();
      removeStopsLayer();
      if (startMarker) { map.removeLayer(startMarker); startMarker = null; }
      ['go', 'summary', 'back'].forEach(clearResultModal);
      Object.assign(state, initialState());
      if (window.massifOverlay) window.massifOverlay.show();
      renderPanel();
    }

    function setMode(mode) {
      const manual = mode === 'manual';
      if (manual === isManual()) return;
      // Chaque mode repart d'une carte vierge
      api.resetResults();
      form.classList.toggle('mode-manual', manual);
      resetManual();
    }

    // Rechargement : certains navigateurs restaurent le bouton coché malgré
    // autocomplete="off". Le trek manuel, lui, n'est pas conservé : on repart
    // du mode par défaut.
    form.querySelector('input[name="mode"][value="auto"]').checked = true;

    form.querySelectorAll('input[name="mode"]').forEach(radio => {
      radio.addEventListener('change', () => { if (radio.checked) setMode(radio.value); });
    });

    // En mode manuel, la touche Entrée ne doit pas lancer le calcul automatique.
    document.addEventListener('submit', e => {
      if (e.target === form && isManual()) {
        e.preventDefault();
        e.stopImmediatePropagation();
      }
    }, true);

    // Massif ou gare changés : les arrêts et leurs durées ne valent plus rien.
    massifSelect.addEventListener('change', () => { if (isManual()) resetManual(); });
    addressInput.addEventListener('change', () => {
      if (isManual() && (state.stops || state.go)) resetManual();
      else if (isManual()) renderPanel();
    });
    addressInput.addEventListener('input', () => {
      if (isManual() && !state.stops) renderPanel();
    });

    // Dates changées : les arrêts restent valables, pas le trajet aller calculé.
    [depInput, retInput].forEach(input => input.addEventListener('input', () => {
      if (!isManual()) return;
      if (state.go) backToGoStep();
      else renderPanel();
    }));

    renderPanel();
  });
})();
