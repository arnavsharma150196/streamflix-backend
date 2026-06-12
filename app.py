from flask import Flask, jsonify, request, Response
from flask_cors import CORS
import time

from config import (
    load_config, load_profiles, load_profiles_data,
    save_profiles_data, ensure_profile_exists
)
from b2_service import list_all_content, get_playlist_with_presigned_urls, get_presigned_url
from tmdb_service import enrich_tv_show, enrich_movie
from auth import verify_password, create_token, verify_token

app = Flask(__name__)

CORS(app,
    supports_credentials=True,
    origins=[
        "http://localhost:3000",
        "http://192.168.1.11:3000",
        "https://streamflix-backend-49iu.onrender.com",
        "https://streamflix-bq82.onrender.com"
    ],
    allow_headers=["Authorization", "Content-Type"],
    methods=["GET", "POST", "OPTIONS"]
)

# ── Simple in-memory cache ────────────────────────────────────────────────────
_library_cache = {"data": None, "timestamp": 0}
CACHE_TTL = 300  # 5 minutes
_playlist_cache = {}
PLAYLIST_CACHE_TTL = 3600  # 1 hour


def require_auth(f):
    from functools import wraps
    @wraps(f)
    def decorated(*args, **kwargs):
        token = request.cookies.get("sf_token") or \
                request.args.get("token") or \
                request.headers.get("Authorization", "").replace("Bearer ", "")
        if not verify_token(token):
            return jsonify({"error": "Unauthorized"}), 401
        return f(*args, **kwargs)
    return decorated


def get_cached_playlist(playlist_key):
    now = time.time()
    if playlist_key in _playlist_cache:
        data, timestamp = _playlist_cache[playlist_key]
        if now - timestamp < PLAYLIST_CACHE_TTL:
            return data
    playlist = get_playlist_with_presigned_urls(playlist_key)
    _playlist_cache[playlist_key] = (playlist, now)
    return playlist


def get_library():
    now = time.time()
    if _library_cache["data"] and now - _library_cache["timestamp"] < CACHE_TTL:
        return _library_cache["data"]

    raw = list_all_content()
    library = {"tv_shows": [], "movies": []}

    for show_key, show in raw["tv_shows"].items():
        try:
            meta = enrich_tv_show(show_key)
        except Exception as e:
            print(f"TMDB error for {show_key}: {e}")
            meta = {
                "show_name": show_key.replace("_", " ").title(),
                "poster": None, "backdrop": None,
                "overview": "No description available.",
                "rating": None, "genres": []
            }
        library["tv_shows"].append({
            **meta,
            "show_key": show_key,
            "episodes": show["episodes"]
        })

    for movie_key, movie in raw["movies"].items():
        try:
            meta = enrich_movie(movie_key)
        except Exception as e:
            print(f"TMDB error for {movie_key}: {e}")
            meta = {
                "title": movie_key.replace("_", " ").title(),
                "year": None, "poster": None, "backdrop": None,
                "overview": "No description available.",
                "rating": None, "genres": [], "cast": []
            }
        library["movies"].append({
            **meta,
            "movie_key": movie_key,
            "playlist_key": movie["playlist_key"]
        })

    _library_cache["data"] = library
    _library_cache["timestamp"] = now
    return library


# ── Auth Routes ───────────────────────────────────────────────────────────────

@app.route("/api/auth/login", methods=["POST"])
def login():
    data = request.json
    password = data.get("password", "")
    config = load_config()

    if verify_password(password, config):
        token = create_token()
        resp = jsonify({"success": True, "token": token})
        resp.set_cookie(
            "sf_token", token,
            max_age=30 * 24 * 60 * 60,
            httponly=False,  # Allow JS to read it
            samesite="Lax"
        )
        return resp

    return jsonify({"error": "Invalid password"}), 401


@app.route("/api/auth/logout", methods=["POST"])
def logout():
    resp = jsonify({"success": True})
    resp.delete_cookie("sf_token")
    return resp


