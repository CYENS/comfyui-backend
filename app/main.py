from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.orm import Session
from starlette.middleware.wsgi import WSGIMiddleware

from .db import Base, SessionLocal, engine
from .flask_ui import app as flask_ui_app
from .routers import assets, export, jobs, review, ui, workflows
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

app.include_router(workflows.router, prefix="/api")
app.include_router(jobs.router, prefix="/api")
app.include_router(assets.router, prefix="/api")
app.include_router(review.router, prefix="/api")
app.include_router(export.router, prefix="/api")
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

