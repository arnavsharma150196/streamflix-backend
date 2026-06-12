import hashlib
import time
import json
import os
from jose import jwt

SECRET_KEY = "streamflix-secret-change-this-in-production"
ALGORITHM = "HS256"
TOKEN_EXPIRY = 30 * 24 * 60 * 60  # 30 days

def hash_password(password):
    return hashlib.sha256(password.encode()).hexdigest()

def verify_password(entered, config):
    stored = config["app_password"]
    return entered == stored or hash_password(entered) == stored

def create_token():
    payload = {
        "authenticated": True,
        "exp": int(time.time()) + TOKEN_EXPIRY
    }
    return jwt.encode(payload, SECRET_KEY, algorithm=ALGORITHM)

def verify_token(token):
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        return payload.get("authenticated", False)
    except:
        return False