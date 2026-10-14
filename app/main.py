from fastapi import FastAPI

from app.auth_routes import router as auth_router

app = FastAPI(title="The Note Taker API")
app.include_router(auth_router)


@app.get("/health", tags=["health"])
def health_check() -> dict[str, str]:
    return {"status": "ok"}
