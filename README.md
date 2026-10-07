# Hodnotenie pracovnej záťaže VŠ učiteľov – SPU v Nitre

Program pre Windows, ktorý počíta pracovnú záťaž vysokoškolských učiteľov a hodnotí výkony ústavov podľa
**Metodického pokynu 1/2023 – Rozvrhnutie pracovnej záťaže vysokoškolských učiteľov SPU v Nitre,
v znení Dodatku č. 2** (účinný od 1. 7. 2025).

## Pre používateľov

### Inštalácia (odporúčaný spôsob – cez Python)
Windows 11 s inteligentným riadením aplikácií blokuje nepodpísaný `SPU-Zataz.exe`. Program sa preto
spúšťa cez nainštalovaný Python, ktorý je podpísaný:
1. Nainštalujte Python z [python.org/downloads](https://www.python.org/downloads/) („Install Now“, predvolené voľby).
2. Na stránke [Releases](https://github.com/Juraj145/Hodnotenie-pracovnej-zataze/releases/latest) stiahnite
   `SPU-Zataz-python.zip` a rozbaľte ho, napr. do `Dokumenty\SPU-Zataz\`.
3. Spustite dvojklikom `SPU-Zataz.pyw`. Podrobnosti sú v súbore `NAVOD.txt` v balíku.

`SPU-Zataz.exe` je k dispozícii pre počítače bez inteligentného riadenia aplikácií
(SmartScreen: **Ďalšie informácie → Spustiť aj tak**).

### Aktualizácie
Program pri každom spustení skontroluje, či je na GitHube novšia verzia. Ak áno, ponúkne
**Aktualizovať teraz** – stiahne nový balík (alebo exe), overí jeho kontrolný súčet SHA-256, vymení súbory
programu a reštartuje sa. Zostavenie na GitHube túto výmenu pred každým vydaním vyskúša na Windows.
Kontrolu možno vypnúť v *Nastavenia → Kontrolovať aktualizácie pri spustení*, alebo spustiť ručne v *Pomoc*.

### Kde sú moje údaje
Každý používateľ má vlastnú databázu v `%APPDATA%\SPU-Zataz\` (`data.db`, `parametre.json`,
`nastavenia.json`, `mapovania.json`). Aktualizácia programu údaje nemení.
Na zálohu alebo odovzdanie údajov kolegovi slúži *Súbor → Exportovať všetky údaje* (Excel, ktorý sa dá znova importovať).

### Ako zadávať údaje
| Spôsob | Kde |
|---|---|
| Učitelia a ústavy z UIS | *Súbor → Načítať učiteľov a ústavy z UIS* – vyberiete fakultu, označíte ústavy a program z verejného zoznamu zamestnancov na is.uniag.sk založí učiteľov s titulmi, funkciou a priradeným ústavom (ID osoby v UIS sa použije ako osobné číslo). Úväzok doplníte. |
| Záverečné práce z UIS | *Súbor → Načítať záverečné práce z UIS* – pre zvolenú fakultu a akademické roky sledovaného obdobia načíta z is.uniag.sk/zp obhájené bakalárske, diplomové a dizertačné práce a priradí ich vedúcim v databáze. |
| Ručne | karta **Vstupné údaje** – tlačidlá Pridať / Upraviť / Vymazať (dvojklik = úprava) |
| Excel šablóna | *Súbor → Vytvoriť prázdnu Excel šablónu*, vyplniť, *Importovať vyplnenú šablónu* |
| Export z UIS, CREPČ, Sofia | *Súbor → Importovať export z UIS / CREPČ…* – vyberiete súbor (XLSX/CSV), typ údajov a priradíte stĺpce. Mapovanie si uložíte ako profil a nabudúce ho len zvolíte. |
| Scopus / Web of Science | *Súbor → Načítať publikácie zo Scopus / WoS* – potrebný API kľúč (*Nastavenia → API kľúče*) a Scopus Author ID / ResearcherID / ORCID pri učiteľovi |

UIS ani CREPČ nemajú verejné rozhranie na priame pripojenie, preto program číta ich **exporty** (XLSX/CSV)
a stĺpce si priradíte raz. Pri opakovanom importe je predvolene zapnuté nahradenie záznamov za roky v súbore,
takže nevznikajú duplicity.

**Scopus / WoS:** metodika určuje kvartil V2/V3 podľa AIS (JCR) a podiel autora podľa CREPČ. Tieto údaje
API neposkytujú v požadovanej podobe, preto sa načítané publikácie pred importom zobrazia na kontrolu
(kategória, kvartil, podiel). Podiel sa predvyplní ako 1 / počet autorov. Kvartil podľa CiteScore zo Scopusu
je len orientačný návrh. API kľúče: [dev.elsevier.com](https://dev.elsevier.com) (Scopus Search API, funguje
v sieti univerzity alebo s Institutional Token), [developer.clarivate.com](https://developer.clarivate.com) (WoS Starter API).

### Čo program počíta
**Záťaž učiteľa** (karta *Záťaž učiteľov*, čl. 3, 5, 7):
- vzdelávanie = 2 × hodiny priamej výučby (v angličtine a pri mobilitných študentoch bonifikácia koef. 3)
  + 0,25 h × študent + záverečné práce (Bc 26 h, Ing 26 h, PhD 312 h), priemer za 2 akademické roky,
- projekty = vykázané hodiny, priemer za 3 roky,
- % z fondu 1 537,5 h × úväzok, status: 40–60 % ideálny stav, ≥ 80 % kvalitatívne posúdenie, > 100 % preťaženie,
- publikácie = Σ body tab. 3 × podiel, priemer za rok,
- projekty € = Σ suma pripísaná SPU × hodiny učiteľa / riešiteľská kapacita (zodpovedný riešiteľ výskumného projektu 2 × hodiny),
- min-max štandardizácia (čl. 7 ods. 1.5); učitelia s úväzkom < 25 % sa nezahŕňajú.
- porovnanie priamej výučby za týždeň s referenciou z pozn. 1 (prof. 6, doc. 8, OA 12, lektor 18 h).

**Hodnotenie ústavov** (karta *Hodnotenie ústavov*, čl. 3–6):
- výkony: študentohodiny × koeficient odboru (tab. 2), body za publikácie, podiely na financiách projektov,
- lineárna regresia bez absolútneho člena (y = b·x, čl. 1 ods. 4) voči prepočítaným úväzkom,
- štandardizované rezíduá (z-skóre), sumárne skóre 40 / 40 / 20 %,
- optimálny počet pedagógov za každú oblasť (y / b) a kvázi optimálny počet 0,4 / 0,4 / 0,2 vrátane grafu ako ilustračný graf 1,
- chýbajúca časť obdobia (nástup, materská/rodičovská) sa nahradí priemerným úväzkom fakulty.

Výsledky sa exportujú do Excelu (*Exportovať výsledky*) vrátane použitých parametrov a obdobia.

### Výklad nejednoznačných miest pokynu
Všetky číselné hodnoty sú v *Nastavenia → Parametre metodiky* a dajú sa zmeniť bez novej verzie programu.

| Miesto | Zvolený výklad | Parameter |
|---|---|---|
| čl. 3 ods. 4 – „bonifikuje koeficientom 3“ | hodina výučby v EN = 2 × 3 = 6 h | `en_koef_nasobi_pripravu` (false → 3 h) |
| čl. 5 ods. 1 A – dvojnásobok hodín zodpovedného riešiteľa | zvyšuje jeho podiel na financiách, nie záťaž v hodinách (čl. 5 ods. 3) | `nasobok_zodpovedny_riesitel` |
| riešiteľská kapacita | ak nie je zadaná, súčet hodín účastníkov | – |
| štandardizované rezíduá | rezíduum / smerodajná odchýlka rezíduí (n − 1) | – |

## Pre správcu programu

### Spustenie zo zdrojového kódu
```
python -m pip install -r requirements.txt
python main.py
python -m pytest tests      # testy výpočtov
```

### Vydanie novej verzie
1. Zmeny nahrajte do vetvy `main` (GitHub Actions spustí testy).
2. Vytvorte tag s novou verziou a nahrajte ho:
   ```
   git tag v0.2.0
   git push origin v0.2.0
   ```
   alebo v GitHube *Actions → Vydanie (build exe) → Run workflow* a zadajte verziu.
3. Workflow na Windows zostaví `SPU-Zataz.exe`, vypočíta SHA-256 a zverejní ich ako nové vydanie.
   Používateľom sa pri ďalšom spustení ponúkne aktualizácia.

Číslo verzie v tagu musí byť vyššie ako predchádzajúce (porovnáva sa X.Y.Z).

### Štruktúra
```
main.py                     spúšťač
spu_zataz/calc.py           výpočty podľa pokynu (bez GUI, testované)
spu_zataz/config.py         parametre pokynu, priečinok s dátami
spu_zataz/models.py         dátové záznamy
spu_zataz/db.py             SQLite databáza
spu_zataz/importy.py        Excel šablóna, import UIS/CREPČ s mapovaním stĺpcov
spu_zataz/biblio.py         Scopus a Web of Science API
spu_zataz/vystupy.py        export výsledkov
spu_zataz/updater.py        aktualizácie z GitHub Releases
spu_zataz/gui*.py           grafické rozhranie (tkinter)
tests/                      testy
.github/workflows/          testy a zostavenie exe
```
