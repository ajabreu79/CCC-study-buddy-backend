from fastapi import FastAPI, Request, HTTPException, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from dotenv import load_dotenv, dotenv_values
import os
import time

from openai import OpenAI
from anthropic import Anthropic
from src.Chat import ChatSingleCall, ChatSingleCallModel, ChatSingleCallResponse
from src.ChatStream import ChatStream, ChatStreamModel
from src.DynamicAuth import DynamicAuth
from src.TtsStream import TtsStream
from src.SttApiKey import SttApiKey, SttApiKeyResponse

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

# initialize FastAPI app and OpenAI client
app = FastAPI(docs_url=f"{DEV_PREFIX}/docs", redoc_url=f"{DEV_PREFIX}/redoc", openapi_url=f"{DEV_PREFIX}/openapi.json")
openai_client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
anthropic_client = Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))

origins = [
    "http://127.0.0.1:8001",
    "http://localhost:8000",
    "http://localhost:5173",
    "http://localhost:5172",
    "http://localhost:5174",
    "http://127.0.0.1:5173",
    "https://conver-flow-web.vercel.app",
    "https://progressive-xlab.vercel.app",
    "https://cwru-xlab-final-demo.vercel.app",
    "https://xlab-ai-demo.vercel.app",
]

regex_origins = "https://.*jerryyang666s-projects\.vercel\.app"

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_origin_regex=regex_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.post(f"{DEV_PREFIX}/chat")
@app.post(f"{PROD_PREFIX}/chat")
async def chat(chat_single_call_model: ChatSingleCallModel):
    """
    ENDPOINT: /dev/chat, /prod/chat
    :param chat_single_call_model: 
    """
    auth = DynamicAuth()
    if not auth.verify_auth_code(chat_single_call_model.dynamic_auth_code):
        return ChatSingleCallResponse(status="fail", messages=[], thread_id="")
    chat_instance = ChatSingleCall(openai_client)
    return await chat_instance.send_chat(chat_single_call_model)


@app.post(f"{DEV_PREFIX}/stream_chat")
@app.post(f"{PROD_PREFIX}/stream_chat")
async def stream_chat(chat_stream_model: ChatStreamModel):
    """
    ENDPOINT: /dev/stream_chat, /prod/stream_chat
    :param chat_stream_model:
    """
    auth = DynamicAuth()
    if not auth.verify_auth_code(chat_stream_model.dynamic_auth_code):
        return ChatSingleCallResponse(status="fail", messages=[], thread_id="")
    chat_instance = ChatStream(chat_stream_model.provider, openai_client, anthropic_client)
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


@app.get(f"{DEV_PREFIX}/get_tts_file")
@app.get(f"{PROD_PREFIX}/get_tts_file")
async def get_tts_file(tts_session_id: str, chunk_id: str, background_tasks: BackgroundTasks):
    """
    ENDPOINT: /dev/get_tts_file, /prod/get_tts_file
    serves the TTS audio file for the specified session id and chunk id.
    :param tts_session_id:
    :param chunk_id:
    :param background_tasks:
    :return:
    """
    file_location = f"{TtsStream.TTS_AUDIO_CACHE_FOLDER}/{tts_session_id}_{chunk_id}.mp3"
    if os.path.isfile(file_location):
        # Add the delete_file_after_delay function as a background task
        background_tasks.add_task(delete_file_after_delay, file_location, 60)  # 60 seconds delay
        return FileResponse(path=file_location, media_type="audio/mpeg")
    else:
        raise HTTPException(status_code=404, detail="File not found")


@app.get(f"{DEV_PREFIX}/get_temp_stt_auth_code")
@app.get(f"{PROD_PREFIX}/get_temp_stt_auth_code")
def get_temp_stt_auth_code(dynamic_auth_code: str):
    """
    ENDPOINT: /user/get_temp_stt_auth_code
    Generates a temporary STT auth code for the user.
    :return:
    """
    auth = DynamicAuth()
    if not auth.verify_auth_code(dynamic_auth_code):
        return SttApiKeyResponse(status="fail", error_message="Invalid auth code", key="")
    stt_key_instance = SttApiKey()
    api_key, _ = stt_key_instance.generate_key()
    return SttApiKeyResponse(status="success", error_message=None, key=api_key)


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
