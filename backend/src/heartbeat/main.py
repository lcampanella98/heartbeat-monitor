import os

from fastapi import FastAPI

app = FastAPI(title="Heartbeat Monitor")


@app.get("/api/v1/system/status")
async def system_status() -> dict:
    return {
        "check_source": os.environ.get("CHECK_SOURCE", "real"),
        "email_sink": os.environ.get("EMAIL_SINK", "smtp"),
        "smtp_from": os.environ.get("SMTP_FROM"),
        "n": 3,
        "m": 2,
    }
