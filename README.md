# METAR Reader

A Flask web application that fetches live aviation weather reports (METARs) and translates them into plain English — so anyone can understand current conditions at any airport in the world.

Type in an ICAO airport code, and get back a friendly summary like:

> *Light rain. Mostly cloudy. 52°F (11°C). Wind 18 mph from the SW, gusting to 28 mph. Visibility 4 miles.*

---

## Features

- **Live data** — pulls the latest METAR directly from [aviationweather.gov](https://aviationweather.gov)
- **Plain-English summary** — converts cryptic codes into readable sentences
- **Full weather breakdown** — wind, temperature, dew point, humidity, visibility, sky conditions, and pressure
- **Flight category badge** — colour-coded VFR / MVFR / IFR / LIFR indicator
- **Unit conversions** — knots → mph, Celsius → Fahrenheit, inHg ↔ mb
- **Raw METAR** — original string always shown for reference
- **Global coverage** — works with any ICAO station code worldwide

---

## What is a METAR?

A METAR (Meteorological Aerodrome Report) is a standardised weather observation issued by airports, typically every 30–60 minutes. They look like this:

```
METAR KHIO 140953Z AUTO 18005KT 10SM SCT070 10/08 A3020 RMK AO2 SLP225
```

This app decodes every field and presents it in a format anyone can understand — no aviation knowledge required.

---

## Getting Started

### Prerequisites

- Python 3.9+
- pip

### Installation

```bash
git clone https://github.com/cstudd/metar-reader.git
cd metar-reader
pip install -r requirements.txt
```

### Run

```bash
python app.py
```

Then open **http://127.0.0.1:5000** in your browser.

---

## Usage

1. Enter a 4-letter **ICAO airport code** in the search box (e.g. `KJFK`, `EGLL`, `EDDM`)
2. Press **Get Weather**
3. Read the decoded report

> **Tip:** ICAO codes are not the same as the 3-letter IATA codes used on boarding passes.  
> Look yours up at [ourairports.com](https://ourairports.com).

### Example codes

| Airport | Code |
|---|---|
| Portland / Hillsboro, OR | `KHIO` |
| New York JFK | `KJFK` |
| London Heathrow | `EGLL` |
| Frankfurt | `EDDF` |
| Tokyo Narita | `RJAA` |
| Sydney | `YSSY` |

---

## Testing

The test suite uses **pytest** and covers three layers:

- **Parsing logic** — `parse_metar()` tested with mock METAR strings across all weather conditions (VFR/MVFR/IFR/LIFR, gusts, CAVOK, negative temperatures, fractional visibility, CB/TCU clouds, Q-altimeter, etc.)
- **Helper functions** — `degrees_to_compass`, `knots_to_mph`, `c_to_f`, `relative_humidity`, `decode_weather`, `determine_flight_category`
- **HTTP layer** — `fetch_metar()` with mocked `requests.get` (correct URL, error propagation)
- **Flask route** — full request/response cycle via Flask test client with mocked `fetch_metar`

### Install test dependencies

```bash
pip install -r requirements-dev.txt
```

### Run tests

```bash
python -m pytest
```

```bash
python -m pytest -v   # verbose output
```

---

## Project Structure

```
metar-reader/
├── app.py                  # Flask app + METAR parser
├── requirements.txt        # Runtime dependencies
├── requirements-dev.txt    # Dev/test dependencies
├── pytest.ini              # pytest configuration
├── tests/
│   └── test_app.py         # 77 unit & integration tests
└── templates/
    └── index.html          # UI (Bootstrap 5, dark sky theme)
```

---

## Data Source

Weather data is provided by the **Aviation Weather Center** (NOAA/NWS):  
https://aviationweather.gov

---

## License

MIT — free to use, modify, and distribute.
