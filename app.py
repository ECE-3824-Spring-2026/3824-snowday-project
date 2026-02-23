#!/usr/bin/env python3
"""
Flask web interface for the US precipitation monitor.
Run:  python app.py
Then open http://localhost:5000 in your browser.
"""

import concurrent.futures
from datetime import datetime

from flask import Flask, jsonify, render_template

from precipitation_monitor import STATE_CITIES, fetch_state_weather, format_age

app = Flask(__name__)


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/api/weather")
def weather():
    results = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=10) as pool:
        futures = {
            pool.submit(fetch_state_weather, state, city, lat, lon): state
            for state, (city, lat, lon) in STATE_CITIES.items()
        }
        for future in concurrent.futures.as_completed(futures):
            results.append(future.result())

    results.sort(key=lambda r: r["state"])

    for r in results:
        r["age"] = format_age(r["obs_time"]) if r["obs_time"] else "—"

    return jsonify({
        "results": results,
        "fetched_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "precip_count": sum(1 for r in results if r["has_precip"]),
        "error_count":  sum(1 for r in results if r["error"]),
    })


if __name__ == "__main__":
    app.run(debug=True, port=5000)
