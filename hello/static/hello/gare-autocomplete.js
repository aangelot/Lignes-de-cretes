document.addEventListener('DOMContentLoaded', () => {
  const input = document.getElementById('address');
  const datalist = document.getElementById('gare-list');

  const codeField = document.getElementById('station_code');
  const lonField  = document.getElementById('station_lon');
  const latField  = document.getElementById('station_lat');

  let gares = [];

  /* =========================
     Normalisation
  ========================= */

  function normalize(s) {
    return (s || '')
      .toString()
      .normalize('NFD')
      .replace(/\p{Diacritic}/gu, '')
      .toLowerCase()
      .replace(/[-_]/g, ' ')
      .replace(/[^0-9a-z ]/g, ' ')
      .replace(/\s+/g, ' ')
      .trim();
  }

  function compact(s) {
    return s.replace(/\s+/g, '');
  }

  const STOPWORDS = new Set([
    'gare','station','de','du','des','la','le','les',
    'tgv','sncf','centre','ville','centreville'
  ]);

  /* =========================
     Chargement des gares
  ========================= */

  fetch('/gares/')
    .then(r => r.json())
    .then(data => {
      gares = data.map(g => {
        const norm = normalize(g.name);
        return {
          ...g,
          _norm: norm,
          _compact: compact(norm),
          _tokens: norm.split(' ').filter(t => t && !STOPWORDS.has(t))
        };
      });
    });

  /* =========================
     Autocomplete
  ========================= */

  input.addEventListener('input', () => {
    datalist.innerHTML = '';
    codeField.value = lonField.value = latField.value = '';

    const raw = input.value;
    if (raw.length < 2) return;

    const inputNorm = normalize(raw);
    const inputCompact = compact(inputNorm);

    let inputTokens = inputNorm
      .split(' ')
      .filter(t => t && !STOPWORDS.has(t));

    if (inputTokens.length === 0) {
      inputTokens = [inputCompact];
    }

    const results = [];

    for (const g of gares) {
      let score = Infinity;

      if (g._norm === inputNorm) score = 0;
      else if (g._compact === inputCompact) score = 1;
      else if (inputTokens.every(t => g._tokens.some(gt => gt.startsWith(t)))) score = 2;
      else if (inputTokens.every(t => g._tokens.some(gt => gt.includes(t)))) score = 3;
      else if (g._compact.startsWith(inputCompact)) score = 4;
      else if (g._compact.includes(inputCompact)) score = 5;
      else if (inputTokens.some(t => g._compact.includes(t))) score = 6;

      if (score < Infinity) {
        results.push({ g, score });
      }
    }

    results
      .sort((a, b) => a.score - b.score || a.g._norm.length - b.g._norm.length)
      .slice(0, 12)
      .forEach(({ g }) => {
        const opt = document.createElement('option');
        opt.value = g.name;
        opt.dataset.code = g.code_uic ?? '';
        opt.dataset.lon  = g.lon ?? '';
        opt.dataset.lat  = g.lat ?? '';
        datalist.appendChild(opt);
      });
  });

  /* =========================
     Sélection finale fiable
  ========================= */

  input.addEventListener('change', () => {
    const valueNorm = normalize(input.value);
    const valueCompact = compact(valueNorm);

    const found =
      gares.find(g => g._norm === valueNorm) ||
      gares.find(g => g._compact === valueCompact);

    if (!found) return;

    codeField.value = found.code_uic ?? '';
    lonField.value  = found.lon ?? '';
    latField.value  = found.lat ?? '';
  });
});
