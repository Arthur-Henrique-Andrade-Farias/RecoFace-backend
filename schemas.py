from pydantic import BaseModel, field_validator
from datetime import datetime
from typing import Optional, List


# ─── Auth ───────────────────────────────────────────────────────────────────

class UserLogin(BaseModel):
    email: str
    password: str


class UserCreate(BaseModel):
    """Admin creates vigia/porteiro accounts."""
    name: str
    email: str
    password: str
    role: str = "porteiro"  # vigia or porteiro only (admin via DB)

    @field_validator("role")
    @classmethod
    def role_valid(cls, v):
        if v not in ("vigia", "porteiro"):
            raise ValueError("Função deve ser 'vigia' ou 'porteiro'")
        return v

    @field_validator("password")
    @classmethod
    def password_strength(cls, v):
        if len(v) < 6:
            raise ValueError("A senha deve ter pelo menos 6 caracteres")
        return v

    @field_validator("email")
    @classmethod
    def email_valid(cls, v):
        if "@" not in v or "." not in v:
            raise ValueError("Email inválido")
        return v.lower().strip()


class UserResponse(BaseModel):
    id: int
    name: str
    email: str
    role: str
    is_active: bool
    created_at: datetime

    class Config:
        from_attributes = True


class Token(BaseModel):
    access_token: str
    token_type: str


# ─── Person Photos ───────────────────────────────────────────────────────────

class PersonPhotoResponse(BaseModel):
    id: int
    person_id: int
    photo_path: str
    has_face_encoding: bool
    label: Optional[str]
    created_at: datetime

    class Config:
        from_attributes = True


# ─── Person ──────────────────────────────────────────────────────────────────

class PersonResponse(BaseModel):
    id: int
    name: str
    role: str
    department: Optional[str]
    photo_path: Optional[str]
    is_authorized: bool
    registration_number: Optional[str]
    has_face_encoding: bool
    photo_count: int
    created_at: datetime

    class Config:
        from_attributes = True


# ─── Camera ──────────────────────────────────────────────────────────────────

class CameraCreate(BaseModel):
    name: str
    camera_type: str = "webcam"
    url: Optional[str] = None
    description: Optional[str] = None
    location: Optional[str] = None


class CameraResponse(BaseModel):
    id: int
    name: str
    camera_type: str
    url: Optional[str]
    description: Optional[str]
    location: Optional[str]
    is_active: bool
    created_at: datetime

    class Config:
        from_attributes = True


# ─── Logs ────────────────────────────────────────────────────────────────────

class LogResponse(BaseModel):
    id: int
    camera_id: Optional[int]
    camera_name: Optional[str]
    person_id: Optional[int]
    person_name: Optional[str]
    person_role: Optional[str]
    recognized: bool
    is_authorized: bool
    confidence: Optional[float]
    photo_path: Optional[str]
    notes: Optional[str]
    timestamp: datetime

    class Config:
        from_attributes = True
