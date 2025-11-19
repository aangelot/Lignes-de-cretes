const addressInput = document.getElementById("address");
const suggestionsBox = document.getElementById("address-suggestions");
let abortController = null;

addressInput.addEventListener("input", async () => {
    const query = addressInput.value.trim();

    // Vide et cache si trop court
    if (query.length < 3) {
        suggestionsBox.style.display = "none";
        suggestionsBox.innerHTML = "";
        return;
    }

    // Annule une requête précédente encore en cours
    if (abortController) abortController.abort();
    abortController = new AbortController();

    // Requête BAN
    try {
        const res = await fetch(
            `https://api-adresse.data.gouv.fr/search/?q=${encodeURIComponent(query)}&limit=5`,
            { signal: abortController.signal }
        );
        const data = await res.json();

        suggestionsBox.innerHTML = "";

        if (!data.features.length) {
            suggestionsBox.style.display = "none";
            return;
        }

        // Affiche suggestions
        data.features.forEach(f => {
            const item = document.createElement("div");
            item.textContent = f.properties.label;

            item.addEventListener("click", () => {
                addressInput.value = f.properties.label;
                suggestionsBox.style.display = "none";
            });

            suggestionsBox.appendChild(item);
        });

        suggestionsBox.style.display = "block";

    } catch (err) {
        // Ignore les abort
    }
});