from fastapi import FastAPI

from app.routes import analyze, resolve

app = FastAPI(title="Merge Conflict Resolver")

app.include_router(analyze.router)
app.include_router(resolve.router)