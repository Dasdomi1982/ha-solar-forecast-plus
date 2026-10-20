# Changelog

## 0.4.3 (2026-10-20)
* Lernen: Beim Start von Home Assistant konnte ein zweiter Eintrag den Lern-Teil ersetzen; dann liefen Abendauswertung und Tageskorrektur nicht. Behoben.

## 0.4.2 (2026-10-20)
* Gesamtsensoren: minütliche Aktualisierung läuft im Event-Loop (Thread-Warnung behoben); Attribute `teile_kwh` und `ohne_korrektur_kwh` in kWh.

## 0.4.1 (2026-10-20)
* manifest.json: Schlüssel sortiert (hassfest).

## 0.4.0 (2026-10-20)
* **Korrektur im Tagesverlauf:** Der Ertrag bis jetzt wird alle 5 Minuten mit der
  Prognose verglichen; der Rest des Tages wird angepasst (abklingend zum Abend).
* **Lernen an allen Tagen:** Jeder Tag zählt, gewichtet nach Bewölkung. „Tage bis
  zur Anwendung“ zählt jetzt gewichtete Tage.
* **Faktor je Jahreszeit:** eigener Faktor je Monat, mit dem Gesamtfaktor gemischt.
* **Tagesprofil:** lernt aus dem Recorder-Verlauf, ob morgens/abends regelmäßig
  weniger kommt (gelernte Dämpfung), Tagessumme bleibt gleich.
* **Gesamtsensoren:** `sensor.solar_forecast_plus_gesamt_heute`, `…_heute_rest`,
  `…_morgen`, `…_leistung`.
* **Bewölkung von Open-Meteo:** der Bewölkungssensor ist optional.
* **Treffsicherheit:** neuer Sensor `sensor.solar_forecast_plus_treffsicherheit`
  mit Abweichung der Vortagesprognose und Vergleich mit einem zweiten Wettermodell.
* Nur noch 7 statt 92 vergangene Tage pro Abruf.
* Gelernte Korrekturen werden auf die unveränderte Prognose angewendet (keine
  Rückkopplung beim Lernen).

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
