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

### Postup v programe
Hlavné okno má vľavo ponuku v poradí, v akom sa hodnotenie robí. **Prehľad** ukazuje stav každého kroku
(✔ hotové, ! treba doplniť), výsledky a nálezy kontroly; kliknutím sa presuniete na príslušnú časť.

| Krok | Čo tam je |
|---|---|
| 1 Podmienky hodnotenia | nahratý dokument metodiky (PDF/DOCX) a parametre, podľa ktorých program počíta |
| 2 Obdobie hodnotenia | akademické roky (vzdelávanie, záverečné práce), roky publikácií a roky projektov – zvlášť |
| 3 Zoznam učiteľov | učitelia, fakulta, ústav, funkcia, úväzok, aktívne obdobie, ORCID / Scopus / WoS; mazanie fakulty |
| 4 Výučba · 5 Záverečné práce · 6 Projekty · 7 Publikácie | údaje s vlastnými tlačidlami na načítanie (UIS, knižnica SPU, súbor, ručne) |
| 8 Kontrola údajov | čo chýba alebo je neúplné na výpočet (chyba / upozornenie / informácia), dvojklik prejde na záznam |
| 9 Hodnotenie učiteľov | záťaž v % fondu (čl. 7 ods. 1.1–1.3) a skóre s poradím (čl. 7 ods. 1.5) |
| 10 Hodnotenie ústavov | regresia, z-skóre, sumárne skóre, optimálny počet pedagógov, graf |

### Podmienky hodnotenia (metodika)
V časti **1 Podmienky hodnotenia** nahráte dokument metodického pokynu (PDF, DOCX alebo TXT). Program z neho
vyčíta parametre – fond pracovného času, násobok hodín výučby, bonifikáciu angličtiny, hodiny na študenta,
tab. 1 (záverečné práce), tab. 2 (koeficienty odborov), tab. 3 (body za publikácie), váhy 40/40/20,
hranice 40–60 / 80 / 100 %, minimálny úväzok 25 %, dĺžky sledovaných období, bonifikáciu zodpovedného riešiteľa
a referenčnú výučbu z pozn. 1. Ukáže, ktoré hodnoty sa líšia od tých, s ktorými program počíta, a po potvrdení
ich použije a výsledky prepočíta. Pri novom dodatku teda stačí nahrať aktualizovaný dokument.

Program preberá **hodnoty**, nie nový postup výpočtu – ak by dodatok zaviedol napr. novú oblasť hodnotenia,
treba aktualizovať program. V tabuľke parametrov je pri každej hodnote úryvok z dokumentu, odkiaľ pochádza,
a označené parametre, ktoré sa v dokumente nenašli. Ručne sa parametre dajú upraviť tlačidlom
*Upraviť parametre ručne*.

### Obdobie hodnotenia
Roky sa dajú určiť tromi spôsobmi:
- **podľa metodického pokynu k dátumu hodnotenia** – dva posledné ukončené akademické roky, tri roky publikácií
  s uzávierkou v CREPČ najneskôr 31. 12. predchádzajúceho roka (rok hodnotenia − 4 až − 2) a tri roky projektov
  (predvolene rovnako; posun sa dá zmeniť v parametroch `posun_rokov_publikacie`, `posun_rokov_projekty`),
- **podľa načítaných údajov** – najnovšie roky, za ktoré sú v programe údaje,
- **vlastný výber** – zaškrtnete ľubovoľné akademické roky, roky publikácií a roky projektov (každé zvlášť).

Vzdelávanie sa dá vypočítať za všetky zvolené akademické roky (priemer) alebo **iba za jeden akademický rok**.
Pri každom roku je počet načítaných záznamov, takže hneď vidno, za ktoré roky údaje chýbajú.

