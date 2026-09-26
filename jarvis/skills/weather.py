"""Weather from Open-Meteo (free, no API key)."""

import json
import urllib.parse
import urllib.request

from ..brain import Response, skill

WMO_CODES = {
    0: "clear skies", 1: "mainly clear", 2: "partly cloudy", 3: "overcast",
    45: "fog", 48: "freezing fog",
    51: "light drizzle", 53: "drizzle", 55: "heavy drizzle", 56: "freezing drizzle", 57: "freezing drizzle",
    61: "light rain", 63: "rain", 65: "heavy rain", 66: "freezing rain", 67: "freezing rain",
    71: "light snow", 73: "snow", 75: "heavy snow", 77: "snow grains",
    80: "light showers", 81: "showers", 82: "violent showers",
    85: "snow showers", 86: "heavy snow showers",
    95: "a thunderstorm", 96: "a thunderstorm with hail", 99: "a thunderstorm with heavy hail",
}


def _get_json(url: str, params: dict | None = None) -> dict:
    if params:
        url = f"{url}?{urllib.parse.urlencode(params)}"
    req = urllib.request.Request(url, headers={"User-Agent": "jarvis-assistant"})
    with urllib.request.urlopen(req, timeout=10) as resp:
        return json.load(resp)


def locate(city: str | None) -> tuple[str, float, float]:
    """Resolve a city name (or, if None, this machine's IP) to (name, lat, lon)."""
    if city:
        data = _get_json("https://geocoding-api.open-meteo.com/v1/search", {"name": city, "count": 1})
        if not data.get("results"):
            raise LookupError(city)
        r = data["results"][0]
        return r["name"], r["latitude"], r["longitude"]
    data = _get_json("https://ipinfo.io/json")
    lat, lon = data["loc"].split(",")
    return data.get("city", "your area"), float(lat), float(lon)


def forecast(lat: float, lon: float, units: str) -> dict:
    params = {
        "latitude": lat,
        "longitude": lon,
        "current": "temperature_2m,apparent_temperature,weather_code,wind_speed_10m,relative_humidity_2m",
        "daily": "temperature_2m_max,temperature_2m_min,precipitation_probability_max",
        "forecast_days": 1,
        "timezone": "auto",
    }
    if units == "imperial":
        params.update(temperature_unit="fahrenheit", wind_speed_unit="mph")
    return _get_json("https://api.open-meteo.com/v1/forecast", params)


def describe(place: str, data: dict, units: str) -> str:
    cur, day = data["current"], data["daily"]
    deg = "degrees Fahrenheit" if units == "imperial" else "degrees Celsius"
    wind = "miles per hour" if units == "imperial" else "kilometres per hour"
    sky = WMO_CODES.get(cur["weather_code"], "unsettled conditions")
    text = (
        f"Currently in {place} it's {round(cur['temperature_2m'])} {deg} with {sky}, "
        f"feels like {round(cur['apparent_temperature'])}. "
        f"Today's high is {round(day['temperature_2m_max'][0])} and the low {round(day['temperature_2m_min'][0])}. "
        f"Wind at {round(cur['wind_speed_10m'])} {wind}."
    )
    rain = (day.get("precipitation_probability_max") or [None])[0]
    if rain is not None and rain >= 40:
        text += f" There's a {rain} percent chance of rain, so you may want an umbrella."
    return text


@skill(
    r"\b(weather|temperature|forecast)\b(?:.*?\b(?:in|at|for)\s+(?P<city>[a-z .'-]+?))?(?:\s+(?:today|now|right now))?$",
    r"\bis it (going to )?(rain|snow)(ing)?\b(?:.*?\b(?:in|at)\s+(?P<city>[a-z .'-]+?))?(?:\s+today)?$",
)
def weather(m, brain):
    city = (m.groupdict().get("city") or "").strip() or brain.config.city
    try:
        place, lat, lon = locate(city)
        return Response(describe(place, forecast(lat, lon, brain.config.units), brain.config.units))
    except LookupError:
        return Response(f"I couldn't find a place called {city}, {brain.title}.")
    except Exception:
        return Response(f"I'm unable to reach the weather service right now, {brain.title}.")
