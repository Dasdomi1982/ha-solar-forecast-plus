# ☀️ Solar Forecast Plus

**PV-Ertragsprognose für Home Assistant auf Basis von Open-Meteo, die aus deiner
eigenen Anlage lernt.**

[![HACS Custom](https://img.shields.io/badge/HACS-Custom-41BDF5.svg)](https://hacs.xyz/)
[![Version](https://img.shields.io/github/v/release/Dasdomi1982/ha-solar-forecast-plus)](https://github.com/Dasdomi1982/ha-solar-forecast-plus/releases)
![Home Assistant](https://img.shields.io/badge/Home%20Assistant-2024.4%2B-blue)

> Läuft **parallel** zur originalen Open-Meteo-Integration (eigene Domain
> `solar_forecast_plus`). So lassen sich beide Prognosen direkt vergleichen.

---

## ✨ Auf einen Blick

| | Funktion | Nutzen |
|---|---|---|
| 🛡️ | **Robust bei Datenlücken** | Ein einzelner leerer Wert von Open-Meteo legt nicht mehr die ganze Prognose lahm |
| 🧠 | **Lernt jeden Tag** | Auch trübe Tage zählen – gewichtet nach Bewölkung, klare Tage am stärksten |
| 🍂 | **Faktor je Jahreszeit** | Eigener Wirkungsgrad je Monat (flache Herbstsonne ≠ Sommerhitze) |
| 🌅 | **Tagesprofil je Jahreszeit** | Erkennt Verschattung morgens/abends – getrennt für Winter, Übergang und Sommer |
| ⏱️ | **Korrektur im Tagesverlauf** | Vergleicht den Ertrag bis jetzt und korrigiert den Rest des Tages |
| ➕ | **Gesamtwerte** | Summe aller Dachseiten als eigene Sensoren |
| ☁️ | **Bewölkung von Open-Meteo** | Kein extra Wetter-Sensor nötig |
| 🎯 | **Treffsicherheit** | Abweichung der letzten 30 Tage + Vergleich mit einem zweiten Wettermodell |
| ⚡ | **Schlanke Abfrage** | 7 statt 92 vergangene Tage pro Abruf |

---

## 📦 Installation über HACS

1. **HACS → ⋮ → Benutzerdefinierte Repositories**
   `https://github.com/Dasdomi1982/ha-solar-forecast-plus` als *Integration* hinzufügen.
2. **Solar Forecast Plus** herunterladen und Home Assistant neu starten.
3. **Einstellungen → Geräte & Dienste → Integration hinzufügen → Solar Forecast Plus**
   und pro Dachseite einen Eintrag anlegen (z. B. „Westseite Plus“).

Die Sensoren heißen dann `sensor.westseite_plus_…` und kommen dem Original nicht
in die Quere.

---

## 🏠 Anlagen-Eintrag: Gesamtwerte und Lernen

In **genau einem** Eintrag die letzte Seite der Einstellungen aktivieren
(*Konfigurieren → … → Anlagen-Eintrag*). Dieser Eintrag liefert dann die
Gesamtwerte und lernt für alle Einträge.

| Option | Standard | Bedeutung |
|---|---|---|
| Tatsächlicher PV-Tagesertrag | – | Energie-Sensor, der täglich auf 0 springt (Pflicht) |
| Bewölkung im Tagesmittel | leer | Eigener Sensor in %; leer = Open-Meteo |
| Schwelle für klare Tage | 30 % | Bis hier zählt ein Tag voll, darüber immer weniger |
| Glättung | 0,2 | Gewicht eines neuen klaren Tages |
| Tage bis zur Anwendung | 10 | Gewichtete Tage, bis der Faktor als eingelernt gilt |
| Gelerntes automatisch anwenden | aus | Jahreszeit-Faktor und Tagesprofil korrigieren die Prognose |
| Restlichen Tag korrigieren | an | Korrektur im Tagesverlauf |
| Vergleichs-Wettermodell | `best_match` | Einmal täglich zum Vergleich gerechnet, leer = aus |
| Auswertung nach Sonnenuntergang | 30 min | Zeitpunkt der täglichen Auswertung |

### So lernt Plus

* **Gewichtung:** Ein Tag bis zur Schwelle zählt 1, bei 50 % Bewölkung etwa 0,5,
  bei 90 % praktisch nichts. So wird Plus auch im Winter eingelernt.
* **Jahreszeit:** Je Monat entsteht ein eigener Faktor. Mit wenigen Tagen wird er
  mit dem Gesamtfaktor gemischt, mit mehr Daten zählt er immer stärker.
* **Tagesprofil:** Der Tag wird von Sonnenauf- bis -untergang in 10 Abschnitte
  geteilt. Aus dem Verlauf des echten Ertrags (Recorder) lernt Plus, ob morgens
  oder abends regelmäßig weniger kommt. Die Tagessumme bleibt dabei unverändert.
  Neben dem Jahresprofil gibt es je ein Profil für **Winter** (Nov–Feb),
  **Übergang** (Mär/Apr, Sep/Okt) und **Sommer** (Mai–Aug) – Verschattung bei
  flacher Wintersonne wird so getrennt gelernt.
* **Tagesverlauf:** Alle 5 Minuten wird der Ertrag bis jetzt mit der Prognose bis
  jetzt verglichen. Die Abweichung wirkt stark auf die nächsten Stunden und
  klingt zum Abend hin ab. Morgen bleibt unberührt.
* **Ohne Rückkopplung:** Gelernt wird immer gegen die unkorrigierte Prognose.

---

## 📊 Sensoren

**Je Eintrag** – wie im Original, z. B.
`sensor.westseite_plus_energy_production_today`, `…_tomorrow`,
`…_power_production_now`.

**Anlagen-Eintrag**

| Sensor | Inhalt |
|---|---|
| `sensor.solar_forecast_plus_gesamt_heute` | Prognose heute, alle Seiten (Attribute: Anteile je Seite, Wert ohne Korrektur, Stundenwerte, Bewölkung) |
| `sensor.solar_forecast_plus_gesamt_heute_rest` | Rest von heute |
| `sensor.solar_forecast_plus_gesamt_morgen` | Prognose morgen |
| `sensor.solar_forecast_plus_gesamt_leistung` | Leistung jetzt |
| `sensor.solar_forecast_plus_pv_faktor` | Gelernter Wirkungsgrad (Attribute: Saisonfaktor, Faktor je Monat, Tagesprofil gesamt und je Jahreszeit, gelernte Dämpfung morgens/abends) |
| `sensor.solar_forecast_plus_ertrag_zu_prognose` | Ist zu Prognose des letzten Tages, Gewicht, Bewölkungsquelle, Abweichung heute, Verlauf |
| `sensor.solar_forecast_plus_klare_tage` | Anzahl klarer Tage, gewichtete Tage |
| `sensor.solar_forecast_plus_treffsicherheit` | Mittlere Abweichung der Vortagesprognose in % (30 Tage), Vergleich ohne Lernen und mit Vergleichsmodell |

## 🛠️ Dienste

| Dienst | Zweck |
|---|---|
| `solar_forecast_plus.learning_evaluate` | Tag sofort auswerten |
| `solar_forecast_plus.learning_set` | Lernstand setzen oder übernehmen (`factor`, `clear_days`, `last_clear_date`, `history`, `reset`) |
| `solar_forecast_plus.update_array_location` | Standort aktualisieren (wie im Original) |

---

## 🛡️ Verhalten bei Datenlücken

| Fehlender Wert | Verhalten in Plus |
|---|---|
| Schneehöhe | zählt als „kein Schnee“ |
| Diffus-/Direktstrahlung (Horizont, Teilverschattung) | Faktor 1,0 bzw. 0 W/m² hinter dem Horizont |
| Einstrahlung oder Temperatur | dieser 15-Minuten-Wert wird übersprungen |
| Sonnenauf-/untergang | keine Dämpfung an diesem Tag |
| Bewölkung | Tag zählt nicht fürs Lernen |
| ganze Variable fehlt | wie lauter Lücken |

Nach einer Änderung der Einstellungen bleibt außerdem die letzte Prognose als
Notreserve erhalten, falls die API genau dann ausfällt.

---

## 🧪 Tests

```bash
pip install pytest-homeassistant-custom-component suncalc pytz
pytest
```

## 🌦️ Wetterdaten

Wetterdaten von [Open-Meteo.com](https://open-meteo.com/), lizenziert unter
[CC BY 4.0](https://creativecommons.org/licenses/by/4.0/). Die kostenlose
Open-Meteo-API darf nur nicht-kommerziell genutzt werden (z. B. private
Hausautomation), siehe [Nutzungsbedingungen](https://open-meteo.com/en/terms).

## 📄 Lizenz

Apache License 2.0 (siehe `LICENSE.md`); die eingebettete Bibliothek
`forecast_lib` steht unter der MIT-Lizenz (siehe `forecast_lib/LICENSE`).
Hinweise zu Herkunft und Änderungen in `NOTICE` und `CHANGELOG.md`.
