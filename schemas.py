from pydantic import BaseModel, field_validator
from datetime import datetime
from typing import Optional, List


# ─── Auth ───────────────────────────────────────────────────────────────────

class UserLogin(BaseModel):
    email: str
    password: str


class UserCreate(BaseModel):
    name: str
    email: str
    password: str
    role: str = "visualizador"

    @field_validator("role")
    @classmethod
    def role_valid(cls, v):
        if v not in ("gerente", "configurador", "visualizador"):
            raise ValueError("Função deve ser 'gerente', 'configurador' ou 'visualizador'")
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
    org_name: Optional[str] = None
    created_at: datetime

    class Config:
        from_attributes = True


class Token(BaseModel):
    access_token: str
    token_type: str


# ─── Person Categories ──────────────────────────────────────────────────────

class PersonCategoryCreate(BaseModel):
    key: str
    label: str
    color: str = "blue"
    sort_order: int = 0


class PersonCategoryResponse(BaseModel):
    id: int
    key: str
    label: str
    color: str
    sort_order: int

    class Config:
        from_attributes = True


# ─── Person Fields ───────────────────────────────────────────────────────────

class PersonFieldCreate(BaseModel):
    key: str
    label: str
    required: bool = False
    sort_order: int = 0


class PersonFieldResponse(BaseModel):
    id: int
    key: str
    label: str
    required: bool
    sort_order: int

    class Config:
        from_attributes = True


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
    photo_path: Optional[str]
    is_authorized: bool
    has_face_encoding: bool
    photo_count: int
    custom_data: dict = {}
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


class LogUpdate(BaseModel):
    person_id: Optional[int] = None
    notes: Optional[str] = None
