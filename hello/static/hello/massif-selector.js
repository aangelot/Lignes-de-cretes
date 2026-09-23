/**
 * Sélection du massif directement sur la carte.
 *
 * Affiche les contours des massifs ouverts (/massifs/), ouvre une popup au clic
 * avec un bouton « Sélectionner », et tient le champ #massif du formulaire
 * synchronisé avec la carte dans les deux sens.
 *
 * C'est aussi cette couche qui donne le cadrage initial de la carte : tant qu'aucun
 * massif n'est choisi, la vue englobe tous les massifs ouverts, sans coordonnées
 * codées en dur à mettre à jour quand on en ouvre un nouveau.
 *
 * Expose window.massifOverlay pour qu'index.js puisse masquer la couche une fois
 * le trek calculé et la réafficher quand on repart d'une carte vierge.
 */
(function () {
  const STYLE_DEFAULT = {
    className: 'massif-shape',
    color: '#ef8409',
    weight: 2,
    opacity: 0.85,
    fillColor: '#ef8409',
    fillOpacity: 0.08,
  };
  const STYLE_HOVER = { weight: 3, fillOpacity: 0.22 };
  // Une fois un massif choisi, il passe au premier plan et les autres s'effacent.
  const STYLE_SELECTED = { weight: 4, opacity: 1, fillOpacity: 0.35 };
  // Estompés mais toujours repérables : on doit pouvoir changer d'avis d'un clic.
  const STYLE_DIMMED = { weight: 1.5, opacity: 0.5, fillOpacity: 0.04 };

  const FLY_OPTIONS = { padding: [40, 40], duration: 1.2, maxZoom: 12 };
  // Vue d'ensemble : marge minimale autour des contours, et plafond de zoom qui
  // garde un contexte lisible s'il n'y a qu'un seul massif ouvert.
  const OVERVIEW_MARGIN = 30;
  const OVERVIEW_MAX_ZOOM = 9;

  window.initMassifSelector = function initMassifSelector(map) {
    const select = document.getElementById('massif');
    if (!select) return;

    const layersByValue = new Map();
    let massifLayer = null;
    let selectedLabel = null;
    let visible = true;

    function styleFor(value) {
      // Tant que rien n'est choisi, tous les massifs s'offrent de la même façon.
      if (!select.value) return STYLE_DEFAULT;
      return Object.assign(
        {},
        STYLE_DEFAULT,
        value === select.value ? STYLE_SELECTED : STYLE_DIMMED
      );
    }

    /** Nom affiché en permanence au centre du massif choisi. */
    function refreshSelectedLabel() {
      if (selectedLabel) {
        map.removeLayer(selectedLabel);
        selectedLabel = null;
      }

      const layer = layersByValue.get(select.value);
      if (!layer || !visible) return;

      selectedLabel = L.tooltip({
        permanent: true,
        direction: 'center',
        className: 'massif-selected-label',
        interactive: false,
      })
        .setLatLng(layer.getCenter())
        .setContent(layer.feature.properties.label)
        .addTo(map);
    }

    function refreshStyles() {
      layersByValue.forEach((layer, value) => layer.setStyle(styleFor(value)));
      refreshSelectedLabel();
    }

    function flyToMassif(value) {
      const layer = layersByValue.get(value);
      if (layer) map.flyToBounds(layer.getBounds(), FLY_OPTIONS);
    }

    /**
     * Options de cadrage d'ensemble. Le formulaire flotte au-dessus de la carte : on
     * lui réserve sa place, sinon les massifs se cadrent sur toute la largeur et une
     * partie d'entre eux finit sous le panneau. Il borde la carte à gauche en grand
     * écran et remonte du bas en tiroir sur mobile, d'où la mesure plutôt qu'une
     * constante. La réserve est plafonnée pour qu'il reste toujours de la place.
     */
    function overviewOptions() {
      const topLeft = [OVERVIEW_MARGIN, OVERVIEW_MARGIN];
      const bottomRight = [OVERVIEW_MARGIN, OVERVIEW_MARGIN];
      const panel = document.getElementById('modals-container');
      const panelRect = panel && panel.getBoundingClientRect();
      const mapRect = map.getContainer().getBoundingClientRect();

      if (panelRect && panelRect.width && panelRect.height) {
        if (panelRect.width < mapRect.width / 2) {
          topLeft[0] += Math.min(panelRect.right - mapRect.left, mapRect.width * 0.45);
        } else {
          bottomRight[1] += Math.min(mapRect.bottom - panelRect.top, mapRect.height * 0.45);
        }
      }

      return {
        paddingTopLeft: topLeft,
        paddingBottomRight: bottomRight,
        maxZoom: OVERVIEW_MAX_ZOOM,
      };
    }

    /** Cadre la carte sur l'ensemble des massifs ouverts. */
    function fitAllMassifs(animate) {
      if (!massifLayer) return;
      const bounds = massifLayer.getBounds();
      if (!bounds.isValid()) return;
      const options = overviewOptions();
      if (animate) map.flyToBounds(bounds, Object.assign({ duration: 1.2 }, options));
      else map.fitBounds(bounds, options);
    }

    /** Renseigne le formulaire depuis la carte : le `change` propage aux autres modules. */
    function selectFromMap(value) {
      if (select.value !== value) {
        select.value = value;
        select.dispatchEvent(new Event('change', { bubbles: true }));
      } else {
        flyToMassif(value);
      }
    }

    function buildPopupContent(feature) {
      const content = document.createElement('div');
      content.className = 'massif-popup';

      const title = document.createElement('strong');
      title.textContent = feature.properties.label;
      content.appendChild(title);

      const button = document.createElement('button');
      button.type = 'button';
      button.textContent = 'Sélectionner';
      button.addEventListener('click', () => {
        map.closePopup();
        selectFromMap(feature.properties.value);
      });
      content.appendChild(button);

      return content;
    }

    function onEachFeature(feature, layer) {
      const { value, label } = feature.properties;
      layersByValue.set(value, layer);

      layer.bindTooltip(label, { sticky: true, direction: 'top' });
      layer.bindPopup(() => buildPopupContent(feature), {
        closeButton: false,
        className: 'massif-popup-wrapper',
      });

      layer.on('mouseover', () => {
        // Le massif choisi porte déjà son nom en permanence
        if (value === select.value) layer.closeTooltip();
        layer.setStyle(Object.assign({}, styleFor(value), STYLE_HOVER));
      });
      layer.on('mouseout', () => layer.setStyle(styleFor(value)));
    }

    // Le formulaire reste maître : qu'on vienne de la carte ou du <select>,
    // c'est cet écouteur qui met la carte à jour.
    select.addEventListener('change', () => {
      refreshStyles();
      if (select.value) flyToMassif(select.value);
      else fitAllMassifs(true);
    });

    window.massifOverlay = {
      show() {
        visible = true;
        if (massifLayer && !map.hasLayer(massifLayer)) massifLayer.addTo(map);
        refreshSelectedLabel();
      },
      fitAll() {
        fitAllMassifs(true);
      },
      hide() {
        visible = false;
        map.closePopup();
        if (selectedLabel) { map.removeLayer(selectedLabel); selectedLabel = null; }
        if (massifLayer && map.hasLayer(massifLayer)) map.removeLayer(massifLayer);
      },
    };

    fetch('/massifs/')
      .then((res) => {
        if (!res.ok) throw new Error('Erreur chargement des massifs');
        return res.json();
      })
      .then((data) => {
        massifLayer = L.geoJSON(data, { style: STYLE_DEFAULT, onEachFeature });
        if (visible) massifLayer.addTo(map);
        refreshStyles();
        if (select.value) flyToMassif(select.value);
        else fitAllMassifs();
      })
      .catch((err) => {
        // Sans contours, le formulaire reste pleinement utilisable.
        console.error(err);
      });
  };
})();