### Uloženie a načítanie údajov
Program si údaje pamätá vo svojej databáze (`%APPDATA%\SPU-Zataz\`) – po zatvorení o ne neprídete a aktualizácia
programu ich nemení. Tlačidlom **💾 Uložiť údaje** ich uložíte do zvoleného priečinka so samostatnými zložkami:

```
01 Podmienky hodnotenia   dokumenty metodiky a parametre výpočtu
02 Zoznam učiteľov        ucitelia.xlsx
03 Výučba                 vyucba.xlsx
04 Záverečné práce        zaverecne_prace.xlsx
05 Projekty               projekty.xlsx (projekty a účasti učiteľov)
06 Publikácie             publikacie.xlsx
07 Výsledky               exporty výsledkov
hodnotenie.json           obdobie a údaje o uložení
```

Súbory sú bežné tabuľky Excelu – dajú sa otvoriť aj upraviť. **📂 Načítať údaje** ich načíta späť (napr. na inom
počítači, alebo keď máte rozpracovaných viac hodnotení) a ponúkne aj podmienky hodnotenia uložené s nimi.
*Súbor → Vymazať fakultu* vymaže fakultu so všetkými jej učiteľmi a ich údajmi.

### Kontrola údajov a identifikátory
**8 Kontrola údajov** vyznačí, čo chýba: učiteľ bez fakulty, ústavu alebo úväzku, bez výučby v sledovaných rokoch,
roky bez načítanej výučby, záverečných prác, publikácií či projektov, projekt bez sumy pripísanej SPU alebo bez
riešiteľov, predmet bez študijného odboru, publikácia s neznámou kategóriou alebo podielom mimo 0–1 a pod.
V zozname učiteľov sú červené riadky s chýbajúcimi údajmi pre výpočet a žlté riadky učiteľov bez ORCID,
Scopus Author ID alebo WoS ResearcherID.

Tlačidlo **🆔 Doplniť ORCID / Scopus / WoS** ich vyhľadá v menných autoritách knižnice SPU (ORCID)
a v registri ORCID (podľa mena a pracoviska SPU) a z profilu ORCID prevezme Scopus Author ID a ResearcherID,
ak ich tam autor prepojil. Dopĺňajú sa iba prázdne polia; pri menovcoch sa nedoplní nič.

### Ako zadávať údaje
| Spôsob | Kde |
|---|---|
| Učitelia a ústavy z UIS | *3 Zoznam učiteľov → Načítať z UIS* – vyberiete fakultu, označíte ústavy a program z verejného zoznamu zamestnancov na is.uniag.sk založí učiteľov s titulmi, funkciou a priradeným ústavom (ID osoby v UIS sa použije ako osobné číslo). Úväzok doplníte. |
| Výučba z UIS (rozvrhy) | *4 Výučba → Načítať z UIS* – tlačidlom 1 si vytvoríte záložku v prehliadači; po prihlásení do UIS na ňu kliknete, zadáte fakultu a akademické roky a stiahne sa súbor s rozvrhmi fakulty a počtami študentov predmetov. Tlačidlom 2 ho načítate; program prepočíta hodiny a študentov každého učiteľa podľa čl. 3 a 7. |
| Záverečné práce z UIS | *5 Záverečné práce → Načítať z UIS* – pre zvolenú fakultu a akademické roky načíta z is.uniag.sk/zp obhájené bakalárske, diplomové a dizertačné práce a priradí ich vedúcim. |
| Projekty z UIS | *6 Projekty → Načítať z UIS* – pre fakultu alebo ústav a kalendárne roky načíta z is.uniag.sk/vv riešené a ukončené externé projekty (pozn. 8 pokynu), zaradí ich do kategórií a priradí učiteľom: garant = zodpovedný riešiteľ, riešiteľ / metodický riešiteľ = riešiteľ. Sumu pripísanú SPU a vykázané hodiny verejná časť UIS neuvádza – doplníte ich ručne alebo importom zo súboru. |
| Publikácie z knižnice SPU / CREPČ | *7 Publikácie → Z knižnice SPU / CREPČ* – z evidencie publikačnej činnosti knižnice SPU (arl4.library.sk, EPCA; záznamy s identifikátorom CREPČ) načíta vedecké výstupy V1–V3 s kategóriou podľa tab. 3, kvartilom podľa AIS a podielom autora. Tie isté publikácie načítané skôr zo Scopus / WoS alebo ručne (zhoda DOI, WoS UT, Scopus EID alebo názvu) sa vymažú a nahradia záznamom knižnice s doplneným podielom. |
| Scopus / Web of Science | *7 Publikácie → Scopus / WoS* – potrebný API kľúč (*Nastavenia → API kľúče*) a Scopus Author ID / ResearcherID / ORCID pri učiteľovi |
| Ručne | tlačidlá Pridať / Upraviť / Vymazať na každej stránke údajov (dvojklik = úprava) |
| Zo súboru (UIS, CREPČ, Sofia, Excel) | tlačidlo *Zo súboru…* na stránke údajov – vyberiete XLSX/CSV a priradíte stĺpce; mapovanie si uložíte ako profil. Celú šablónu naraz: *Súbor → Vytvoriť prázdnu Excel šablónu / Importovať vyplnenú šablónu*. |

**Scopus / WoS:** metodika určuje kvartil V2/V3 podľa AIS (JCR) a podiel autora podľa CREPČ. Tieto údaje
API neposkytujú v požadovanej podobe, preto sa načítané publikácie pred importom zobrazia na kontrolu.
API kľúče: [dev.elsevier.com](https://dev.elsevier.com) (Scopus Search API, funguje v sieti univerzity alebo
s Institutional Token), [developer.clarivate.com](https://developer.clarivate.com) (WoS Starter API).

### Čo program počíta
**Záťaž učiteľa** (9 Hodnotenie učiteľov, záložka *Záťaž*, čl. 3, 5, 7):
- vzdelávanie = 2 × hodiny priamej výučby (v angličtine a pri mobilitných študentoch bonifikácia koef. 3)
  + 0,25 h × študent + záverečné práce (Bc 26 h, Ing 26 h, PhD 312 h), priemer za zvolené akademické roky,
- projekty = vykázané hodiny, priemer za zvolené roky,
- % z fondu 1 537,5 h × úväzok za čas, keď bol učiteľ aktívny; status: 40–60 % ideálny stav,
  ≥ 80 % kvalitatívne posúdenie, > 100 % preťaženie,
- porovnanie priamej výučby za týždeň s referenciou z pozn. 1 (prof. 6, doc. 8, OA 12, lektor 18 h).

**Skóre učiteľa** (záložka *Skóre a poradie*, čl. 7 ods. 1.5) – overené na výsledkoch ústavu UPTDB TF:
- pôvodné hodnoty: vzdelávanie (h/ak. rok), publikácie (Σ body tab. 3 × podiel, priemer za rok),
  projekty (Σ suma pripísaná SPU × hodiny učiteľa / riešiteľská kapacita; zodpovedný riešiteľ výskumného
  projektu 2 × hodiny; priemer za rok),
- prepočítané hodnoty: chýbajúca časť obdobia oblasti (neskorší nástup, materská/rodičovská) sa doplní
  priemerom fakulty – prepočítaná = pôvodná + (1 − aktívny podiel) × priemer fakulty,
- skóre oblasti = (x − x_min) / (x_max − x_min) × 100 v rámci fakulty, celkové skóre = 0,4 · vzdelávanie
  + 0,4 · publikácie + 0,2 · projekty, poradie v rámci fakulty,
- do výpočtov na úrovni učiteľov nevstupujú učitelia s prepočítaným úväzkom < 25 % v ktorejkoľvek oblasti.

**Hodnotenie ústavov** (10 Hodnotenie ústavov, čl. 3–6):
- výkony: študentohodiny × koeficient odboru (tab. 2), body za publikácie, podiely na financiách projektov
  (súčty prepočítaných hodnôt učiteľov ústavu),
- prepočítané úväzky po oblastiach (chýbajúca časť obdobia nahradená priemerným úväzkom fakulty),
- lineárna regresia bez absolútneho člena (y = b·x, čl. 1 ods. 4), štandardizované rezíduá (z-skóre),
  sumárne skóre 40 / 40 / 20 %,
- optimálny počet pedagógov za každú oblasť (y / b) a kvázi optimálny počet 0,4 / 0,4 / 0,2 vrátane grafu.

Výsledky sa exportujú do Excelu (hárky Skóre učiteľov – v rovnakom usporiadaní ako výsledky UPTDB, Záťaž
učiteľov, Ústavy, Model a parametre).

### Výklad nejednoznačných miest pokynu
Všetky číselné hodnoty sú v parametroch a dajú sa zmeniť bez novej verzie programu.

| Miesto | Zvolený výklad | Parameter |
|---|---|---|
| čl. 3 ods. 4 – „bonifikuje koeficientom 3“ | hodina výučby v EN = 2 × 3 = 6 h | `en_koef_nasobi_pripravu` (false → 3 h) |
| čl. 5 ods. 1 A – dvojnásobok hodín zodpovedného riešiteľa | zvyšuje jeho podiel na financiách, nie záťaž v hodinách (čl. 5 ods. 3) | `nasobok_zodpovedny_riesitel` |
| priemer fakulty pri prepočte (čl. 3–5) | priemer pôvodných hodnôt hodnotených učiteľov fakulty, ktorí boli aktívni celé obdobie oblasti | `prepocet_chybajuceho_obdobia` |
| skupina pre štandardizáciu (čl. 7 ods. 1.5) | fakulta | `standardizacia_skupina` (`vsetci`) |
| celkové skóre učiteľa | váhy 40/40/20 ako sumárne skóre pracoviska (čl. 6) | `vahy_ucitelia` |
| % fondu pri neúplnom období | záťaž sa počíta za čas, keď bol učiteľ aktívny | – |
| riešiteľská kapacita | ak nie je zadaná, súčet hodín účastníkov | – |
| hodiny priamej výučby z rozvrhu | týždenná akcia × 13 týždňov, pri párnom/nepárnom týždni × ½; bloková akcia s dátumom sa započíta raz; spoločná akcia („Ďalej vyučujú“) sa delí rovným dielom | `tyzdne_vyucby` (26 = 2 × 13) |
| odučení študenti (čl. 7 ods. 1.1 b) | študenti predmetu sa rozdelia medzi skupiny prednášok a cvičení podľa kapacity; učiteľ má väčšiu z hodnôt (študenti jeho prednášok / jeho cvičení) | – |
| jazyk výučby | poznámka „Výučba v AJ“ → EN, skupiny mobilitných študentov („mob“, erasmus) → MOB | – |
| doktorandské predmety | UIS k nim neuvádza počet študentov – započítajú sa iba hodiny | – |
| projekt bez vykázaných hodín | suma sa rozdelí rovným dielom medzi riešiteľov projektu v UIS (zodpovedný riešiteľ výskumného projektu 2×); výsledok je označený ako odhad | – |
| interné granty (GA SPU a pod.), mobilitné a štipendijné programy | nezapočítavajú sa (pozn. 8 uvádza iba externé zdroje) | kategória druhu v okne Projekty z UIS |
| publikácie z knižnice | rok = rok vykázania (pole 985); V1 monografia = typ MON, ostatné V1 (editovaná kniha, zborník) = editovaná kniha; V2/V3 indexované = indexovanie WoS alebo Scopus; kvartil AIS z metrík časopisu (T16 $D) za rok vydania; ak podiel chýba, 1 / počet autorov; výstupy O, P, I sa nezapočítavajú | úprava dvojklikom pred uložením |
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
spu_zataz/epca.py           publikácie z knižnice SPU (EPCA / CREPČ), odstránenie duplicít
spu_zataz/metodika.py       podmienky hodnotenia: čítanie dokumentu metodiky a parametrov z neho
spu_zataz/ulozisko.py       uloženie / načítanie údajov do priečinka so zložkami
spu_zataz/kontrola.py       kontrola chýbajúcich údajov
spu_zataz/identifikatory.py ORCID, Scopus Author ID, ResearcherID (autority knižnice SPU, register ORCID)
spu_zataz/vystupy.py        export výsledkov
spu_zataz/updater.py        aktualizácie z GitHub Releases
spu_zataz/gui*.py           grafické rozhranie (tkinter)
tests/                      testy
.github/workflows/          testy a zostavenie exe
```
