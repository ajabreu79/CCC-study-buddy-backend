from fastapi import FastAPI, Request, HTTPException, BackgroundTasks, Body
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from dotenv import load_dotenv, dotenv_values
import os
import time
import uuid
import json

# Firebase imports
import firebase_admin
from firebase_admin import credentials, firestore

# JWT imports
import bcrypt
import jwt
import datetime
from pydantic import BaseModel, EmailStr, Field, field_validator
import re

# LLM imports
from openai import OpenAI
from anthropic import Anthropic
from src.ChatStream import ChatStream, ChatStreamModel
from src.DynamicAuth import DynamicAuth

# Middleware import
from middleware import auth_middleware

# import routes
from src.UserRoutes import router as user_router

DEV_PREFIX = "/dev"
PROD_PREFIX = "/prod"

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
    "measurementId": os.getenv("NEXT_PUBLIC_FIREBASE_MEASUREMENT_ID")
}

# Load Firebase service account key from environment variable
firebase_service_account_key_path = os.getenv("FIREBASE_SERVICE_ACCOUNT_KEY_PATH")
if not firebase_service_account_key_path:
    raise ValueError("FIREBASE_SERVICE_ACCOUNT_KEY_PATH environment variable is not set")

with open(firebase_service_account_key_path) as f:
    firebase_config = json.load(f)

cred = credentials.Certificate(firebase_config)
firebase_admin.initialize_app(cred)
db = firestore.client()

# initialize FastAPI app and OpenAI client
app = FastAPI(
    docs_url=f"{DEV_PREFIX}/docs",
    redoc_url=f"{DEV_PREFIX}/redoc",
    openapi_url=f"{DEV_PREFIX}/openapi.json",
)
openai_client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
anthropic_client = Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))

origins = [
    "http://127.0.0.1:8001",
    "http://localhost:8000",
    "http://localhost:5173",
    "http://localhost:5172",
    "http://localhost:5174",
    "http://localhost:3000",
    "http://127.0.0.1:5173",
    "https://eaton1.xlab-cwru.com",
    "https://xlab-ai-demo.vercel.app",
]

regex_origins = "https://.*jerryyang666s-projects\.vercel\.app"

@app.middleware("http")
async def add_process_time_header(request: Request, call_next):
    response = await auth_middleware(request, call_next)
    return response

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_origin_regex=regex_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Routes
app.include_router(user_router, prefix=f"{DEV_PREFIX}/user", tags=["Development"])
app.include_router(user_router, prefix=f"{PROD_PREFIX}/user", tags=["Production"])

@app.post(f"{DEV_PREFIX}/stream_chat")
@app.post(f"{PROD_PREFIX}/stream_chat")
async def stream_chat(chat_stream_model: ChatStreamModel):
    """
    ENDPOINT: /dev/stream_chat, /prod/stream_chat
    :param chat_stream_model:
    """
    auth = DynamicAuth()
    chat_instance = ChatStream(
        chat_stream_model.provider, openai_client, anthropic_client
    )
    return chat_instance.stream_chat(chat_stream_model)


def delete_file_after_delay(file_path: str, delay: float):
    """
    Deletes the specified file after a delay.
    :param file_path: The path to the file to delete.
    :param delay: The delay before deletion, in seconds.
    """
    time.sleep(delay)
    if os.path.isfile(file_path):
        os.remove(file_path)


@app.get("/dev/")
@app.get("/prod/")
@app.get("/")
def read_root(request: Request):
    """
    ENDPOINT: /dev/, /prod/, /
    :param request:
    :return:
    """
    abc = config.get("ABC") or os.getenv("ABC")  # local is prioritized
    if abc is None:
        return {"Hello": "World", "request": str(request.url.path)}
    else:
        return {"Servers": "Hello-World-" + abc, "request": str(request.url.path)}

