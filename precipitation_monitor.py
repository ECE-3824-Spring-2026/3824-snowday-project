#!/usr/bin/env python3
"""
Real-time US precipitation monitor using the National Weather Service (NWS) API.
No API key required. Data source: https://api.weather.gov
"""

import concurrent.futures
from datetime import datetime, timezone

import requests
from rich import box
from rich.console import Console
from rich.progress import Progress, SpinnerColumn, TextColumn
from rich.table import Table

BASE_URL = "https://api.weather.gov"
HEADERS = {
    "User-Agent": "(US Precipitation Monitor, for educational use)",
    "Accept": "application/geo+json",
}

# One representative city per state (lat, lon)
STATE_CITIES: dict[str, tuple[str, float, float]] = {
    "Alabama":        ("Birmingham",     33.5186,  -86.8104),
    "Alaska":         ("Anchorage",      61.2181, -149.9003),
    "Arizona":        ("Phoenix",        33.4484, -112.0740),
    "Arkansas":       ("Little Rock",    34.7465,  -92.2896),
    "California":     ("Los Angeles",    34.0522, -118.2437),
    "Colorado":       ("Denver",         39.7392, -104.9903),
    "Connecticut":    ("Hartford",       41.7658,  -72.6851),
    "Delaware":       ("Wilmington",     39.7447,  -75.5484),
    "Florida":        ("Miami",          25.7617,  -80.1918),
    "Georgia":        ("Atlanta",        33.7490,  -84.3880),
    "Hawaii":         ("Honolulu",       21.3069, -157.8583),
    "Idaho":          ("Boise",          43.6150, -116.2023),
    "Illinois":       ("Chicago",        41.8781,  -87.6298),
    "Indiana":        ("Indianapolis",   39.7684,  -86.1581),
    "Iowa":           ("Des Moines",     41.5868,  -93.6250),
    "Kansas":         ("Wichita",        37.6872,  -97.3301),
    "Kentucky":       ("Louisville",     38.2527,  -85.7585),
    "Louisiana":      ("New Orleans",    29.9511,  -90.0715),
    "Maine":          ("Portland",       43.6591,  -70.2568),
    "Maryland":       ("Baltimore",      39.2904,  -76.6122),
    "Massachusetts":  ("Boston",         42.3601,  -71.0589),
    "Michigan":       ("Detroit",        42.3314,  -83.0458),
    "Minnesota":      ("Minneapolis",    44.9778,  -93.2650),
    "Mississippi":    ("Jackson",        32.2988,  -90.1848),
    "Missouri":       ("Kansas City",    39.0997,  -94.5786),
    "Montana":        ("Billings",       45.7833, -108.5007),
    "Nebraska":       ("Omaha",          41.2565,  -95.9345),
    "Nevada":         ("Las Vegas",      36.1699, -115.1398),
    "New Hampshire":  ("Concord",        43.2081,  -71.5376),
    "New Jersey":     ("Newark",         40.7357,  -74.1724),
    "New Mexico":     ("Albuquerque",    35.0844, -106.6504),
    "New York":       ("New York City",  40.7128,  -74.0060),
    "North Carolina": ("Charlotte",      35.2271,  -80.8431),
    "North Dakota":   ("Bismarck",       46.8083, -100.7837),
    "Ohio":           ("Columbus",       39.9612,  -82.9988),
    "Oklahoma":       ("Oklahoma City",  35.4676,  -97.5164),
    "Oregon":         ("Portland",       45.5051, -122.6750),
    "Pennsylvania":   ("Philadelphia",   39.9526,  -75.1652),
    "Rhode Island":   ("Providence",     41.8240,  -71.4128),
    "South Carolina": ("Columbia",       34.0007,  -81.0348),
    "South Dakota":   ("Sioux Falls",    43.5446,  -96.7311),
    "Tennessee":      ("Nashville",      36.1627,  -86.7816),
    "Texas":          ("Houston",        29.7604,  -95.3698),
    "Utah":           ("Salt Lake City", 40.7608, -111.8910),
    "Vermont":        ("Burlington",     44.4759,  -73.2121),
    "Virginia":       ("Richmond",       37.5407,  -77.4360),
    "Washington":     ("Seattle",        47.6062, -122.3321),
    "West Virginia":  ("Charleston",     38.3498,  -81.6326),
    "Wisconsin":      ("Milwaukee",      43.0389,  -87.9065),
    "Wyoming":        ("Cheyenne",       41.1400, -104.8202),
}

# NWS present-weather phenomenon codes that indicate precipitation
# https://www.weather.gov/media/wrh/mesowest/metar_decode_key.pdf
PRECIP_PHENOMENA = {"DZ", "RA", "SN", "SG", "IC", "PL", "GR", "GS", "UP"}

# Fallback: keywords in the plain-text description
PRECIP_KEYWORDS = [
    "rain", "snow", "drizzle", "hail", "sleet",
    "shower", "precipitation", "ice pellet",
    "thunderstorm", "wintry mix", "freezing",
]


def _get(url: str, timeout: int = 12) -> dict:
    """GET with up to 3 retries on transient NWS server errors."""
    import time
    last_exc: Exception = RuntimeError("No attempts made")
    for attempt in range(3):
        try:
            r = requests.get(url, headers=HEADERS, timeout=timeout)
            if r.status_code in (500, 503) and attempt < 2:
                time.sleep(1.5 * (attempt + 1))
                continue
            r.raise_for_status()
            return r.json()
        except Exception as exc:
            last_exc = exc
            if attempt < 2:
                time.sleep(1)
    raise last_exc


