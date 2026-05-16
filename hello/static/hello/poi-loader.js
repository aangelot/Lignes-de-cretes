document.addEventListener("DOMContentLoaded", () => {
  const massifSelect = document.getElementById("massif");
  const input = document.getElementById("poi-input");
  const menu = document.getElementById("poi-menu");
  const container = document.getElementById("poi-dropdown");
  const selectedContainer = document.getElementById("poi-selected");
  const errorDiv = document.getElementById("poi-error");

  let allPOIs = [];
  let filteredPOIs = [];
  window.window.selectedPOIs = window.window.selectedPOIs || [];

  // --- utils ---
  function slugify(text) {
    return text
      .toLowerCase()
      .normalize("NFD")
      .replace(/[\u0300-\u036f]/g, "")
      .replace(/\s+/g, "_");
  }

  function closeMenu() {
    menu.style.display = "none";
  }

  function openMenu() {
    if (filteredPOIs.length > 0) {
      menu.style.display = "block";
    }
  }

  // --- data loading ---
  async function loadPOIs(massif) {
    const slug = slugify(massif);
    const url = `/data/output/${slug}_poi_scores.geojson`;

    try {
      const res = await fetch(url);
      if (!res.ok) throw new Error("Erreur chargement POI");

      const data = await res.json();

      allPOIs = data.features
        .map(f => f.properties.titre)
        .sort((a, b) => a.localeCompare(b));

      filteredPOIs = [...allPOIs];
      closeMenu();

    } catch (err) {
      console.error(err);
      allPOIs = [];
      filteredPOIs = [];
      closeMenu();
    }
  }

  // --- rendering ---
  function renderMenu() {
    menu.innerHTML = "";

    filteredPOIs.forEach(poi => {
      const item = document.createElement("div");
      item.className = "dropdown-item";
      item.textContent = poi;

      if (window.selectedPOIs.includes(poi)) {
        item.classList.add("selected");
      }

      item.addEventListener("click", (e) => {
        e.stopPropagation();

        if (!window.selectedPOIs.includes(poi) && window.selectedPOIs.length >= 3) {
            errorDiv.textContent = "❌ Maximum 3 points d’intérêt.";
            closeMenu();
            return;
        }

        togglePOI(poi);
        });

      menu.appendChild(item);
    });
  }

  function renderSelected() {
    selectedContainer.innerHTML = "";

    window.selectedPOIs.forEach(poi => {
      const tag = document.createElement("span");
      tag.className = "poi-tag";
      tag.textContent = poi + " ✕";

      tag.addEventListener("click", () => {
        window.selectedPOIs = window.selectedPOIs.filter(p => p !== poi);
        renderSelected();
        renderMenu();
        if (window.selectedPOIs.length < 3) {
            errorDiv.textContent = "";
        }
      });

      selectedContainer.appendChild(tag);
    });
  }

  // --- logic ---
  function togglePOI(poi) {
  if (window.selectedPOIs.includes(poi)) {
    window.selectedPOIs = window.selectedPOIs.filter(p => p !== poi);
  } else {
    window.selectedPOIs.push(poi);
  }

  renderSelected();
  renderMenu();
  closeMenu();

  validatePOI(); 

  if (window.selectedPOIs.length < 3) {
    errorDiv.textContent = "";
  }
}

  function filterPOIs(query) {
    const q = query.toLowerCase();

    filteredPOIs = allPOIs.filter(poi =>
      poi.toLowerCase().includes(q)
    );
  }

  function validatePOI() {
    let message = "";
    let isValid = true;

    if (window.selectedPOIs.length > 3) {
        message = "❌ Vous pouvez sélectionner maximum 3 points d’intérêt.";
        isValid = false;
    }

    errorDiv.textContent = message;
    return isValid;
    }

  // --- events ---

  // ouverture au clic
  input.addEventListener("click", () => {
    filteredPOIs = [...allPOIs];
    renderMenu();
    openMenu();
  });

  // autocomplétion
  input.addEventListener("input", () => {
    filterPOIs(input.value);
    renderMenu();
    openMenu();
  });

  // empêcher fermeture quand on clique dans le menu
  menu.addEventListener("click", (e) => {
    e.stopPropagation();
  });

  // fermeture clic extérieur
  document.addEventListener("click", (e) => {
    if (!container.contains(e.target)) {
      closeMenu();
    }
  });

  // reset si massif change
  massifSelect.addEventListener("change", () => {
    window.selectedPOIs = [];
    renderSelected();
    input.value = "";
    loadPOIs(massifSelect.value);
  });

  // --- init ---
  loadPOIs(massifSelect.value);
});