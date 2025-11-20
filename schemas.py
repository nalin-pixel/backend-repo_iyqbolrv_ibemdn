"""
Database Schemas

Pydantic models that represent MongoDB collections. Each class name becomes
a collection name in lowercase.
"""

from pydantic import BaseModel, Field, EmailStr
from typing import Optional, List
from datetime import datetime

class Organizer(BaseModel):
    name: str = Field(..., description="Organization or club name")
    contact_email: Optional[EmailStr] = Field(None, description="Primary contact email")

class Event(BaseModel):
    external_id: Optional[str] = Field(None, description="ID from Smoothcomp if available")
    title: str
    slug: Optional[str] = None
    description: Optional[str] = None
    start_date: Optional[datetime] = None
    end_date: Optional[datetime] = None
    location: Optional[str] = None
    rule_set: Optional[str] = Field(None, description="Ruleset or style (e.g., Freestyle, Greco)")
    organizer: Optional[Organizer] = None
    published: bool = True

class Participant(BaseModel):
    first_name: str
    last_name: str
    email: EmailStr
    birth_year: Optional[int] = Field(None, ge=1900, le=2100)
    weight_class: Optional[str] = None
    club: Optional[str] = None
    country: Optional[str] = None

class Registration(BaseModel):
    event_id: str = Field(..., description="Local Event document id (or slug)")
    participant: Participant
    division: Optional[str] = None
    belt: Optional[str] = None
    status: str = Field("pending", description="pending | confirmed | rejected")
    external_ref: Optional[str] = Field(None, description="External Smoothcomp registration id if synced")

class ChatTranscript(BaseModel):
    user_message: str
    response: str
    context: Optional[dict] = None

# Auth schemas
class AuthUser(BaseModel):
    name: Optional[str] = None
    email: EmailStr
    role: str = Field("athlete", description="organizer | coach | athlete | admin")
    hashed_password: str
    is_active: bool = True

class SignupRequest(BaseModel):
    name: Optional[str] = None
    email: EmailStr
    password: str
    role: Optional[str] = Field("athlete")

class LoginRequest(BaseModel):
    email: EmailStr
    password: str

class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: dict

# Example from template retained for compatibility
class User(BaseModel):
    name: str
    email: str
    address: str
    age: Optional[int] = None
    is_active: bool = True

class Product(BaseModel):
    title: str
    description: Optional[str] = None
    price: float
    category: str
    in_stock: bool = True
