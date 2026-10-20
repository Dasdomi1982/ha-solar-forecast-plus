# Changelog

## 0.2.0 (2026-10-19)
Basis: ha-open-meteo-solar-forecast 0.1.33 / open-meteo-solar-forecast 0.1.32.

* Bibliothek eingebettet (`forecast_lib`), keine Abhängigkeit mehr vom PyPI-Paket.
* Fehlende Werte der Open-Meteo-Antwort (Schneehöhe, Diffus-/Direktstrahlung,
  Sonnenauf-/untergang, ganze Variablen) brechen die Prognose nicht mehr ab.
* Nach einer Optionsänderung dient die letzte Prognose als Notreserve, falls die API
  ausfällt.
* Neu: selbstlernender Wirkungsgrad mit drei Sensoren und zwei Diensten.
* Diagnosedaten um Lücken-Zähler und Lernstand erweitert.
* Eigenes Icon (hell/dunkel) im Ordner `brand/`.