def fetch_state_weather(state: str, city: str, lat: float, lon: float) -> dict:
    """
    Return a dict describing current conditions for one state.
    Three NWS API calls:
      1. /points/{lat},{lon}           → resolves nearest forecast office + stations URL
      2. {observationStations URL}     → lists nearby ASOS/AWOS stations (take first)
      3. /stations/{id}/observations/latest → current ob
    """
    result: dict = {
        "state": state,
        "city": city,
        "station": "—",
        "condition": "Error",
        "temp_f": None,
        "has_precip": False,
        "obs_time": None,
        "error": None,
    }
    try:
        # Step 1: grid point metadata
        point_data = _get(f"{BASE_URL}/points/{lat:.4f},{lon:.4f}")
        stations_url: str = point_data["properties"]["observationStations"]

        # Step 2: nearest observation station
        stations_data = _get(stations_url)
        features = stations_data.get("features") or []
        if not features:
            result["condition"] = "No stations found"
            return result

        station_id: str = features[0]["properties"]["stationIdentifier"]
        result["station"] = station_id

        # Step 3: latest observation
        obs_data = _get(f"{BASE_URL}/stations/{station_id}/observations/latest")
        props: dict = obs_data["properties"]

        # Temperature (Celsius → Fahrenheit)
        temp_c = (props.get("temperature") or {}).get("value")
        if temp_c is not None:
            result["temp_f"] = round(temp_c * 9 / 5 + 32)

        result["obs_time"] = props.get("timestamp")

        # Detect precipitation via structured codes first, then text fallback
        text_desc: str = props.get("textDescription") or ""
        present_weather: list = props.get("presentWeather") or []

        has_precip = any(
            (w.get("weather") or "").upper() in PRECIP_PHENOMENA
            for w in present_weather
        )
        if not has_precip:
            has_precip = any(kw in text_desc.lower() for kw in PRECIP_KEYWORDS)

        result["has_precip"] = has_precip
        result["condition"] = text_desc if text_desc else (
            "Precipitation" if has_precip else "Clear"
        )

    except Exception as exc:
        result["error"] = str(exc)
        result["condition"] = str(exc)[:60]

    return result


def format_age(iso_timestamp: str) -> str:
    """Human-readable staleness of an observation timestamp."""
    try:
        obs = datetime.fromisoformat(iso_timestamp.replace("Z", "+00:00"))
        minutes = int((datetime.now(timezone.utc) - obs).total_seconds() / 60)
        if minutes < 60:
            return f"{minutes}m ago"
        return f"{minutes // 60}h {minutes % 60}m ago"
    except Exception:
        return "?"


def main() -> None:
    console = Console()
    console.print()
    console.print(
        "[bold blue]US Real-Time Precipitation Monitor[/bold blue]  "
        f"[dim]{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}[/dim]"
    )
    console.print(
        "[dim]Source: National Weather Service (weather.gov) — no API key required[/dim]\n"
    )

    results: list[dict] = []

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        transient=True,
        console=console,
    ) as progress:
        task_id = progress.add_task(
            "[cyan]Querying NWS for all 50 states...", total=50
        )
        with concurrent.futures.ThreadPoolExecutor(max_workers=10) as pool:
            futures = {
                pool.submit(fetch_state_weather, state, city, lat, lon): state
                for state, (city, lat, lon) in STATE_CITIES.items()
            }
            for future in concurrent.futures.as_completed(futures):
                results.append(future.result())
                progress.advance(task_id)

    results.sort(key=lambda r: r["state"])

    table = Table(
        title="[bold]Current Conditions — One Location Per State[/bold]",
        title_justify="left",
        box=box.ROUNDED,
        show_header=True,
        header_style="bold cyan",
    )
    table.add_column("State",     width=18, style="bold white")
    table.add_column("City",      width=16)
    table.add_column("Station",   width=8)
    table.add_column("Condition", width=30)
    table.add_column("Temp",      width=6,  justify="right")
    table.add_column("Observed",  width=11, justify="right", style="dim")

    precip_count = 0
    error_count = 0

    for r in results:
        temp_str = f"{r['temp_f']}°F" if r["temp_f"] is not None else "—"
        age_str  = format_age(r["obs_time"]) if r["obs_time"] else "—"

        if r["error"]:
            error_count += 1
            cond_markup = f"[red dim]{r['condition']}[/red dim]"
        elif r["has_precip"]:
            precip_count += 1
            cond_markup = f"[bold yellow]{r['condition']}[/bold yellow]"
        else:
            cond_markup = f"[dim]{r['condition']}[/dim]"

        table.add_row(
            r["state"],
            r["city"],
            r["station"],
            cond_markup,
            temp_str,
            age_str,
        )

    console.print(table)
    console.print()
    console.print(
        f"  [bold yellow]{precip_count}[/bold yellow] states with precipitation  |  "
        f"[bold white]{50 - precip_count - error_count}[/bold white] states clear  |  "
        f"[red]{error_count}[/red] errors"
    )
    console.print()


if __name__ == "__main__":
    main()
