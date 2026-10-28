# Benchmark hledání na Webshare

Měří, jak dobře doplněk najde a seřadí správné soubory pro film nebo epizodu. Testuje oba toky:

- **a** – vlastní hledání přes TMDb v doplňku (`matching.build_search_queries` + `rank_files`)
- **b** – přehrávač pro TMDb Helper (`build_tmdbh_queries` + řazení jako `search_and_score_tmdbh`)

Vyhodnocení běží offline nad zamrazeným snímkem odpovědí Webshare, takže výsledky jsou opakovatelné a porovnatelné.

## Co je kde

| Soubor | Obsah |
|---|---|
| `cases.json` | 59 případů (filmy a epizody, 11 kategorií) s metadaty z TMDb, `split` train/holdout |
| `evaluate.py` | vyhodnocení a porovnání výsledků |
| `build_benchmark.py` | sestavení snímku: metadata z TMDb (`tmdb`), odpovědi Webshare (`fetch`), pooly a split (`finalize`) |
| `results/baseline.json` | výsledky před optimalizací skórování (commit 547af9d) |
| `results/current.json` | výsledky aktuální verze |

**Snímek Webshare (cache odpovědí, pooly souborů a štítky) je v soukromém repozitáři**, protože obsahuje názvy souborů z Webshare. Výsledky v `results/` jsou bez názvů a identifikátorů souborů. Snímek naklonujte vedle tohoto repozitáře:

```
git clone git@github.com:jigfreedcze-lab/kss-benchmark-data.git ../KodiSimpleStream-benchmark
```

Jinou cestu zadejte přes `--data` nebo proměnnou `KSS_BENCH_DATA`.

## Použití

```
python -X utf8 tools/benchmark/evaluate.py --compare tools/benchmark/results/current.json
```

- `--split train|holdout|all`, `--flow a|b|both`, `--per-case` (podrobnosti po případech, včetně top 10)
- `--preference cz_audio|cz_subs`, `--tmdbh-quality …` – nastavení doplňku
- `--public-json results/<název>.json` – uloží výsledky bez názvů souborů (do repozitáře)
- `--json <soubor>` – úplné výsledky včetně názvů souborů (**necommitovat**)

Hlavní metrika **SCORE** = průměr Top1, P@5, MRR a Recall@10 (1,0 = dokonalé).

## Pravidla

- Ladit jen na případech `train`, `holdout` slouží ke kontrole, že zlepšení platí obecně.
- Žádná pravidla šitá na konkrétní tituly z benchmarku.
- Po změně skórování přegenerovat `results/current.json` a commitnout ho spolu se změnou.
- Data ze snímku (názvy souborů, identifikátory) do tohoto repozitáře nepatří.
