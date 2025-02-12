import time
from fastapi import Request


async def auth_middleware(request: Request, call_next):
    start_time = time.perf_counter()
    response = await call_next(request)
    process_time = time.perf_counter() - start_time
    print(f"Processing time: {process_time}")
    response.headers["X-Process-Time"] = str(process_time)
    return response
