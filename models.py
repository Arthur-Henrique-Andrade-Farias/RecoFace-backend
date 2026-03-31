from sqlalchemy import Column, Integer, String, Boolean, Float, DateTime, Text, ForeignKey, UniqueConstraint
from sqlalchemy.orm import relationship
from database import Base
from tz import now_brt


class Organization(Base):
    __tablename__ = "organizations"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(255), nullable=False)
    brand_name = Column(String(100), nullable=False, default="RecoFace")
    brand_subtitle = Column(String(100), nullable=False, default="Monitorando vidas")
    brand_logo_path = Column(String(500), nullable=True)
    telegram_bot_token = Column(String(255), nullable=True)
    telegram_notify_unrecognized = Column(Boolean, default=True)
    telegram_notify_recognized = Column(Boolean, default=False)
    created_at = Column(DateTime, default=now_brt)

    users = relationship("User", back_populates="organization")


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    org_id = Column(Integer, ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False)
    name = Column(String(255), nullable=False)
    email = Column(String(255), unique=True, index=True, nullable=False)
    hashed_password = Column(String(255), nullable=False)
    role = Column(String(20), nullable=False, default="visualizador")
    is_active = Column(Boolean, default=True)
    telegram_chat_id = Column(String(50), nullable=True)
    telegram_active = Column(Boolean, default=False)
    created_at = Column(DateTime, default=now_brt)

    organization = relationship("Organization", back_populates="users")


class PersonCategory(Base):
    __tablename__ = "person_categories"
    __table_args__ = (UniqueConstraint("org_id", "key", name="uq_category_org_key"),)

    id = Column(Integer, primary_key=True, index=True)
    org_id = Column(Integer, ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False)
    key = Column(String(50), nullable=False)
    label = Column(String(100), nullable=False)
    color = Column(String(20), default="blue")
    sort_order = Column(Integer, default=0)


class PersonField(Base):
    """Configurable custom fields for persons per organization."""
    __tablename__ = "person_fields"
    __table_args__ = (UniqueConstraint("org_id", "key", name="uq_field_org_key"),)

    id = Column(Integer, primary_key=True, index=True)
    org_id = Column(Integer, ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False)
    key = Column(String(50), nullable=False)
    label = Column(String(100), nullable=False)
    required = Column(Boolean, default=False)
    sort_order = Column(Integer, default=0)


class Person(Base):
    __tablename__ = "persons"

    id = Column(Integer, primary_key=True, index=True)
    org_id = Column(Integer, ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False)
    name = Column(String(255), index=True)
    role = Column(String(50), default="student")
    department = Column(String(255), nullable=True)
    photo_path = Column(String(500), nullable=True)
    face_encoding = Column(Text, nullable=True)
    is_authorized = Column(Boolean, default=True)
    registration_number = Column(String(100), nullable=True)
    custom_data = Column(Text, nullable=True)  # JSON: {"field_key": "value", ...}
    created_at = Column(DateTime, default=now_brt)

    photos = relationship("PersonPhoto", back_populates="person", cascade="all, delete-orphan")
    logs = relationship("RecognitionLog", back_populates="person")


class PersonPhoto(Base):
    __tablename__ = "person_photos"

    id = Column(Integer, primary_key=True, index=True)
    person_id = Column(Integer, ForeignKey("persons.id", ondelete="CASCADE"), nullable=False)
    photo_path = Column(String(500), nullable=False)
    face_encoding = Column(Text, nullable=True)
    label = Column(String(100), nullable=True)
    created_at = Column(DateTime, default=now_brt)

    person = relationship("Person", back_populates="photos")


class Camera(Base):
    __tablename__ = "cameras"

    id = Column(Integer, primary_key=True, index=True)
    org_id = Column(Integer, ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False)
    name = Column(String(255))
    camera_type = Column(String(50), default="webcam")
    url = Column(String(500), nullable=True)
    description = Column(String(500), nullable=True)
    location = Column(String(255), nullable=True)
    is_active = Column(Boolean, default=False)
    created_at = Column(DateTime, default=now_brt)

    logs = relationship("RecognitionLog", back_populates="camera")


class RecognitionLog(Base):
    __tablename__ = "recognition_logs"

    id = Column(Integer, primary_key=True, index=True)
    org_id = Column(Integer, ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False)
    camera_id = Column(Integer, ForeignKey("cameras.id", ondelete="SET NULL"), nullable=True)
    person_id = Column(Integer, ForeignKey("persons.id", ondelete="SET NULL"), nullable=True)
    recognized = Column(Boolean, default=False)
    is_authorized = Column(Boolean, default=False)
    confidence = Column(Float, nullable=True)
    photo_path = Column(String(500), nullable=True)
    notes = Column(String(1000), nullable=True)
    timestamp = Column(DateTime, default=now_brt)

    camera = relationship("Camera", back_populates="logs")
    person = relationship("Person", back_populates="logs")
