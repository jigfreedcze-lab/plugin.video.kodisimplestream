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

### Požadavky
- Kodi 19.0 (Matrix) nebo novější (testoval jsem jen na Kodi 21)
- Aktivní účet na Webshare.cz

### Podpora
Pokud narazíte na problémy nebo máte otázky:
- Prohlédněte si [Issues](https://github.com/jigfreedcze-lab/plugin.video.kodisimplestream/issues)
- Vytvořte nový problém, pokud váš problém ještě nebyl nahlášen

Nápady na vylepšení i opravy jsou vítány – založte Issue nebo rovnou pošlete Pull request.

### TMDb Helper integrace
1. Zkopírujte soubor `docs/tmdbhelper/kodisimplestream.json` do:
   `userdata/addon_data/plugin.video.themoviedb.helper/players/kodisimplestream.json`
   Pokud už tam starší soubor je, přepište jej novou verzí.
2. V TMDb Helper otevřete nastavení přehrávačů a povolte/vyberte `KodiSimpleStream`.
3. TMDb Helper pak při kliknutí na film/epizodu zavolá trasu:
   `plugin://plugin.video.kodisimplestream/?action=tmdbh_play...`
4. Addon vyhledá Webshare zdroje a při vypnutém auto-play zobrazí modální výběr zdroje přímo v TMDb Helper přehrávacím toku. Po výběru se zdroj vyřeší přes `play_ident`.
   Před otevřením výběru zjistí skutečné parametry prvních 10 zdrojů (nejvýše 1,2 s, co nedorazí, je bez nich).

Auto-play přehraje první z 5 nejlepších zdrojů nad prahem skóre, který není trailer/ukázka, část (CD1, 1of2)
ani film z jiného roku; jinak otevře výběr zdroje. Délku proti stopáži kontrolovat nemůže: TMDb Helper přehrávači
stopáž nepředává (v řetězci přehrávače není žádná proměnná s délkou), takže v tomto toku jsou jen rozlišení a zvukové stopy.

Nová nastavení addonu (sekce **TMDb Helper**):
- **Auto-play best source** – automaticky přehraje nejlépe skórovaný zdroj.
- **Auto-play minimum score** – minimální skóre, od kterého dojde k auto-play.
- **Maximum ranked results** – omezení počtu kandidátů v seznamu.
- **Preferred quality mode** – jemné řazení kvality (`1080p_or_best`, `720p_or_best`, `highest`).
- **Show debug scores in labels and logs** – zobrazí skóre i v názvech položek a logu.

Poznámka: přesnost párování závisí na kvalitě názvů souborů na Webshare a kvalitě metadat předaných z TMDb Helper.