class UserSignUpModel(BaseModel):
    email: EmailStr
    password: str = Field(..., min_length=8, max_length=64)
    first_name: str = Field(..., min_length=1, max_length=50, pattern=r'^[A-Za-z-]+$')
    last_name: str = Field(..., min_length=1, max_length=50, pattern=r'^[A-Za-z-]+$')

    @field_validator('password')
    def validate_password(cls, v):
        if not re.search(r'[A-Z]', v):
            raise ValueError('Password must contain at least one uppercase letter')
        if not re.search(r'[a-z]', v):
            raise ValueError('Password must contain at least one lowercase letter')
        if not re.search(r'[0-9]', v):
            raise ValueError('Password must contain at least one digit')
        if not re.search(r'[!@#$%^&*(),.?":{}|<>]', v):
            raise ValueError('Password must contain at least one special character')
        return v

@app.post(f"{DEV_PREFIX}/signup")
@app.post(f"{PROD_PREFIX}/signup")
def sign_up(payload: UserSignUpModel = Body(...)):
    allowed_user_ref = db.collection('allowed_users').document(payload.email).get()
    if not allowed_user_ref.exists:
        raise HTTPException(status_code=403, detail="User not allowed to sign up")

    hashed_pw = bcrypt.hashpw(payload.password.encode("utf-8"), bcrypt.gensalt())
    user_id = str(uuid.uuid4())

    user_data = {
        "user_id": user_id,
        "first_name": payload.first_name,
        "last_name": payload.last_name,
        "email": payload.email,
        "hashed_pw": hashed_pw.decode("utf-8"),
        "access_level": allowed_user_ref.to_dict().get("access_level"),
        "workspace_id": 0,
        "isDeleted": None
    }
    db.collection('users').document(payload.email).set(user_data)

    token = jwt.encode(
        {
            "user_id": user_data["user_id"],
            "access_level": user_data["access_level"],
            "exp": datetime.datetime.utcnow() + datetime.timedelta(days=1)
        },
        os.getenv("JWT_SECRET_KEY"),
        algorithm="HS256"
    )
    return {"message": "Sign-up successful", "token": token}

class UserSignInModel(BaseModel):
    email: EmailStr
    password: str = Field(..., min_length=8, max_length=64)

@app.post(f"{DEV_PREFIX}/signin")
@app.post(f"{PROD_PREFIX}/signin")
def sign_in(payload: UserSignInModel = Body(...)):
    user_ref = db.collection('users').where('email', '==', payload.email).limit(1).get()
    if not user_ref:
        raise HTTPException(status_code=401, detail="Invalid credentials")

    user = user_ref[0].to_dict()
    if not bcrypt.checkpw(payload.password.encode("utf-8"), user["hashed_pw"].encode("utf-8")):
        raise HTTPException(status_code=401, detail="Invalid credentials")

    token = jwt.encode(
        {
            "user_id": user["user_id"],
            "access_level": user["access_level"],
            "exp": datetime.datetime.utcnow() + datetime.timedelta(days=1)
        },
        os.getenv("JWT_SECRET_KEY"),
        algorithm="HS256"
    )
    return {"message": "Sign-in successful", "token": token}

def create_admin_account():
    admin_email = os.getenv("ADMIN_EMAIL")
    admin_password = os.getenv("ADMIN_PASSWORD")
    admin_first_name = os.getenv("ADMIN_FIRST_NAME")
    admin_last_name = os.getenv("ADMIN_LAST_NAME")
    admin_access_level = 9

    if not admin_email or not admin_password or not admin_first_name or not admin_last_name:
        print("Admin credentials are not set in the environment variables.")
        return

    # Check if the admin account already exists
    admin_ref = db.collection('users').where('email', '==', admin_email).limit(1).get()
    if not admin_ref:
        # Hash the admin password
        hashed_pw = bcrypt.hashpw(admin_password.encode("utf-8"), bcrypt.gensalt())

        # Create the admin account
        admin_data = {
            "user_id": str(uuid.uuid4()),
            "first_name": admin_first_name,
            "last_name": admin_last_name,
            "email": admin_email,
            "hashed_pw": hashed_pw.decode("utf-8"),
            "access_level": admin_access_level,
            "workspace_id": 0,
            "isDeleted": None
        }
        db.collection('users').document(admin_data["user_id"]).set(admin_data)
        print("Admin account created.")
    else:
        print("Admin account already exists.")

# Create admin account if it doesn't exist
create_admin_account()