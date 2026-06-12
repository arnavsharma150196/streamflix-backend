import boto3
from botocore.config import Config
import os
import time

os.environ['AWS_REQUEST_CHECKSUM_CALCULATION'] = 'when_required'
os.environ['AWS_RESPONSE_CHECKSUM_VALIDATION'] = 'when_required'

B2_KEY_ID = "6688666e5211e3c6dd128d6c493cc960031d7c24"
B2_APP_KEY = "scqT7+yUGG9kwtCZEYW+n27r0CoVBOH28PL/0tVU5l8="
B2_BUCKET = "streamflix"
B2_ENDPOINT = "https://bmrh712l39ph.compat.objectstorage.ap-mumbai-1.oraclecloud.com"

_client = None

def get_b2_client():
    global _client
    if _client is None:
        _client = boto3.client(
            "s3",
            endpoint_url=B2_ENDPOINT,
            aws_access_key_id=B2_KEY_ID,
            aws_secret_access_key=B2_APP_KEY,
            region_name="ap-mumbai-1",
            config=Config(signature_version="s3v4")
        )
    return _client


def list_all_content():
    """
    Scan B2 bucket and return structured library.
    Folder structure:
        tv/<show_name>/s01e01/playlist.m3u8
        movies/<movie_name>/playlist.m3u8
    """
    client = get_b2_client()
    library = {"tv_shows": {}, "movies": {}}

    paginator = client.get_paginator("list_objects_v2")
    pages = paginator.paginate(Bucket=B2_BUCKET)

    for page in pages:
        for obj in page.get("Contents", []):
            key = obj["Key"]
            if not key.endswith("playlist.m3u8"):
                continue

            parts = key.split("/")

            if parts[0] == "tv" and len(parts) >= 4:
                show_key = parts[1]
                ep_key = parts[2]  # e.g. s01e01

                if show_key not in library["tv_shows"]:
                    library["tv_shows"][show_key] = {
                        "show_key": show_key,
                        "show_name": show_key.replace("_", " ").title(),
                        "episodes": []
                    }

                # Parse season/episode from folder name
                import re
                match = re.match(r"s(\d+)e(\d+)", ep_key)
                season = int(match.group(1)) if match else 1
                episode = int(match.group(2)) if match else 1

                library["tv_shows"][show_key]["episodes"].append({
                    "season": season,
                    "episode": episode,
                    "ep_key": ep_key,
                    "playlist_key": key,
                    "show_key": show_key
                })

            elif parts[0] == "movies" and len(parts) >= 3:
                movie_key = parts[1]
                library["movies"][movie_key] = {
                    "movie_key": movie_key,
                    "title": movie_key.replace("_", " ").title(),
                    "playlist_key": key
                }

    # Sort episodes
    for show in library["tv_shows"].values():
        show["episodes"].sort(key=lambda x: (x["season"], x["episode"]))

    return library


_url_cache = {}
URL_CACHE_TTL = 3600  # 1 hour

def get_presigned_url(key, expiry=21600):
    """Generate a presigned URL with caching."""
    now = time.time()
    if key in _url_cache:
        url, timestamp = _url_cache[key]
        if now - timestamp < URL_CACHE_TTL:
            return url
    
    client = get_b2_client()
    url = client.generate_presigned_url(
        "get_object",
        Params={"Bucket": B2_BUCKET, "Key": key},
        ExpiresIn=expiry
    )
    _url_cache[key] = (url, now)
    return url


def get_playlist_with_presigned_urls(playlist_key):
    import requests
    client = get_b2_client()

    # Get presigned URL for the playlist itself
    playlist_url = get_presigned_url(playlist_key)
    resp = requests.get(playlist_url)
    playlist_content = resp.text

    base_path = "/".join(playlist_key.split("/")[:-1])

    # Generate all presigned URLs in batch
    lines = []
    segments = [line.strip() for line in playlist_content.splitlines() if line.endswith(".ts")]
    
    # Pre-generate all URLs at once
    presigned_urls = {}
    for seg in segments:
        segment_key = f"{base_path}/{seg}"
        presigned_urls[seg] = get_presigned_url(segment_key, expiry=21600)

    for line in playlist_content.splitlines():
        if line.endswith(".ts"):
            lines.append(presigned_urls[line.strip()])
        else:
            lines.append(line)

    return "\n".join(lines)


def get_subtitle_url(playlist_key):
    client = get_b2_client()
    base_path = "/".join(playlist_key.split("/")[:-1])
    subtitle_key = f"{base_path}/subtitles.en.vtt"
    print(f"[Subtitle] Looking for: {subtitle_key}")  # ← add this

    try:
        client.head_object(Bucket=B2_BUCKET, Key=subtitle_key)
        url = get_presigned_url(subtitle_key, expiry=21600)
        print(f"[Subtitle] Found! URL generated.")  # ← add this
        return url
    except Exception as e:
        print(f"[Subtitle] Not found: {e}")  # ← add this
        return None