@app.route("/api/auth/verify", methods=["GET"])
def verify():
    token = request.cookies.get("sf_token")
    return jsonify({"authenticated": verify_token(token)})


# ── Profile Routes ────────────────────────────────────────────────────────────

@app.route("/api/profiles", methods=["GET"])
@require_auth
def get_profiles():
    return jsonify(load_profiles())


# ── Library Routes ────────────────────────────────────────────────────────────

@app.route("/api/library", methods=["GET"])
@require_auth
def get_library_route():
    return jsonify(get_library())


@app.route("/api/library/refresh", methods=["POST"])
@require_auth
def refresh_library():
    _library_cache["data"] = None
    _library_cache["timestamp"] = 0
    return jsonify(get_library())


# ── Streaming Routes ──────────────────────────────────────────────────────────

@app.route("/api/stream/tv/<show_key>/<ep_key>")
def stream_tv(show_key, ep_key):
    # Accept token from cookie OR query param (needed for HLS.js segment requests)
    token = request.cookies.get("sf_token") or request.args.get("token") or \
            request.headers.get("Authorization", "").replace("Bearer ", "")
    if not verify_token(token):
        return jsonify({"error": "Unauthorized"}), 401

    playlist_key = f"tv/{show_key}/{ep_key}/playlist.m3u8"
    try:
        playlist = get_cached_playlist(playlist_key)
        return Response(
            playlist,
            mimetype="application/x-mpegURL",
            headers={
                "Cache-Control": "no-cache"
            }
        )
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/stream/movie/<movie_key>")
def stream_movie(movie_key):
    token = request.cookies.get("sf_token") or request.args.get("token") or \
            request.headers.get("Authorization", "").replace("Bearer ", "")
    if not verify_token(token):
        return jsonify({"error": "Unauthorized"}), 401

    playlist_key = f"movies/{movie_key}/playlist.m3u8"
    try:
        playlist = get_cached_playlist(playlist_key)
        return Response(
            playlist,
            mimetype="application/x-mpegURL",
            headers={
                "Cache-Control": "no-cache"
            }
        )
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ── Favorites Routes ──────────────────────────────────────────────────────────

@app.route("/api/favorites/<profile_id>", methods=["GET"])
@require_auth
def get_favorites(profile_id):
    ensure_profile_exists(profile_id)
    data = load_profiles_data()
    return jsonify(data[profile_id].get("favorites", []))


@app.route("/api/favorites/<profile_id>", methods=["POST"])
@require_auth
def toggle_favorite(profile_id):
    ensure_profile_exists(profile_id)
    body = request.json
    item_key = body.get("item_key")
    data = load_profiles_data()
    favs = data[profile_id].get("favorites", [])

    if item_key in favs:
        favs.remove(item_key)
        action = "removed"
    else:
        favs.append(item_key)
        action = "added"

    data[profile_id]["favorites"] = favs
    save_profiles_data(data)
    return jsonify({"action": action, "favorites": favs})


# ── Watch Progress Routes ─────────────────────────────────────────────────────

@app.route("/api/progress/<profile_id>", methods=["GET"])
@require_auth
def get_progress(profile_id):
    ensure_profile_exists(profile_id)
    data = load_profiles_data()
    return jsonify(data[profile_id].get("continue_watching", {}))


@app.route("/api/progress/<profile_id>", methods=["POST"])
@require_auth
def save_progress(profile_id):
    ensure_profile_exists(profile_id)
    body = request.json
    item_key = body.get("item_key")
    seconds = body.get("seconds", 0)
    data = load_profiles_data()
    data[profile_id]["continue_watching"][item_key] = seconds
    save_profiles_data(data)
    return jsonify({"success": True})


# ── Add Subtiles Route ─────────────────────────────────────────────────────

