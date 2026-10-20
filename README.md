# Solar Forecast Plus

PV-Ertragsprognose für Home Assistant auf Basis von Open-Meteo – mit
lückentoleranter Berechnung und selbstlernendem Wirkungsgrad.

## Was ist neu?

### 1. Robust bei Datenlücken
Die Original-Bibliothek bricht die komplette Prognose ab, sobald Open-Meteo in den
über 100 abgefragten Tagen einen einzigen leeren Wert liefert (z. B.
`TypeError: unsupported operand type(s) for *: 'NoneType' and 'int'` bei der
Schneehöhe). Plus überbrückt solche Lücken:

| Fehlender Wert | Verhalten in Plus |
|---|---|
| Schneehöhe | zählt als „kein Schnee“ |
| Diffus-/Direktstrahlung (Horizont, Teilverschattung) | Faktor 1,0 bzw. 0 W/m² hinter dem Horizont |
| Einstrahlung oder Temperatur | dieser 15-Minuten-Wert wird übersprungen |
| Sonnenauf-/untergang | keine Dämpfung an diesem Tag |
| ganze Variable fehlt in der Antwort | wie lauter Lücken |

Außerdem bleibt nach einer Änderung der Einstellungen die letzte Prognose als
Notreserve erhalten. Fällt die API genau dann aus, bleiben die Sensoren befüllt,
statt dass die Integration hängen bleibt. Die Anzahl überbrückter Lücken steht in
den Diagnosedaten.

### 2. Selbstlernender Wirkungsgrad
Jeden Abend (einstellbar, Standard 30 min nach Sonnenuntergang) wird der echte
PV-Tagesertrag mit der Prognose **aller** Einträge der Integration verglichen.
An klaren Tagen (Bewölkung unter der Schwelle) wird daraus der Wirkungsgrad
gelernt und geglättet (exponentieller Mittelwert).

Einrichtung: **Einstellungen → Geräte & Dienste → Open-Meteo Solar Forecast →
Konfigurieren**. Nach den Anlagen-Seiten folgt die Seite *Selbstlernender
Wirkungsgrad*. Nur in **einem** Eintrag aktivieren.

| Option | Bedeutung |
|---|---|
| Tatsächlicher PV-Tagesertrag | Energie-Sensor, der täglich auf 0 zurückgesetzt wird |
| Bewölkung im Tagesmittel | Sensor in %, z. B. aus OpenWeatherMap |
| Schwelle für klare Tage | Standard 30 % |
| Glättung | Gewicht eines neuen Tages, Standard 0,2 |
| Klare Tage bis zur Anwendung | Standard 10 |
| Automatisch anwenden | ersetzt danach den eingestellten Wirkungsgrad aller Einträge |

Neue Sensoren:

* `sensor.open_meteo_pv_faktor` – gelernter Wirkungsgrad (Attribute: klare Tage,
  eingelernt, angewendet, letzter klarer Tag, konfigurierter/aktiver Wirkungsgrad)
* `sensor.open_meteo_ertrag_zu_prognose` – Ist/Prognose des letzten Tages
  (Attribute: Datum, klar, Bewölkung, Ist- und Prognose-kWh, 14-Tage-Verlauf)
* `sensor.open_meteo_klare_tage` – Anzahl gelernter klarer Tage

Dienste:

* `open_meteo_solar_forecast.learning_evaluate` – Tag sofort auswerten
* `open_meteo_solar_forecast.learning_set` – Lernstand setzen oder übernehmen
  (`factor`, `clear_days`, `last_clear_date`, `history`, `reset`)

### 3. Eigenes Icon
Ab Home Assistant 2026.3 bringt die Integration ihr eigenes Icon mit (Ordner
`brand/`, hell und dunkel). Es ersetzt das Icon des Originals automatisch.

## Installation über HACS

1. Die originale Integration in HACS entfernen (die Einträge unter *Geräte &
   Dienste* bleiben erhalten – Plus nutzt dieselbe Domain, alle Sensoren behalten
   ihre Namen).
2. HACS → ⋮ → *Benutzerdefinierte Repositories* → `https://github.com/Dasdomi1982/ha-solar-forecast-plus` als
   *Integration* hinzufügen.
3. *Solar Forecast Plus* herunterladen und Home Assistant neu starten.

## Tests

```bash
pip install pytest-homeassistant-custom-component suncalc pytz
pytest
```

## Wetterdaten

Wetterdaten von [Open-Meteo.com](https://open-meteo.com/), lizenziert unter
[CC BY 4.0](https://creativecommons.org/licenses/by/4.0/). Die kostenlose
Open-Meteo-API darf nur nicht-kommerziell genutzt werden (z. B. private
Hausautomation), siehe [Nutzungsbedingungen](https://open-meteo.com/en/terms).

## Lizenz

Apache License 2.0 (siehe `LICENSE.md`); die eingebettete Bibliothek
`forecast_lib` steht unter der MIT-Lizenz (siehe `forecast_lib/LICENSE`).
Hinweise zu Herkunft und Änderungen in `NOTICE` und `CHANGELOG.md`.
