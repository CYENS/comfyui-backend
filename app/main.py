import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-8s %(name)s  %(message)s",
    datefmt="%H:%M:%S",
)
from fastapi.responses import HTMLResponse, RedirectResponse  # noqa: E402
from slowapi import _rate_limit_exceeded_handler  # noqa: E402
from slowapi.errors import RateLimitExceeded  # noqa: E402
from slowapi.middleware import SlowAPIMiddleware  # noqa: E402
from sqlalchemy.orm import Session  # noqa: E402
from starlette.middleware.base import BaseHTTPMiddleware  # noqa: E402
from starlette.middleware.wsgi import WSGIMiddleware  # noqa: E402

from .db import Base, SessionLocal, engine  # noqa: E402
from .flask_ui import app as flask_ui_app  # noqa: E402
from .limiter import limiter  # noqa: E402
from .routers import admin, assets, auth, export, jobs, public, review, ui, workflows  # noqa: E402
from .seeding import seed_roles_and_system_user, seed_workflows  # noqa: E402


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
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)  # type: ignore[arg-type]
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
app.include_router(public.router, prefix="/api")
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
