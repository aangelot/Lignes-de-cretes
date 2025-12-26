document.addEventListener('DOMContentLoaded', function () {
  const addressInput = document.getElementById('address');
  const datalist = document.getElementById('gare-list');
  let gares = [];
  let suppressInput = false;

  function normalize(s){
    return (s || '')
      .toString()
      .normalize('NFD')
      .replace(/\p{Diacritic}/gu,'')
      .toLowerCase()
      .replace(/[-_]/g,' ')
      .replace(/[^0-9a-z ]/g,' ')
      .replace(/\s+/g,' ')
      .trim();
  }

  function compact(s){
    return s.replace(/\s+/g,'');
  }

  const STOPWORDS = new Set([
    'gare','station','de','du','des','la','le','les',
    'tgv','sncf','centre','ville','centreville'
  ]);

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

  function selectStation(found) {
    if (!found) return;
    addressInput.dataset.lon = found.lon ?? '';
    addressInput.dataset.lat = found.lat ?? '';
    addressInput.dataset.code = found.code_uic ?? '';
    datalist.innerHTML = '';
    // suppress immediate re-processing (allow events to settle)
    suppressInput = true;
    setTimeout(() => { suppressInput = false; }, 300);
  }

  addressInput.addEventListener('input', function () {
    if (suppressInput) return;

    const raw = addressInput.value;
    datalist.innerHTML = '';

    if (raw.length < 2) return;

    const inputNorm = normalize(raw);
    const inputCompact = compact(inputNorm);

    let inputTokens = inputNorm.split(' ')
      .filter(t => t && !STOPWORDS.has(t));

    // 🔑 si l'utilisateur tape "par " → on garde "par"
    if (inputTokens.length === 0 && inputNorm.length >= 2) {
      inputTokens = [inputNorm.replace(/\s+/g,'')];
    }

    const scored = [];

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
        scored.push({ g, score });
      }
    }

    scored
      .sort((a,b) => a.score - b.score || a.g._norm.length - b.g._norm.length)
      .slice(0, 12)
      .forEach(({g}) => {
        const opt = document.createElement('option');
        opt.value = g.name;
        opt.dataset.code = g.code_uic ?? '';
        opt.dataset.lon = g.lon ?? '';
        opt.dataset.lat = g.lat ?? '';
        datalist.appendChild(opt);
      });

    // If the current input exactly matches one option, treat it as a selection
    const exact = Array.from(datalist.options).find(o => o.value === raw);
    if (exact) {
      const found = gares.find(g => g.name === raw || normalize(g.name) === normalize(raw));
      selectStation(found);
    }
  });

  // when user finalizes selection (blur/change), set fields and remove suggestions
  addressInput.addEventListener('change', function () {
    const chosen = addressInput.value;
    const chosenNorm = normalize(chosen);
    const found = gares.find(g => normalize(g.name) === chosenNorm || g.name === chosen);
    if (found) {
      selectStation(found);
      return;
    }

    // fallback fuzzy: try compact prefix match
    const sv2 = chosenNorm.replace(/\s+/g,'').slice(0,3);
    const fuzzy = gares.find(g => {
      const sName = normalize(g.name);
      const sNameCompact = sName.replace(/\s+/g,'');
      return sNameCompact.startsWith(sv2) || sName.includes(sv2) || sNameCompact.includes(sv2);
    });
    if (fuzzy) {
      selectStation(fuzzy);
    }
  });
});