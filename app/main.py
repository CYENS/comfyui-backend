import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-8s %(name)s  %(message)s",
    datefmt="%H:%M:%S",
)
from fastapi.responses import HTMLResponse, RedirectResponse
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware
from sqlalchemy.orm import Session
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.middleware.wsgi import WSGIMiddleware

from .db import Base, SessionLocal, engine
from .flask_ui import app as flask_ui_app
from .limiter import limiter
from .routers import admin, assets, auth, export, jobs, review, ui, workflows
from .seeding import seed_roles_and_system_user, seed_workflows


@asynccontextmanager
async def lifespan(app: FastAPI):
    Base.metadata.create_all(bind=engine)
    db: Session = SessionLocal()
    try:
        seed_roles_and_system_user(db)
        seed_workflows(db)
        yield
    finally:
        db.close()


app = FastAPI(
    title="ComfyUI Wrapper API",
    description="Backend gateway for ComfyUI workflows, jobs, assets, reviews, and exports.",
    version="0.2.0",
    lifespan=lifespan,
)

app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
app.add_middleware(SlowAPIMiddleware)


class HSTSMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        response = await call_next(request)
        response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
        return response


app.add_middleware(HSTSMiddleware)

app.include_router(workflows.router, prefix="/api")
app.include_router(jobs.router, prefix="/api")
app.include_router(admin.router, prefix="/api")
app.include_router(assets.router, prefix="/api")
app.include_router(review.router, prefix="/api")
app.include_router(export.router, prefix="/api")
app.include_router(auth.router, prefix="/api")
app.include_router(ui.router)
app.mount("/ui/builder", WSGIMiddleware(flask_ui_app))


@app.get("/api/health")
def health():
    return {"status": "ok"}


@app.get("/index", response_class=HTMLResponse)
def ui_root_index():
    return RedirectResponse(url="/ui")


@app.get("/", response_class=HTMLResponse)
def ui_root():
    return RedirectResponse(url="/ui")
