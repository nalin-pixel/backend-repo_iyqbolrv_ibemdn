import os
from typing import Optional, Dict, Any, List
from datetime import datetime, timedelta

from fastapi import FastAPI, HTTPException, Query, Depends, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import OAuth2PasswordBearer
from pydantic import BaseModel
import requests
from jose import JWTError, jwt
from passlib.context import CryptContext

from database import db, create_document, get_documents

app = FastAPI(title="WrestlePro API", version="1.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

SMOOTHCOMP_API_BASE = os.getenv("SMOOTHCOMP_API_BASE", "https://smoothcomp.com/api")
SMOOTHCOMP_API_KEY = os.getenv("SMOOTHCOMP_API_KEY")

# ----------------------- Auth / JWT Config -----------------------
JWT_SECRET = os.getenv("JWT_SECRET", "dev-secret-change-me")
JWT_ALGORITHM = "HS256"
JWT_EXPIRES_MIN = int(os.getenv("JWT_EXPIRES_MIN", "1440"))  # 24h default

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/auth/login")

# Pydantic helper for health
class Health(BaseModel):
    backend: str
    database: str

@app.get("/", response_model=dict)
def root():
    return {"message": "WrestlePro backend is running"}

@app.get("/test", response_model=dict)
def test_database():
    response: Dict[str, Any] = {"backend": "✅ Running", "database": "❌ Not Available"}
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
    headers: Dict[str, str] = {}
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

# ----------------------- Schemas & Models -----------------------
from schemas import (
    Event as EventSchema,
    Registration as RegistrationSchema,
    ChatTranscript,
    AuthUser,
    SignupRequest,
    LoginRequest,
    TokenResponse,
)

# ----------------------- Auth Utilities -----------------------

def verify_password(plain_password: str, hashed_password: str) -> bool:
    return pwd_context.verify(plain_password, hashed_password)


def get_password_hash(password: str) -> str:
    return pwd_context.hash(password)


def create_access_token(data: dict, expires_minutes: int = JWT_EXPIRES_MIN) -> str:
    to_encode = data.copy()
    expire = datetime.utcnow() + timedelta(minutes=expires_minutes)
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, JWT_SECRET, algorithm=JWT_ALGORITHM)


def get_user_by_email(email: str) -> Optional[dict]:
    if db is None:
        raise HTTPException(status_code=500, detail="Database not configured")
    return db["authuser"].find_one({"email": email})


async def get_current_user(token: str = Depends(oauth2_scheme)) -> dict:
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        payload = jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
        email: str = payload.get("sub")
        if email is None:
            raise credentials_exception
    except JWTError:
        raise credentials_exception
    user = get_user_by_email(email)
    if not user:
        raise credentials_exception
    if not user.get("is_active", True):
        raise HTTPException(status_code=403, detail="User is inactive")
    user["_id"] = str(user.get("_id"))
    return user


def require_roles(*allowed_roles: str):
    async def _dep(user: dict = Depends(get_current_user)):
        role = user.get("role", "athlete")
        if role not in allowed_roles:
            raise HTTPException(status_code=403, detail="Insufficient permissions")
        return user
    return _dep

# ----------------------- Auth Routes -----------------------

@app.post("/api/auth/signup", response_model=TokenResponse)
def signup(payload: SignupRequest):
    # Check if exists
    existing = get_user_by_email(payload.email)
    if existing:
        raise HTTPException(status_code=400, detail="Email already registered")
    # Create user
    hashed = get_password_hash(payload.password)
    user_model = AuthUser(
        name=payload.name,
        email=payload.email,
        role=payload.role or "athlete",
        hashed_password=hashed,
        is_active=True,
    )
    user_id = create_document("authuser", user_model)
    token = create_access_token({"sub": payload.email, "role": user_model.role})
    user_dict = user_model.model_dump()
    user_dict.update({"_id": user_id})
    del user_dict["hashed_password"]
    return {"access_token": token, "token_type": "bearer", "user": user_dict}


@app.post("/api/auth/login", response_model=TokenResponse)
def login(payload: LoginRequest):
    user = get_user_by_email(payload.email)
    if not user:
        raise HTTPException(status_code=400, detail="Invalid email or password")
    if not verify_password(payload.password, user.get("hashed_password", "")):
        raise HTTPException(status_code=400, detail="Invalid email or password")
    token = create_access_token({"sub": user["email"], "role": user.get("role", "athlete")})
    user_slim = {k: v for k, v in user.items() if k not in ("hashed_password",)}
    user_slim["_id"] = str(user_slim.get("_id"))
    return {"access_token": token, "token_type": "bearer", "user": user_slim}


@app.get("/api/auth/me")
def me(user: dict = Depends(get_current_user)):
    return {"user": user}

# ----------------------- Local Event & Registration -----------------------

@app.get("/api/events")
def get_local_events(limit: int = 50):
    try:
        docs = get_documents("event", {}, limit)
        for d in docs:
            d["_id"] = str(d.get("_id"))
        return {"events": docs}
    except Exception as e:
        return {"events": [], "error": str(e)}


@app.post("/api/events")
def create_event(event: EventSchema, user: dict = Depends(require_roles("organizer", "admin"))):
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
