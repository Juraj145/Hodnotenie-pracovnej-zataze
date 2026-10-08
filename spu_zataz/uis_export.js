/* SPU záťaž – export výučby z UIS (is.uniag.sk)
 *
 * Spúšťa sa ako záložka (bookmarklet) na ľubovoľnej stránke is.uniag.sk po prihlásení.
 * Iba ČÍTA stránky, ktoré prihlásený používateľ vidí v UIS:
 *   - Rozvrhy → rozvrhy fakulty (zoznam rozvrhových akcií) pre zvolené akademické roky,
 *   - Úspešnosť študentov v predmetoch → počet študentov predmetu v semestri.
 * Výsledok stiahne ako jeden súbor JSON, ktorý sa načíta do programu (Súbor → Načítať výučbu z UIS).
 *
 * spuExport({fakulta: 30, roky: ["2023/2024", "2024/2025"], ustav: 0}) vráti Promise s dátami.
 */
async function spuExport(o) {
  const F = String(o.fakulta), ROKY = o.roky, US = String(o.ustav || 0), log = o.log || (() => {});
  const P = new DOMParser();
  const doc = h => P.parseFromString(h, "text/html");
  const txt = e => (e ? e.textContent : "").replace(/ /g, " ").replace(/\s+/g, " ").trim();
  const get = async u => { const r = await fetch(u, {credentials: "include"}); if (!r.ok) throw new Error(u + " " + r.status); return r.text(); };
  const rokZ = s => { const m = (s || "").match(/(\d{4})\/(\d{4})/); return m ? m[1] + "/" + m[2] : ""; };
  const sem = s => /\bZS\b/.test(s) ? "ZS" : /\bLS\b/.test(s) ? "LS" : /doktorand/i.test(s) ? "PhD" : "";
  const idZ = (h, k) => { const m = (h || "").match(new RegExp("[?;]" + k + "=(\\d+)")); return m ? m[1] : ""; };

  // 1. rozvrhy fakulty
  log("Zoznam rozvrhov…");
  const d1 = doc(await get("/auth/katalog/rozvrhy_view.pl?konf=1;f=" + F + ";lang=sk"));
  const t1 = [...d1.querySelectorAll("table")].find(t => /Obdobie/.test(txt(t.rows[0])) && /Rozvrh/.test(txt(t.rows[0])));
  if (!t1) throw new Error("Nenašiel som zoznam rozvrhov – ste prihlásený v UIS?");
  const hl = [...t1.rows[0].cells].map(txt);
  const ci = n => hl.findIndex(h => h.startsWith(n));
  const rozvrhy = [];
  for (const r of [...t1.rows].slice(1)) {
    const inp = r.querySelector("input[name=rozvrh]"); if (!inp) continue;
    const c = [...r.cells].map(txt), obd = c[ci("Obdobie")] || "";
    if (!ROKY.includes(rokZ(obd))) continue;
    rozvrhy.push({id: inp.value, nazov: c[ci("Rozvrh")], obdobie: obd, ak_rok: rokZ(obd), semester: sem(obd),
                  forma: c[ci("Forma")] || "", zaciatok: c[ci("Začiatok")] || "", koniec: c[ci("Koniec")] || "", akcie: []});
  }

  // 2. akcie každého rozvrhu (zvlášť – pri spájaní by UIS stratil dátumy blokovej výučby)
  for (const [i, rz] of rozvrhy.entries()) {
    log("Rozvrh " + (i + 1) + "/" + rozvrhy.length + ": " + rz.nazov);
    const d = doc(await get("/auth/katalog/rozvrhy_view.pl?f=" + F + ";rozvrh=" + rz.id + ";ustav=" + US + ";format=list;zobraz=1;lang=sk"));
    const pozn = {};
    for (const t of d.querySelectorAll("table")) for (const r of t.rows) {
      const c = r.cells; if (c.length !== 2) continue;
      const m = txt(c[0]).match(/^\((\d+)\)$/); if (!m) continue;
      pozn[m[1]] = {text: txt(c[1]), ucitelia: [...c[1].querySelectorAll("a[href*='clovek.pl']")].map(a => [idZ(a.getAttribute("href"), "id"), txt(a)])};
    }
    const t = [...d.querySelectorAll("table")].find(t => /Akcia/.test(txt(t.rows[0])) && /Vyučujúci/.test(txt(t.rows[0])));
    if (!t) continue;
    const h = [...t.rows[0].cells].map(txt), k = n => h.indexOf(n);
    for (const r of [...t.rows].slice(1)) {
      const c = r.cells; if (c.length < h.length) continue;
      const pa = c[k("Predmet")].querySelector("a[href*='predmet=']");
      const sup = [...c[k("Predmet")].querySelectorAll("sup")].map(txt).join(" ");
      const pz = [...sup.matchAll(/\d+/g)].map(m => pozn[m[0]]).filter(Boolean);
      const ucit = [...c[k("Vyučujúci")].querySelectorAll("a[href*='clovek.pl']")].map(a => [idZ(a.getAttribute("href"), "id"), txt(a)]);
      pz.forEach(p => /Ďalej vyučujú/.test(p.text) && p.ucitelia.forEach(u => ucit.push(u)));
      rz.akcie.push({den: txt(c[k("Deň")]), od: txt(c[k("Od")]), do: txt(c[k("Do")]),
                     predmet_id: pa ? idZ(pa.getAttribute("href"), "predmet") : "", predmet: pa ? txt(pa) : txt(c[k("Predmet")]),
                     akcia: txt(c[k("Akcia")]), ucitelia: ucit, obmedzenie: k("Obmedzenie") >= 0 ? txt(c[k("Obmedzenie")]) : "",
                     kapacita: k("Kapacita") >= 0 ? (parseInt(txt(c[k("Kapacita")])) || 0) : 0,
                     poznamky: pz.filter(p => !/Ďalej vyučujú/.test(p.text)).map(p => p.text)});
    }
  }

  // 3. počty študentov predmetov po semestroch
  log("Počty študentov…");
  const d3 = doc(await get("/auth/student/hodnoceni.pl?fakulta=" + F + ";lang=sk"));
  const obdobia = [...d3.querySelectorAll("a[href*='obdobi=']")].map(a => {
    const r = a.closest("tr"); return r ? {id: idZ(a.getAttribute("href"), "obdobi"), nazov: txt(r.cells[0])} : null;
  }).filter(x => x && ROKY.includes(rokZ(x.nazov)));
  const predmety = {};
  for (const ob of obdobia) {
    log("Študenti: " + ob.nazov);
    const d = doc(await get("/auth/student/hodnoceni.pl?fakulta=" + F + ";obdobi=" + ob.id + ";pismeno=all;lang=sk"));
    const t = [...d.querySelectorAll("table")].find(t => /Študentov/.test(txt(t.rows[0])));
    if (!t) continue;
    const h = [...t.rows[0].cells].map(txt);
    for (const r of [...t.rows].slice(1)) {
      const a = r.querySelector("a[href*='predmet=']"); if (!a) continue;
      predmety[idZ(a.getAttribute("href"), "predmet")] = {kod: txt(r.cells[h.indexOf("Kód")]), nazov: txt(a),
        studentov: parseInt(txt(r.cells[h.indexOf("Študentov")])) || 0, obdobie: ob.nazov, ak_rok: rokZ(ob.nazov), semester: sem(ob.nazov)};
    }
  }
  return {format: "spu-zataz-uis-vyucba", verzia: 1, vytvorene: new Date().toISOString(), fakulta: F, ustav: US,
          roky: ROKY, rozvrhy, predmety};
}

