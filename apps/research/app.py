"""Research App — FastAPI entry point.

Usage (dev)::

    uvicorn app:app --reload --port 8000

Usage (Databricks Apps)::

    python app.py
"""

from __future__ import annotations

import os

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from applib.routes import router

app = FastAPI(title="Research App")

app.mount("/static", StaticFiles(directory="static"), name="static")
app.include_router(router)


if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("DATABRICKS_APP_PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)
