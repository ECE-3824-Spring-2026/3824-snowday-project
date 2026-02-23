# US Real-Time Precipitation Monitor

Displays current weather conditions for one city in each of the 50 US states, highlighting any location that is actively experiencing rain, snow, or other precipitation. Data is fetched live from the National Weather Service API — no API key required.

---

## Setup

```bash
python3 -m venv .venv
source .venv/bin/activate      # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

## Running

```bash
python precipitation_monitor.py
```

The script fetches all 50 states in parallel and prints a table like:

```
Current Conditions — One Location Per State
╭───────────────┬─────────────┬─────────┬───────────────────────────┬──────┬────────────╮
│ State         │ City        │ Station │ Condition                 │ Temp │ Observed   │
├───────────────┼─────────────┼─────────┼───────────────────────────┼──────┼────────────┤
│ Indiana       │ Indianapolis│ KIND    │ Light Snow                │ 28°F │ 12m ago    │
│ Oregon        │ Portland    │ KPDX    │ Rain and Fog/Mist         │ 46°F │ 12m ago    │
│ ...           │ ...         │ ...     │ ...                       │ ...  │ ...        │
╰───────────────┴─────────────┴─────────┴───────────────────────────┴──────┴────────────╯
  9 states with precipitation  |  41 states clear  |  0 errors
```

- **Precipitation** is highlighted in bold yellow
- **Clear** conditions are shown dimmed
- **Errors** (API timeouts, missing data) are shown in red
- The **Observed** column shows how old the reading is — NWS stations report every 20–60 minutes

---

## NWS API

The script uses the free [National Weather Service API](https://www.weather.gov/documentation/services-web-api) (`https://api.weather.gov`). No registration or API key is needed. The API returns GeoJSON and requires a descriptive `User-Agent` header per its terms of service.

### Endpoints Used

Each state requires three sequential API calls:

#### 1. Resolve a lat/lon to a forecast grid point

```
GET https://api.weather.gov/points/{latitude},{longitude}
```

**Example:** `GET https://api.weather.gov/points/39.9612,-82.9988`

**Response (abbreviated):**
```json
{
  "properties": {
    "gridId": "ILN",
    "gridX": 68,
    "gridY": 74,
    "observationStations": "https://api.weather.gov/gridpoints/ILN/68,74/stations",
    "relativeLocation": {
      "properties": {
        "city": "Columbus",
        "state": "OH"
      }
    }
  }
}
```

The key field is `observationStations` — a URL to the list of nearby ASOS/AWOS weather stations.

---

#### 2. Get nearby observation stations

```
GET {observationStations URL}
```

**Example:** `GET https://api.weather.gov/gridpoints/ILN/68,74/stations`

**Response (abbreviated):**
```json
{
  "features": [
    {
      "properties": {
        "stationIdentifier": "KCMH",
        "name": "Columbus, Port Columbus International Airport"
      }
    },
    ...
  ]
}
```

Stations are ordered by proximity. The script takes `features[0]` — the nearest station. Station identifiers follow the ICAO format (e.g., `KCMH` for Columbus, `KBOS` for Boston).

---

#### 3. Fetch the latest observation

```
GET https://api.weather.gov/stations/{stationId}/observations/latest
```

**Example:** `GET https://api.weather.gov/stations/KCMH/observations/latest`

**Response (abbreviated):**
```json
{
  "properties": {
    "timestamp": "2026-02-23T18:53:00+00:00",
    "textDescription": "Light Snow and Fog/Mist",
    "temperature": {
      "value": -2.2,
      "unitCode": "wmoUnit:degC"
    },
    "presentWeather": [
      {
        "intensity": "light",
        "weather": "snow_grains",
        "rawString": "-SG"
      }
    ]
  }
}
```

Key fields:

| Field | Description |
|---|---|
| `textDescription` | Human-readable summary (e.g., `"Light Snow and Fog/Mist"`) |
| `temperature.value` | Temperature in Celsius |
| `timestamp` | ISO 8601 observation time |
| `presentWeather` | Array of structured weather phenomena (see below) |

---

### Precipitation Detection

Precipitation is detected in two ways, in order of preference:

**1. `presentWeather` phenomenon codes** — structured METAR-style codes in the observation:

| Code | Meaning |
|---|---|
| `RA` | Rain |
| `SN` | Snow |
| `DZ` | Drizzle |
| `PL` | Ice Pellets / Sleet |
| `GR` | Hail |
| `GS` | Small Hail / Snow Pellets |
| `SG` | Snow Grains |
| `IC` | Ice Crystals |
| `UP` | Unknown Precipitation |

**2. `textDescription` keyword matching** — fallback for stations that omit `presentWeather`. The script scans for words like `rain`, `snow`, `drizzle`, `sleet`, `hail`, `shower`, `thunderstorm`, `freezing`, `wintry mix`.

### Rate Limits & Reliability

The NWS API has no enforced rate limit but requests that clients use a descriptive `User-Agent` header. The script uses up to 10 parallel threads and retries up to 3 times on `500`/`503` responses. Stale or missing observations are surfaced in the **Observed** column rather than silently dropped.
