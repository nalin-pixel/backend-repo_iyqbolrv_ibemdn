import os
from typing import List, Optional

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import requests

from database import db, create_document, get_documents

app = FastAPI(title="WrestlePro API", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

SMOOTHCOMP_API_BASE = os.getenv("SMOOTHCOMP_API_BASE", "https://smoothcomp.com/api")
SMOOTHCOMP_API_KEY = os.getenv("SMOOTHCOMP_API_KEY")

class Health(BaseModel):
    backend: str
    database: str

@app.get("/", response_model=dict)
def root():
    return {"message": "WrestlePro backend is running"}

@app.get("/test", response_model=dict)
def test_database():
    response = {"backend": "✅ Running", "database": "❌ Not Available"}
    try:
        if db is not None:
            names = db.list_collection_names()
            response["database"] = "✅ Connected"
            response["collections"] = names[:10]
        else:
            response["database"] = "❌ Not Configured"
    except Exception as e:
        response["database"] = f"⚠️ {str(e)[:120]}"
    return response

# ----------------------- Smoothcomp Integration -----------------------

def smoothcomp_get(path: str, params: Optional[dict] = None):
    url = f"{SMOOTHCOMP_API_BASE.rstrip('/')}/{path.lstrip('/')}"
    headers = {}
    if SMOOTHCOMP_API_KEY:
        headers["Authorization"] = f"Bearer {SMOOTHCOMP_API_KEY}"
    r = requests.get(url, params=params or {}, headers=headers, timeout=15)
    if r.status_code >= 400:
        raise HTTPException(status_code=r.status_code, detail=r.text)
    return r.json()

@app.get("/api/smoothcomp/events")
def list_smoothcomp_events(q: Optional[str] = Query(None, description="Search query")):
    params = {"q": q} if q else None
    try:
        data = smoothcomp_get("events", params)
    except HTTPException as e:
        # Graceful fallback when API key missing or external error
        if e.status_code in (401, 403):
            return {"events": [], "note": "Add SMOOTHCOMP_API_KEY to enable live sync."}
        raise
    return {"events": data}

@app.get("/api/smoothcomp/event/{event_id}")
def get_smoothcomp_event(event_id: str):
    try:
        data = smoothcomp_get(f"events/{event_id}")
    except HTTPException as e:
        if e.status_code in (401, 403):
            return {"event": None, "note": "Add SMOOTHCOMP_API_KEY to enable live sync."}
        raise
    return {"event": data}

# ----------------------- Local Models -----------------------
from schemas import Event as EventSchema, Registration as RegistrationSchema, ChatTranscript
from bson import ObjectId

@app.get("/api/events")
def get_local_events(limit: int = 50):
    try:
        docs = get_documents("event", {}, limit)
        # Convert ObjectId
        for d in docs:
            d["_id"] = str(d.get("_id"))
        return {"events": docs}
    except Exception as e:
        return {"events": [], "error": str(e)}

@app.post("/api/events")
def create_event(event: EventSchema):
    try:
        new_id = create_document("event", event)
        return {"id": new_id}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/registrations")
def create_registration(reg: RegistrationSchema):
    try:
        new_id = create_document("registration", reg)
        return {"id": new_id}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# ----------------------- Simple AI Chatbot (rules + retrieval) -----------------------
# For demo we implement a lightweight rules-based responder server-side.
# Frontend can call this endpoint; later we can swap to an LLM provider.

FAQ = [
    ("how do i register", "To register, pick an event, choose your division, and complete the form. You'll receive a confirmation email."),
    ("refund", "Refunds follow organizer policy. Contact support with your registration ID."),
    ("weight", "Weight classes are listed on the event page under Divisions. Bring ID for weigh-ins."),
]

@app.post("/api/chat")
def chat(query: dict):
    user_msg = (query.get("message") or "").lower()
    answer = None
    for key, val in FAQ:
        if key in user_msg:
            answer = val
            break
    if not answer:
        if "register" in user_msg:
            answer = "Use the Register button on the event card. The wizard will guide you."
        elif "event" in user_msg:
            answer = "You can browse upcoming events on the home page or search by city and date."
        else:
            answer = "I'm here to help with registrations, schedules, divisions, and weigh-ins. How can I assist?"
    try:
        create_document("chattranscript", {"user_message": query.get("message"), "response": answer})
    except Exception:
        pass
    return {"response": answer}

if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)