/* Spúšťač záložky: opýta sa na fakultu a roky, stiahne súbor. */
async function spuExportSpusti() {
  if (!/is\.uniag\.sk$/.test(location.hostname)) { alert("Spustite na stránke is.uniag.sk po prihlásení do UIS."); return; }
  const FAK = {TF: 30, FEM: 10, FAPZ: 20, FBP: 50, FZKI: 40, "FEŠRR": 60, FESRR: 60};
  const f = (prompt("Fakulta (TF, FEM, FAPZ, FBP, FZKI, FEŠRR):", "TF") || "").trim().toUpperCase();
  if (!FAK[f]) { if (f) alert("Neznáma fakulta: " + f); return; }
  const r = new Date().getFullYear(), m = new Date().getMonth();
  const posl = m >= 8 ? r - 1 : r - 2;
  const def = (posl - 1) + "/" + posl + ", " + posl + "/" + (posl + 1);
  const roky = (prompt("Akademické roky (oddelené čiarkou):", def) || "").split(",").map(s => s.trim()).filter(Boolean);
  if (!roky.length) return;
  const box = document.createElement("div");
  box.style.cssText = "position:fixed;top:12px;right:12px;z-index:99999;background:#1E4620;color:#fff;padding:12px 16px;font:14px sans-serif;border-radius:6px;box-shadow:0 2px 8px #0005;max-width:420px";
  document.body.appendChild(box);
  const log = s => { box.textContent = "SPU záťaž – export: " + s; };
  try {
    const data = await spuExport({fakulta: FAK[f], roky, log});
    const n = data.rozvrhy.reduce((s, x) => s + x.akcie.length, 0);
    const blob = new Blob([JSON.stringify(data)], {type: "application/json"});
    const a = document.createElement("a");
    a.href = URL.createObjectURL(blob);
    a.download = "uis_vyucba_" + f + "_" + roky.map(x => x.replace("/", "-")).join("_") + ".json";
    document.body.appendChild(a); a.click(); a.remove();
    log("hotovo – " + data.rozvrhy.length + " rozvrhov, " + n + " akcií, " + Object.keys(data.predmety).length +
        " predmetov. Súbor sa stiahol, načítajte ho v programe (Súbor → Načítať výučbu z UIS).");
  } catch (e) {
    log("chyba: " + e.message);
  }
  setTimeout(() => box.remove(), 20000);
}
