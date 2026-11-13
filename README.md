![Version](https://img.shields.io/github/v/tag/jigfreedcze-lab/plugin.video.kodisimplestream?label=version&logo=github)
![License](https://img.shields.io/github/license/jigfreedcze-lab/plugin.video.kodisimplestream)

# KodiSimpleStream - Kodi Plugin pro Webshare.cz

KodiSimpleStream je jednoduchý Kodi plugin, který umí vyhledávat a přehrávat videa z [Webshare.cz](https://webshare.cz)

> **Tato verze je fork** doplňku [badmin15/plugin.video.kodisimplestream](https://github.com/badmin15/plugin.video.kodisimplestream) (TMDb Helper, výběr zdrojů), který vychází z původního [Kecerim24/plugin.video.kodisimplestream](https://github.com/Kecerim24/plugin.video.kodisimplestream). Navíc: volitelné hledání filmů a seriálů přes TMDb místo nefunkčního ČSFD, řazení a stránkování výsledků z Webshare, rozpoznání CZ dabingu a titulků a opravy chyb. Repozitář původního autora níže v návodu instaluje jeho verzi bez těchto změn.

### Instalace této verze
1. Stáhněte ZIP této verze (`plugin.video.kodisimplestream-<verze>.zip`), případně ho sestavte z repozitáře:
   ```
   git archive --format=zip --prefix=plugin.video.kodisimplestream/ -o plugin.video.kodisimplestream.zip HEAD
   ```
2. V Kodi povolte *Nastavení → Systém → Doplňky → Neznámé zdroje*.
3. *Doplňky → Instalovat ze souboru ZIP* → vyberte stažený ZIP. Závislosti si Kodi stáhne z oficiálního repozitáře samo.

Pokud máte nainstalovaný repozitář *kecerim's repo*, Kodi tuto verzi přepíše původní, jakmile autor vydá vyšší verzi. Chcete-li zůstat u této verze, repozitář autora neinstalujte nebo u doplňku vypněte automatické aktualizace.

Testy: `python tests/run_tests.py`

### Instalace původní verze (z repozitáře autora)
1. Stáhněte si zip [nejnovější verze repozitáře](https://github.com/Kecerim24/repository.kecerim/releases/latest)
2. Nainstalujte plugin přes Správce doplňků v Kodi:
   - Přejděte do Doplňků
   - Klikněte na ikonu instalátoru balíčků
   - Vyberte "Instalovat ze souboru zip"
   - Zvolte stažený zip soubor
3. Jděte do Instalovat z repozitáře:
   - Vyberte kecerim's repo > doplňky videí > kodisimplestream
### Nebo
1. Přidejte si zdroj repozitáře do Správce souborů:
   - Přejděte do Správce souborů
   - Klikněte na "Přidat zdroj"
   - Do pole "Cesta k médiu" zadejte: https://kecerim24.github.io/repository.kecerim/
   - Pojmenujte zdroj (např. "Kecerim Repo")
2. Nainstalujte repozitář:
   - Přejděte do Doplňků
   - Klikněte na ikonu instalátoru balíčků
   - Vyberte "Instalovat ze souboru zip"
   - Najděte přidaný zdroj a vyberte repository.kecerim-x.x.x.zip
3. Nainstalujte plugin:
   - Jděte do "Instalovat z repozitáře"
   - Vyberte kecerim's repo > doplňky videí > kodisimplestream

### Konfigurace
1. Po instalaci přejděte do nastavení pluginu
2. Zadejte své uživatelské jméno a heslo do Webshare.cz
3. *Volitelně:* pro hledání filmů a seriálů zadejte v sekci Nastavení TMDb svůj TMDb API klíč, viz [TMDb API klíč](#tmdb-api-klíč-volitelné)

### TMDb API klíč (volitelné)
Hledání filmů a seriálů (české názvy, plakáty, řady a epizody) používá databázi [TMDB](https://www.themoviedb.org). Bez klíče doplněk funguje dál, jen v menu místo hledání filmů a seriálů najdete položku *Zapnout hledání filmů a seriálů (TMDb)…* s krátkým návodem.

> **Nechcete zakládat klíč?** Filmy a seriály můžete procházet v doplňku TMDb Helper a KodiSimpleStream použít jen k přehrání (viz [TMDb Helper integrace](#tmdb-helper-integrace)). Postup níže pak nepotřebujete.

#### Jak získat vlastní klíč
Klíč je zdarma a vyřízení trvá pár minut. Každý uživatel si zakládá vlastní – doplněk žádný sdílený klíč neobsahuje.

1. Založte si účet na [themoviedb.org/signup](https://www.themoviedb.org/signup) a potvrďte e-mail.
2. Otevřete [Nastavení → API](https://www.themoviedb.org/settings/api) a klikněte na **Create** (případně *Request an API Key*).
3. Zvolte typ **Developer** a odsouhlaste podmínky použití.
4. Vyplňte formulář. Pro osobní použití v Kodi stačí třeba:
   - **Type of Use:** Personal
   - **Application Name:** KodiSimpleStream (personal Kodi add-on)
   - **Application URL:** `http://localhost`
   - **Application Summary** (TMDb chce podrobnější popis, stačí upravit tento vzor):
     ```
     Personal, non-commercial use of the KodiSimpleStream add-on for the Kodi media center on my own devices at home. It uses the TMDB API to search for movies and TV shows by title and to show their Czech titles, release years, plot summaries, posters, seasons and episode lists. The data is only displayed to me, it is not stored in any public database, redistributed or sold. TMDB is credited as the data source in the add-on.
     ```
   - zbytek formuláře jsou vaše kontaktní údaje
5. Po odeslání uvidíte **API Key** (32 znaků) a **API Read Access Token** (dlouhý). Doplněk přijme oba, na televizi se ovladačem snáz zadává kratší API Key.
6. V Kodi otevřete nastavení doplňku → **Nastavení TMDb** → **TMDb API klíč** a klíč vložte. **Potvrďte tlačítkem OK** – Zpět nebo Esc zadaný klíč zahodí. Po návratu do menu doplňku se objeví hledání filmů a seriálů.

### Zdroj dat
[![TMDB](https://www.themoviedb.org/assets/v4/logos/v2/blue_short-8e7b30f73a4020692ccca9c88bafe5dcb6f8a62a4c6bc55cd9ba82bb2cd95f6c.svg)](https://www.themoviedb.org)

Informace o filmech a seriálech (názvy, popisy, plakáty, řady a epizody) pochází z [TMDB](https://www.themoviedb.org).
This product uses TMDB and the TMDB APIs but is not endorsed, certified, or otherwise approved by TMDB.

### Použití
1. Spusťte plugin z vašich Kodi doplňků
2. Použijte vyhledávací funkci pro nalezení videí (hodně možností že?)
3. Vyberte video pro spuštění přehrávání

#### Skutečné parametry souborů
Seznam výsledků se zobrazí hned. U prvních 15 souborů si pak doplněk na pozadí (anonymně, bez přihlášení) zjistí
z Webshare skutečnou délku, rozlišení a zvukové stopy a seznam jednou obnoví:
- délka je vedle názvu; **oranžová s vykřičníkem**, když neodpovídá stopáži z TMDb (film mimo 0,8–1,5×,
  epizoda pod 0,45× nebo nad 1,5×) – nejspíš jiný film, epizoda, trailer nebo jen část (CD1). Pořadí se nemění.
- štítek kvality ukazuje skutečné rozlišení místo odhadu z názvu, popis (Informace) skutečné video, datový tok a stopy,
  skin zobrazí ikony kodeků a kanálů.
- česká zvuková stopa (CZE) se počítá jako CZ dabing – štítek i preference jazyka, i když v názvu není.
  Chybějící stopa CZE nic neznamená (mp4/avi mívají jedinou stopu označenou ENG nebo UND).

Údaje se pamatují 14 dní (nejvýše 2000 souborů, `addon_data/plugin.video.kodisimplestream/file_details.json`).
Když Webshare neodpoví, seznam zůstane jen s údaji z názvu souboru.

#### Animovaný náhled (zobrazení Wide list)
Ve stejném běhu na pozadí doplněk složí z náhledového pásu prvních 10 souborů animovaný GIF (snímek za sekundu,
dokola) a seznam jednou obnoví. Ve zobrazení **Wide list** (skin Estuary) pak hraje jen velký panel vybraného
souboru, řádky zůstanou statické. Kodi animuje každý viditelný GIF, proto je animace jen v obrázku `poster`:
v zobrazení **Icon wall** by se hýbaly všechny dlaždice. Výběr zdroje TMDb Helperu ukazuje jen ikonu, animace v něm není.
Seznamy dál mají typ obsahu `videos` (typ `movies` by přidal zobrazení, kde se hýbe všechno, a Kodi by soubory
považovalo za filmy). GIFy leží v `special://temp` (Kodi ho maže při startu), jeden má asi 0,4 MB.
Když se cokoli nepovede, zůstane statický náhled. Vypíná se v nastavení **Hledání → Animovaný náhled vybraného souboru**
(jen se zapnutým náhledem videa místo odznaku kvality). Na Android TV zatím nevyzkoušeno (výkon a paměť).

### Požadavky
- Kodi 19.0 (Matrix) nebo novější (testováno jen na Kodi 21.3, Windows a Android TV)
- Aktivní účet na Webshare.cz
- Volitelně [TMDb Helper](#tmdb-helper-integrace): otestováno s verzí **5.4.16** z oficiálního repozitáře Kodi. Řada 6.x z repozitáře autora TMDb Helperu zatím vyzkoušená není.

### Dětské hledání
Hledání filmů a seriálů v TMDb. Se zapnutým **Dětským režimem** (`kids_only`) pustí jen tituly vhodné pro dítě daného věku,
bez něj najde všechno (kromě titulů pro dospělé podle TMDb). Celé běží uvnitř doplňku,
TMDb Helper se nijak neupravuje. Potřebuje TMDb API klíč. V hlavním menu doplňku je jedna položka **Hledat filmy a seriály**, která vede na podnabídku (`?action=kids_menu`) se třemi položkami:
**Hledat vše**, **Hledat filmy**, **Hledat seriály** (v dětském režimu jsou tyto tři položky přímo v hlavním menu).
Samotné hledání (`?action=kids_search`, volitelně `type=movie|tv|both` a `query=...`, bez dotazu se zeptá klávesnicí)
hledá filmy i seriály.
Nad výsledky je položka **Nové hledání**, která nahradí aktuální seznam. Mimo dětský režim je v kontextovém menu každého
výsledku **Trakt (seznam, zhlédnuto…)**, která otevře nabídku Traktu z TMDb Helperu (watchlist, sbírka, zhlédnuto).
V dětském režimu tato položka v kontextovém menu **není**.

Nastavení (sekce **Dětské hledání**):
- **Věk dítěte** (`kids_age`, výchozí 8, povolené 3 až 18) – tituly s vyšším věkovým hodnocením se nezobrazí.
  Všechno ostatní se odvodí z tohoto čísla.
- **Přísnost** (`kids_percentile`, výchozí 75, povolené 50 až 100) – hodnocení se nejdřív sloučí po zemích (za každou
  zemi platí její nejpřísnější) a z věků zemí se vybere percentil: 100 = rozhoduje nejpřísnější země, 50 =
  medián. Nižší přísnost toleruje jednu odlehlou zemi (chybu v datech), vyšší ji bere vážně. Přesná pravidla (kdy se
  který percentil použije a jak se zachází s nepřehlédnutelně přísnými hodnoceními) se mohou v dalších verzích
  zpřísnit, proto je zde nepopisujeme. Kdo chce nejopatrnější chování, nastaví 100.
- **Řazení výsledků** (`kids_sort`: relevance (pořadí z TMDb) / popularita / hodnocení / rok vydání, výchozí relevance) a **Nejvíce výsledků**
  (`kids_limit`, výchozí 20, povolené 5 až 60) – týká se jen hledání filmů a seriálů v TMDb, ne řazení souborů na Webshare (`ws_sort`).
  Platí v dětském režimu i bez něj.
- **Minimum hlasů** (`kids_min_votes`, výchozí 20) – titul s méně hlasy na TMDb se skryje, 0 = bez omezení.
  Jen v dětském režimu.
- **Tituly bez věkového hodnocení** (`kids_unrated`: zakázat / povolit, výchozí zakázat) – co se stane s titulem,
  u kterého TMDb nezná žádné použitelné hodnocení.
- **Dětský režim** (`kids_only`, vypnuto) – hledání filtruje podle věku a doplněk nabídne jen dětské hledání a odmítne všechno ostatní kromě
  přehrání z TMDb Helperu (to před startem zkontroluje věk titulu, viz níže) (hledání na Webshare i v TMDb, výběr titulu, epizody, náhledy, detaily souborů, přímé
  přehrání). V tomto režimu se nikdy neukáže ani výběr zdroje (jako se zapnutým `tmdbh_no_picker`).
  Při **vypnutém** dětském režimu se věk dítěte, přísnost, minimum hlasů, žánry ani nehodnocené tituly nepoužijí
  (hledání najde všechno, kromě titulů pro dospělé podle TMDb); platí jen **Řazení výsledků** (`kids_sort`) a
  **Nejvíce výsledků** (`kids_limit`).

Jak se věk titulu odvodí:
- Doplněk má vestavěnou tabulku „hodnocení -> minimální věk“ pro CZ, SK, DE, AT, CH, US, GB, FR, ES, IT, NL, SE, NO,
  DK, FI, CA (včetně CA-QC) a BR, ještě AU, NZ, IE, PL a HU (jedna tabulka na zemi, platí pro filmy i seriály). Bere se hodnocení **ze všech těchto zemí** (z TMDb: datumy vydání filmu, hodnocení seriálu). Za každou zemi platí její
  nejpřísnější hodnocení a z věků zemí se vybere věk podle nastavení **Přísnost** (viz výše). Titul projde, jen
  když vybraný věk není vyšší než věk dítěte. Hodnocení zemí mimo tabulku se při výpočtu věku neberou v úvahu, ale titul, který má hodnocení jen v takových
  zemích, se nepovažuje za nehodnocený a vyřadí se (i při povolení nehodnocených titulů).
- Značky „bez hodnocení“ (NR, UR, Unrated, prázdné hodnocení) věk nenesou a ignorují se. Pokud nezbude žádné
  hodnocení, rozhoduje **Tituly bez věkového hodnocení**.
- Chybějící nebo porušený údaj o žánrech (nebo o počtu hlasů) titul vyřadí.
- Hodnocení ze země z tabulky, které tabulka nezná a není to značka „bez hodnocení“, titul vyřadí (nic se
  nehádá).

| Země | Příklady (hodnocení = minimální věk) |
|------|--------------------------------------|
| CZ | film U = 0, 12+ = 12, 15+ = 15, 18+ = 18; seriál 0+, 5+, 7+, 9+, 12+, 15+, 18+ |
| DE | 0, 6, 12, 16, 18 |
| US | film G = 0, PG = 8, PG-13 = 13, R = 17, NC-17 = 18; seriál TV-Y = 0, TV-Y7 = 7, TV-G = 0, TV-PG = 8, TV-14 = 14, TV-MA = 17 |
| GB | U = 0, PG = 8, 12A = 12, 12 = 12, 15 = 15, 18 = 18 |
| CA | G = 0, PG = 8, 14A = 14, 18A = 18, R = 18 |

Další pravidla (první, které titul vyřadí, rozhoduje):
1. Titul pro dospělé se vyřadí.
2. Zakázané žánry podle věku: do 11 let horor, thriller, krimi, válečný, mysteriózní a „válka a politika“;
   od 12 do 15 let horor a válečný; od 16 let žádné. Povolené žánry ani jazyk se nevyžadují.
3. Titul s méně hlasy na TMDb, než je **Minimum hlasů** (`kids_min_votes`, výchozí 20), se vyřadí.

Výsledek se vypíše jako `Název (rok)  [6+]` (věk, který titulu vyšel, jen když je znám). Film se po výběru přehraje
přes `plugin://plugin.video.themoviedb.helper/?info=play&tmdb_type=movie&tmdb_id=<id>`, seriál otevře řady přes
`plugin://plugin.video.themoviedb.helper/?info=seasons&tmdb_type=tv&tmdb_id=<id>`; hledání zdroje na Webshare
pak dělá přehrávač KodiSimpleStream z [TMDb Helper integrace](#tmdb-helper-integrace).

Omezení:
- TMDb nemá věkové hodnocení u všech titulů (zvlášť u starších a českých). Takový titul se ve výchozím nastavení
  nezobrazí; po povolení **Tituly bez věkového hodnocení** projdou i nehodnocené tituly, třeba pro dospělé.
- Údaje na TMDb (žánry, hodnocení) nejsou dokonalé a špatné hodnocení z jedné země titul zablokuje. Filtr je
  pomůcka, ne záruka. Spolehlivý seznam jsou oblíbené položky (Favourites), které si rodič vybere sám.
- **Kontrola při přehrání:** v dětském režimu se věk titulu ověří i těsně před přehráním přes TMDb Helper
  (`tmdbh_play`), takže zakázaný titul vybraný jinde (hledání nebo widget v TMDb Helperu) se nepřehraje a ukáže se
  oznámení „Nevhodné pro věk N“. U seriálu se hodnotí seriál, ne epizoda; rozhoduje věk a zakázané žánry (**Minimum
  hlasů** se při přehrání nepoužije) a **Tituly bez věkového hodnocení** se řídí nastavením jako v hledání. Zjistí se
  TMDb id (případně z IMDb id přes TMDb `/find`); bez TMDb API klíče, při chybě sítě nebo TMDb či když titul nejde
  určit, se přehrání zamítne. Kontrola stojí 1 až 2 dotazy na TMDb navíc, při vypnutém dětském režimu žádný.
- **TMDb Helper sám věk nefiltruje.** Prohlížení v něm (jeho hledání, widgety, seznamy) zůstává dětem dostupné a
  zakázané tituly tam uvidí, jen se nepřehrají. Doporučení: v dětském profilu skinu skrýt sekci Doplňky (video
  doplňky) nebo ji zamknout, ať se dítě k TMDb Helperu vůbec nedostane. Zámek nastavení Kodi, profilu, rodičovskou kontrolu a skrytí položek v
  tapetě (skinu) nastavuje Kodi a skin, tento doplněk je nenahrazuje.
- **Co má rodič zamknout v Kodi** (doplněk to sám zajistit nemůže):
  - **Nastavení:** nastavení doplňku (včetně vypnutí dětského režimu a věku) jde změnit jen přes Nastavení Kodi. V
    *Nastavení → Profily → Hlavní zámek* nastavte kód a u dětského profilu zamkněte *Nastavení a správce souborů*.
  - **Ovládání zvenčí:** JSON-RPC, webové rozhraní, Kore, UPnP a AirPlay (*Nastavení → Služby → Ovládání*) umí přehrát
    libovolnou adresu a kontrola věku se pak neuplatní u podstrčeného názvu. Vypněte je nebo je dejte pod heslo.
  - **TMDb Helper a jiné přehrávače:** kontrola věku platí jen pro přehrávač KodiSimpleStream. Jiný přehrávač v
    TMDb Helperu, jiný video doplněk nebo knihovna Kodi ji obejdou. Seriálové výsledky dětského hledání se otevírají
    v TMDb Helperu, takže se dítě k jeho nabídkám dostane i tak.
  - **Soubory:** `addon_data` (nastavení doplňku, heslo Webshare, TMDb klíč) je čitelné ve Správci souborů.
  - **Shoda souboru s titulem:** zdroj se vybírá podle názvu souboru na Webshare. Špatně pojmenovaný soubor se může
    přehrát, i když neodpovídá titulu.

### Podpora
Pokud narazíte na problémy nebo máte otázky:
- Prohlédněte si [Issues](https://github.com/jigfreedcze-lab/plugin.video.kodisimplestream/issues)
- Vytvořte nový problém, pokud váš problém ještě nebyl nahlášen

Nápady na vylepšení i opravy jsou vítány – založte Issue nebo rovnou pošlete Pull request.

### TMDb Helper integrace
1. Zkopírujte oba soubory `docs/tmdbhelper/kodisimplestream.json` a `docs/tmdbhelper/kodisimplestream_select.json` do:
   `userdata/addon_data/plugin.video.themoviedb.helper/players/`
   Pokud už tam starší soubor je, přepište jej novou verzí. Starší soubor posílal místo originálního názvu
   seriálu a TMDb id jen `_` (neexistující klíče `{show_originaltitle}`, `{tmdb_id}`, `{imdb_id}`).
   - `kodisimplestream.json` (přehrávač **KodiSimpleStream**) je hlavní přehrávač: podle nastavení auto-play
     zdroj přehraje sám, nebo otevře výběr zdroje.
   - `kodisimplestream_select.json` (přehrávač **KodiSimpleStream – výběr zdroje**) otevře výběr zdroje vždy,
     i se zapnutým auto-play. Hodí se, když auto-play vybere špatný soubor. V seznamu přehrávačů je hned
     za hlavním; výchozí přehrávač TMDb Helperu je uložený podle názvu souboru (`kodisimplestream.json play_movie`),
     druhý soubor ho tedy nezmění.
2. V TMDb Helper otevřete nastavení přehrávačů a povolte/vyberte `KodiSimpleStream`.
3. TMDb Helper pak při kliknutí na film/epizodu zavolá trasu:
   `plugin://plugin.video.kodisimplestream/?action=tmdbh_play...`
4. Addon vyhledá Webshare zdroje a při vypnutém auto-play zobrazí modální výběr zdroje přímo v TMDb Helper přehrávacím toku. Po výběru se zdroj vyřeší přes `play_ident`.
   Před otevřením výběru zjistí skutečné parametry prvních 10 zdrojů (nejvýše 1,2 s, co nedorazí, je bez nich).

Auto-play přehraje první z 5 nejlepších zdrojů nad prahem skóre, který není trailer/ukázka, část (CD1, 1of2),
film z jiného roku ani soubor s datovým tokem nad limitem (viz **Auto-play maximum bitrate** níže); jinak otevře
výběr zdroje. Délku proti stopáži kontrolovat nemůže: TMDb Helper přehrávači stopáž nepředává (v řetězci přehrávače
není žádná proměnná s délkou), takže v tomto toku jsou jen rozlišení, zvukové stopy a datový tok.

Jiný zdroj, než jaký vybere auto-play: v TMDb Helperu otevřete kontextovou nabídku filmu nebo epizody,
zvolte **Select player** (TMDb Helper nemá český překlad, položka je anglicky) a v seznamu přehrávačů
**Play with KodiSimpleStream – výběr zdroje**. Při zapnutém sloučení přehrávačů (nastavení TMDb Helperu
*Combine all players for plugin into single entry*) nejdřív zvolte položku tohoto doplňku, **kodisimplestream** (název z `addon.xml`), a pak tento přehrávač. Otevře se stejný výběr zdroje
jako při vypnutém auto-play (včetně minimálního skóre a změny hledání).

Up Next (automatické nabídnutí dalšího dílu):
- Hlavní přehrávač `kodisimplestream.json` má `"make_playlist": "upnext"`, takže TMDb Helper po spuštění epizody
  připraví další díly pro doplněk **Up Next** (`service.upnext`), který musí být nainstalovaný. Funguje jen hlavní
  přehrávač, ne `kodisimplestream_select.json`.
- Při vypnutém auto-play (výchozí) se další díl otevře ve výběru zdroje. Když nikdo nic nevybere, nic se nepřehraje.
- Stávající uživatelé musí po aktualizaci **znovu zkopírovat** `kodisimplestream.json` do
  `userdata/addon_data/plugin.video.themoviedb.helper/players/`, jinak se Up Next nezapne.
- Chování řetězu více dílů za sebou bylo ověřeno jen čtením kódu, ne v praxi. V okrajových případech (třeba výběr
  zdroje trvá déle než 30 s) se nabídka Up Next nemusí objevit.

Nová nastavení addonu (sekce **TMDb Helper**):
- **Nikdy nezobrazovat výběr zdroje** (`tmdbh_no_picker`, vypnuto) – ať přehrávač výběr zdroje neotevře nikdy: ignoruje i
  druhý přehrávač „výběr zdroje“, auto-play se použije vždy a když žádný zdroj nevyhovuje, zobrazí upozornění a
  přehrání skončí. Hodí se pro děti, které by si neuměly vybrat. V dětském režimu platí vždy.
- **Auto-play best source** – automaticky přehraje nejlépe skórovaný zdroj.
- **Auto-play minimum score** – minimální skóre, od kterého dojde k auto-play.
- **Další zdroj při chybě souboru:** když Webshare u vybraného souboru vrátí jasnou chybu (např. „File temporarily
  unavailable“), auto-play zkusí dalšího nejlepšího kandidáta (jen nad prahem shody a s týmiž kontrolami jako první
  volba). Nejvýš 3 pokusy a nový pokus se nezačne, když od prvního uplynulo víc než 8 s. Při timeoutu, chybě spojení
  nebo přihlášení se nezkouší nic dalšího. Když se nic nepodaří, ukáže se dialog „Soubory k tomuto titulu jsou právě
  nedostupné, zkuste to později“.
- **Auto-play maximum bitrate** – nejvyšší průměrný datový tok v Mbit/s, který auto-play ještě spustí (výchozí 30,
  0 = bez omezení). Brání tomu, aby se automaticky pustil třeba 60GB 4K remux (50–80 Mbit/s), který připojení
  nestihne přenášet a video se zasekává. Nastavte ho asi na dvě třetiny rychlosti připojení (pro 50 Mbit/s tedy 30).
  - Datový tok se bere z údajů Webshare o souboru (jeho datový tok, jinak velikost / délka). Doplněk si je při
    zapnutém limitu před auto-play vyžádá u kandidátů (nejvýše 2 s, nejvýše 10 souborů); když nedorazí, odhadne
    tok z velikosti souboru a obvyklé délky (film 2 h, epizoda 45 min).
  - Soubor nad limitem auto-play nepřehraje a nezabere mu ani jedno z 5 míst: místo něj se posoudí další zdroj
    v pořadí (nejdál po hranici **Maximum ranked results**). Když se do limitu nevejde žádný vhodný zdroj, otevře se
    výběr zdroje s upozorněním „Nejlepší zdroje nesedí, vyberte ručně“.
  - Ve výběru zdroje zůstanou i soubory nad limitem (můžete je spustit ručně), ve druhém řádku mají oranžově datový
    tok s vykřičníkem, např. `≈72 Mbit/s !`; `≈` znamená odhad z velikosti. V informacích o položce je i upozornění
    na limit.
  - V pořadí zdrojů soubor nad limitem klesne za vyhovující soubor se stejně dobrou shodou názvu a stejným nebo
    o stupeň nižším rozlišením (počítá se mu, jako by měl o stupeň nižší rozlišení). Před soubor, který názvem sedí
    zřetelně hůř (jiný rok, díl, epizoda), se tím nikdy nedostane.
- **Minimum score in the source picker** – zdroje pod tímto skóre se ve výběru zdroje neukážou; poslední řádek „Zobrazit další zdroje pod minimálním skóre“ zobrazí i všechny skryté. Výsledky ručně změněného hledání se nefiltrují. Výchozí 50 (podle benchmarku zůstane asi 98 % správných souborů a skryje se asi 9 z 10 ostatních), 0 = zobrazit vše. Práh obvykle volte nižší než pro auto-play.
- **Maximum ranked results** – omezení počtu kandidátů v seznamu.
- **Preferred quality mode** – jemné řazení kvality mezi zdroji se stejně dobrou shodou názvu:
  `1080p_or_best` (výchozí) dá přednost 1080p, 4K (2160p) až za ním, ale před 720p a SD – 2160p tedy nevyhrává
  jen tím, že je 2160p; `720p_or_best` řadí od nejvyššího rozlišení, 720p a víc před SD; `highest` vždy nejvyšší
  rozlišení.
- **Show debug scores in labels and logs** – zobrazí skóre i v názvech položek a logu.

Poznámka: přesnost párování závisí na kvalitě názvů souborů na Webshare a kvalitě metadat předaných z TMDb Helper.
