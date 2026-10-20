# Changelog

## 0.3.0 (2026-10-20)
* Eigene Domain `solar_forecast_plus` (Ordner `custom_components/solar_forecast_plus`).
  Plus läuft damit parallel zur originalen Integration; Einträge müssen neu angelegt werden.
* Lern-Sensoren heißen jetzt `sensor.solar_forecast_plus_pv_faktor`,
  `…_ertrag_zu_prognose` und `…_klare_tage`; Dienste `solar_forecast_plus.learning_*`.
* Gerätename „Solar Forecast Plus“.

## 0.2.2 (2026-10-20)
* Lizenzpflichten: Änderungshinweis im Kopf jeder geänderten Datei, NOTICE ergänzt.
* Quellenhinweis für die Wetterdaten (Open-Meteo.com, CC BY 4.0) im README und in der NOTICE.

## 0.2.1 (2026-10-20)
* Übersetzungen: Beschreibung des Felds „history“ ohne geschweifte Klammern (hassfest-Fehler).

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
