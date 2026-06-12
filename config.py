import json
import os

# On Render, files are at root. Locally, they're in data/
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.path.join(BASE_DIR, "data")

def _find_file(filename):
    """Look for file in data/ first, then root directory."""
    local_path = os.path.join(DATA_DIR, filename)
    if os.path.exists(local_path):
        return local_path
    root_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), filename)
    return root_path

def load_config():
    # Password comes from environment variable on Render
    password = os.environ.get("APP_PASSWORD")
    if password:
        return {"app_password": password}
    # Fallback to config.json locally
    with open(_find_file("config.json"), "r") as f:
        return json.load(f)

def load_profiles():
    with open(_find_file("users.json"), "r") as f:
        return json.load(f)["profiles"]

def load_profiles_data():
    path = _find_file("profiles_data.json")
    if not os.path.exists(path):
        return {}
    with open(path, "r") as f:
        try:
            return json.load(f)
        except:
            return {}

def save_profiles_data(data):
    path = _find_file("profiles_data.json")
    with open(path, "w") as f:
        json.dump(data, f, indent=4)

def ensure_profile_exists(profile_id):
    data = load_profiles_data()
    if profile_id not in data:
        data[profile_id] = {
            "favorites": [],
            "continue_watching": {}
        }
        save_profiles_data(data)