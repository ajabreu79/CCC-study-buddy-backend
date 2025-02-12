from fastapi import FastAPI, Request, HTTPException, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from dotenv import load_dotenv, dotenv_values
import os
import time

from openai import OpenAI
from anthropic import Anthropic
from src.ChatStream import ChatStream, ChatStreamModel
from src.DynamicAuth import DynamicAuth

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
    "http://localhost:3000",
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


@app.post(f"{DEV_PREFIX}/stream_chat")
@app.post(f"{PROD_PREFIX}/stream_chat")
async def stream_chat(chat_stream_model: ChatStreamModel):
    """
    ENDPOINT: /dev/stream_chat, /prod/stream_chat
    :param chat_stream_model:
    """
    auth = DynamicAuth()
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