def proxy_subtitle(playlist_key, specific_file=False):
    import requests as req
    from b2_service import get_subtitle_url, get_presigned_url
    if specific_file:
        url = get_presigned_url(playlist_key, expiry=21600)
    else:
        url = get_subtitle_url(playlist_key)
        
    if not url:
        return Response("", status=404)
    try:
        resp = req.get(url, timeout=10)
        response = Response(resp.content, mimetype="text/vtt")
        response.headers["Cache-Control"] = "public, max-age=3600"
        return response
    except Exception as e:
        print(f"Subtitle proxy error: {e}")
        return Response("", status=500)


def list_subtitle_tracks(prefix):
    """List all subtitle files for an episode."""
    from b2_service import get_b2_client, B2_BUCKET
    client = get_b2_client()
    try:
        response = client.list_objects_v2(
            Bucket=B2_BUCKET,
            Prefix=prefix
        )
        subtitles = []
        for obj in response.get("Contents", []):
            key = obj["Key"]
            filename = key.split("/")[-1]
            if filename.startswith("subtitles.") and filename.endswith(".vtt"):
                # Extract language from filename e.g. subtitles.eng.vtt → eng
                parts = filename.replace("subtitles.", "").replace(".vtt", "")
                # Try to make a clean label
                if parts.isdigit():
                    label = f"Subtitle {parts}"
                elif len(parts) <= 4:
                    label = parts.upper()
                else:
                    label = parts.replace("_", " ").title()
                subtitles.append({
                    "key": key,
                    "filename": filename,
                    "language": parts,
                    "label": label
                })
        return jsonify(subtitles)
    except Exception as e:
        return jsonify([])


@app.route("/api/subtitles/tv/<show_key>/<ep_key>")
def get_tv_subtitles(show_key, ep_key):
    token = request.cookies.get("sf_token") or request.args.get("token") or \
            request.headers.get("Authorization", "").replace("Bearer ", "")
    if not verify_token(token):
        return jsonify({"error": "Unauthorized"}), 401
    
    # Allow specific subtitle file to be requested
    subtitle_file = request.args.get("file")
    if subtitle_file:
        playlist_key = f"tv/{show_key}/{ep_key}/{subtitle_file}"
    else:
        playlist_key = f"tv/{show_key}/{ep_key}/playlist.m3u8"
    return proxy_subtitle(playlist_key, specific_file=bool(subtitle_file))


@app.route("/api/subtitles/movie/<movie_key>")
def get_movie_subtitles(movie_key):
    token = request.cookies.get("sf_token") or request.args.get("token") or \
            request.headers.get("Authorization", "").replace("Bearer ", "")
    if not verify_token(token):
        return jsonify({"error": "Unauthorized"}), 401

    subtitle_file = request.args.get("file")
    if subtitle_file:
        playlist_key = f"movies/{movie_key}/{subtitle_file}"
    else:
        playlist_key = f"movies/{movie_key}/playlist.m3u8"
    return proxy_subtitle(playlist_key, specific_file=bool(subtitle_file))


@app.route("/api/subtitles/tv/<show_key>/<ep_key>/list")
def list_tv_subtitles(show_key, ep_key):
    token = request.cookies.get("sf_token") or request.args.get("token") or \
            request.headers.get("Authorization", "").replace("Bearer ", "")
    if not verify_token(token):
        return jsonify({"error": "Unauthorized"}), 401
    
    prefix = f"tv/{show_key}/{ep_key}/"
    return list_subtitle_tracks(prefix)


@app.route("/api/subtitles/movie/<movie_key>/list")
def list_movie_subtitles(movie_key):
    token = request.cookies.get("sf_token") or request.args.get("token") or \
            request.headers.get("Authorization", "").replace("Bearer ", "")
    if not verify_token(token):
        return jsonify({"error": "Unauthorized"}), 401
    
    prefix = f"movies/{movie_key}/"
    return list_subtitle_tracks(prefix)


# ── Health check ──────────────────────────────────────────────────────────────

@app.route("/api/ping")
def ping():
    return jsonify({"status": "awake"})
    
@app.route("/api/health")
def health():
    return jsonify({"status": "ok"})


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)