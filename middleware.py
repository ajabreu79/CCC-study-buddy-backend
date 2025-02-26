import time
from fastapi import Request, HTTPException
import jwt
import os


async def auth_middleware(request: Request, call_next):
    start_time = time.perf_counter()

    # List of endpoints that do not require authentication
    unauthenticated_endpoints = [
        "/",
        "/dev/docs",
        "/prod/docs",
        "/dev/user/signup",
        "/prod/user/signup",
        "/dev/user/signin",
        "/prod/user/signin",
        "/dev/openapi.json",
        "/prod/openapi.json",
    ]

    # Check if the request path is in the list of unauthenticated endpoints
    if request.url.path in unauthenticated_endpoints:
        response = await call_next(request)
        process_time = time.perf_counter() - start_time
        response.headers["X-Process-Time"] = str(process_time)
        return response

    # Extract JWT token from Authorization header
    auth_header = request.headers.get("Authorization")
    if auth_header:
        token = auth_header.split(" ")[1]
        try:
            # Decode JWT token
            payload = jwt.decode(
                token, os.getenv("JWT_SECRET_KEY"), algorithms=["HS256"]
            )
            request.state.user = payload
        except jwt.ExpiredSignatureError:
            raise HTTPException(status_code=401, detail="Token has expired")
        except jwt.InvalidTokenError:
            raise HTTPException(status_code=401, detail="Invalid token")
    else:
        # Log the missing Authorization header
        print(f"Authorization header missing for request to {request.url.path}")
        raise HTTPException(status_code=401, detail="Authorization header missing")

    response = await call_next(request)
    process_time = time.perf_counter() - start_time
    response.headers["X-Process-Time"] = str(process_time)
    return response
