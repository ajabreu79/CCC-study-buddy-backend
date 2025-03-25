from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from dotenv import dotenv_values
import os
import time

# LLM imports
from openai import OpenAI
from anthropic import Anthropic
from src.ChatStream import ChatStream, ChatStreamModel
from src.DynamicAuth import DynamicAuth

# Middleware import
from middleware import auth_middleware

# Constants import
from src.constants import USER, MODULE, CHAT, CHAT_HISTORY

# import routes
from src.routes.user import router as user_router
from src.routes.module import router as module_router
from src.routes.chat import router as chat_router
from src.routes.ChatHistory import router as chat_history_router

DEV_PREFIX = "/dev"
PROD_PREFIX = "/prod"

try:
    config = dotenv_values(".env")
except FileNotFoundError:
    config = {}
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

regex_origins = r"https://.*jerryyang666s-projects\.vercel\.app"


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
app.include_router(user_router, prefix=f"{DEV_PREFIX}/{USER}", tags=["Development"])
app.include_router(user_router, prefix=f"{PROD_PREFIX}/{USER}", tags=["Production"])
app.include_router(module_router, prefix=f"{DEV_PREFIX}/{MODULE}", tags=["Development"])
app.include_router(module_router, prefix=f"{PROD_PREFIX}/{MODULE}", tags=["Production"])
app.include_router(chat_router, prefix=f"{DEV_PREFIX}/{CHAT}", tags=["Development"])
app.include_router(chat_router, prefix=f"{PROD_PREFIX}/{CHAT}", tags=["Production"])
app.include_router(chat_history_router, prefix=f"{DEV_PREFIX}/{CHAT_HISTORY}", tags=["Development"])
app.include_router(chat_history_router, prefix=f"{PROD_PREFIX}/{CHAT_HISTORY}", tags=["Production"])


@app.post(f"{DEV_PREFIX}/stream_chat")
@app.post(f"{PROD_PREFIX}/stream_chat")
async def stream_chat(chat_stream_model: ChatStreamModel):
    """
    ENDPOINT: /dev/stream_chat, /prod/stream_chat
    :param chat_stream_model:
    """
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
