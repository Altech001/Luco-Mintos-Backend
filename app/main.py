import asyncio
import sentry_sdk
from fastapi import FastAPI
from fastapi.routing import APIRoute
from sqlmodel import Session
from starlette.middleware.cors import CORSMiddleware
import httpx

from app.api.main import api_router
from app.core.config import settings
from app.core.db import engine, init_db


def custom_generate_unique_id(route: APIRoute) -> str:
    tag = route.tags[0] if getattr(route, "tags", None) else "default"
    name = route.name or "route"
    return f"{tag}-{name}"


if settings.SENTRY_DSN and settings.ENVIRONMENT != "local":
    sentry_sdk.init(dsn=str(settings.SENTRY_DSN), enable_tracing=True)


app = FastAPI(
    title=settings.PROJECT_NAME,
    # openapi_url=f"{settings.API_V1_STR}/openapi.json",
    generate_unique_id_function=custom_generate_unique_id,
    license_info={
        "name": "MIT License",
        "url": "https://opensource.org/license/mit/",
    },
    openapi_url="/openapi.json",  # ✅ Explicitly set it
    docs_url="/docs",  
)

if settings.all_cors_origins:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.all_cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

app.include_router(api_router, prefix=settings.API_V1_STR)


@app.get("/health", tags=["system"])
def health() -> dict:
    return {"status": "ok"}


@app.on_event("startup")
async def on_startup() -> None:
    # Ensure DB is initialized
    with Session(engine) as session:
        init_db(session)

    # Start keepalive pinger if enabled
    if settings.ENABLE_KEEPALIVE and settings.PING_URL:
        async def _keepalive_loop() -> None:
            async with httpx.AsyncClient(timeout=10) as client:
                while True:
                    try:
                        await client.get(str(settings.PING_URL))
                    except Exception:
                        # Intentionally swallow errors to keep the loop alive
                        pass
                    await asyncio.sleep(int(settings.PING_INTERVAL_SECONDS))

        app.state.keepalive_task = asyncio.create_task(_keepalive_loop())


@app.on_event("shutdown")
async def on_shutdown() -> None:
    # Stop keepalive task if running
    task = getattr(app.state, "keepalive_task", None)
    if task:
        task.cancel()
        try:
            await task
        except Exception:
            pass



