import json
import os

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.path.join(BASE_DIR, "data")

def load_config():
    with open(os.path.join(DATA_DIR, "config.json"), "r") as f:
        return json.load(f)

def load_profiles():
    with open(os.path.join(DATA_DIR, "users.json"), "r") as f:
        return json.load(f)["profiles"]

def load_profiles_data():
    path = os.path.join(DATA_DIR, "profiles_data.json")
    if not os.path.exists(path):
        return {}
    with open(path, "r") as f:
        try:
            return json.load(f)
        except:
            return {}

def save_profiles_data(data):
    path = os.path.join(DATA_DIR, "profiles_data.json")
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