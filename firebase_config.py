from dotenv import load_dotenv, dotenv_values
import os
import json

# Firebase imports
import firebase_admin
from firebase_admin import credentials, firestore

# try loading from .env file (only when running locally)
try:
    config = dotenv_values(".env")
except FileNotFoundError:
    config = {}
# load secrets from /run/secrets/ (only when running in docker)
load_dotenv(dotenv_path="/run/secrets/xlab_secret")
load_dotenv()

# Initialize Firebase using environment variables
firebase_config = {
    "apiKey": os.getenv("NEXT_PUBLIC_FIREBASE_API_KEY"),
    "authDomain": os.getenv("NEXT_PUBLIC_FIREBASE_AUTH_DOMAIN"),
    "projectId": os.getenv("NEXT_PUBLIC_FIREBASE_PROJECT_ID"),
    "storageBucket": os.getenv("NEXT_PUBLIC_FIREBASE_STORAGE_BUCKET"),
    "messagingSenderId": os.getenv("NEXT_PUBLIC_FIREBASE_MESSAGING_SENDER_ID"),
    "appId": os.getenv("NEXT_PUBLIC_FIREBASE_APP_ID"),
    "measurementId": os.getenv("NEXT_PUBLIC_FIREBASE_MEASUREMENT_ID"),
}

# Load Firebase service account key from environment variable
firebase_service_account_key_path = os.getenv("FIREBASE_SERVICE_ACCOUNT_KEY_PATH")
if not firebase_service_account_key_path:
    raise ValueError(
        "FIREBASE_SERVICE_ACCOUNT_KEY_PATH environment variable is not set"
    )

with open(firebase_service_account_key_path) as f:
    firebase_config = json.load(f)

cred = credentials.Certificate(firebase_config)
firebase_admin.initialize_app(cred)
db = firestore.client()
