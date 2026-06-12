import requests
import re
import ssl
import urllib3
import certifi
import json 
import os
os.environ['REQUESTS_CA_BUNDLE'] = certifi.where()
os.environ['SSL_CERT_FILE'] = certifi.where()

urllib3.disable_warnings()

TMDB_API_KEY = "d95f580ae5da8ccdd02cdde126703f9d"
TMDB_BASE_URL = "https://api.themoviedb.org/3"
TMDB_IMAGE_BASE = "https://image.tmdb.org/t/p/w500"
TMDB_BACKDROP_BASE = "https://image.tmdb.org/t/p/w1280"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Accept": "application/json"
}

_session = None
CACHE_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".tmdb_cache.json")

def _load_cache():
    try:
        if os.path.exists(CACHE_FILE):
            with open(CACHE_FILE, "r") as f:
                return json.load(f)
    except:
        pass
    return {}

def _save_cache():
    try:
        with open(CACHE_FILE, "w") as f:
            json.dump(_cache, f)
    except:
        pass

_cache = _load_cache()

def get_session():
    global _session
    if _session is None:
        import ssl
        from requests.adapters import HTTPAdapter
        from urllib3.util.retry import Retry
        from urllib3.util.ssl_ import create_urllib3_context

        class TLSAdapter(HTTPAdapter):
            def init_poolmanager(self, *args, **kwargs):
                ctx = create_urllib3_context()
                ctx.set_ciphers("DEFAULT@SECLEVEL=1")
                ctx.minimum_version = ssl.TLSVersion.TLSv1_2
                kwargs["ssl_context"] = ctx
                super().init_poolmanager(*args, **kwargs)

        retry = Retry(total=3, backoff_factor=2, status_forcelist=[429, 500, 502, 503, 504])
        adapter = TLSAdapter(max_retries=retry)

        _session = requests.Session()
        _session.headers.update(HEADERS)
        _session.verify = certifi.where()
        _session.mount("http://", adapter)
        _session.mount("https://", adapter)
    return _session


def tmdb_get(url, params):
    for attempt in range(3):  # retry up to 3 times
        try:
            resp = get_session().get(url, params=params, timeout=15)
            if resp.status_code == 200:
                return resp.json()
            elif resp.status_code == 429:  # rate limited
                import time
                time.sleep(2 ** attempt)  # exponential backoff
            else:
                print(f"TMDB status {resp.status_code} for {url}")
        except Exception as e:
            print(f"TMDB error (attempt {attempt+1}): {e}")
            if attempt < 2:
                import time
                time.sleep(1)
    return {}


def search_tv_show(title):
    key = f"tv_{title}"
    if key in _cache:
        return _cache[key]
    data = tmdb_get(f"{TMDB_BASE_URL}/search/tv", {"api_key": TMDB_API_KEY, "query": title})
    results = data.get("results", [])
    result = results[0] if results else None
    _cache[key] = result
    _save_cache()
    return result


def search_movie(title, year=None):
    key = f"movie_{title}_{year}"
    if key in _cache:
        return _cache[key]
    params = {"api_key": TMDB_API_KEY, "query": title}
    if year:
        params["year"] = year
    data = tmdb_get(f"{TMDB_BASE_URL}/search/movie", params)
    results = data.get("results", [])
    result = results[0] if results else None
    _cache[key] = result
    _save_cache()
    return result


def get_tv_details(tmdb_id):
    key = f"tv_details_{tmdb_id}"
    if key in _cache:
        return _cache[key]
    data = tmdb_get(f"{TMDB_BASE_URL}/tv/{tmdb_id}", {"api_key": TMDB_API_KEY})
    _cache[key] = data
    _save_cache()
    return data


def get_movie_details(tmdb_id):
    key = f"movie_details_{tmdb_id}"
    if key in _cache:
        return _cache[key]
    data = tmdb_get(
        f"{TMDB_BASE_URL}/movie/{tmdb_id}",
        {"api_key": TMDB_API_KEY, "append_to_response": "credits"}
    )
    _cache[key] = data
    _save_cache()
    return data


def enrich_tv_show(show_key):
    title = show_key.replace("_", " ").title()
    result = search_tv_show(title)
    if not result:
        return {
            "show_name": title,
            "poster": None,
            "backdrop": None,
            "overview": "No description available.",
            "rating": None,
            "genres": []
        }
    details = get_tv_details(result["id"])
    return {
        "show_name": details.get("name", title),
        "poster": TMDB_IMAGE_BASE + details["poster_path"] if details.get("poster_path") else None,
        "backdrop": TMDB_BACKDROP_BASE + details["backdrop_path"] if details.get("backdrop_path") else None,
        "overview": details.get("overview", ""),
        "rating": round(details.get("vote_average", 0), 1),
        "genres": [g["name"] for g in details.get("genres", [])],
        "tmdb_id": details.get("id")
    }


def enrich_movie(movie_key):
    parts = movie_key.rsplit("_", 1)
    year = parts[1] if len(parts) == 2 and parts[1].isdigit() else None
    title = parts[0].replace("_", " ").title()

    result = search_movie(title, year)
    if not result:
        return {
            "title": title,
            "year": year,
            "poster": None,
            "backdrop": None,
            "overview": "No description available.",
            "rating": None,
            "genres": [],
            "cast": []
        }
    details = get_movie_details(result["id"])
    cast = [c["name"] for c in details.get("credits", {}).get("cast", [])[:5]]
    return {
        "title": details.get("title", title),
        "year": details.get("release_date", "")[:4],
        "poster": TMDB_IMAGE_BASE + details["poster_path"] if details.get("poster_path") else None,
        "backdrop": TMDB_BACKDROP_BASE + details["backdrop_path"] if details.get("backdrop_path") else None,
        "overview": details.get("overview", ""),
        "rating": round(details.get("vote_average", 0), 1),
        "genres": [g["name"] for g in details.get("genres", [])],
        "cast": cast,
        "runtime": details.get("runtime"),
        "tmdb_id": details.get("id")
    }