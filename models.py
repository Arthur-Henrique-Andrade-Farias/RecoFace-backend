from sqlalchemy import Column, Integer, String, Boolean, Float, DateTime, Text, ForeignKey
from sqlalchemy.orm import relationship
from database import Base
from datetime import datetime


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(255), nullable=False)
    email = Column(String(255), unique=True, index=True, nullable=False)
    hashed_password = Column(String(255), nullable=False)
    role = Column(String(20), nullable=False, default="porteiro")  # admin, vigia, porteiro
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)


class Person(Base):
    __tablename__ = "persons"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(255), index=True)
    role = Column(String(50), default="student")
    department = Column(String(255), nullable=True)
    photo_path = Column(String(500), nullable=True)
    face_encoding = Column(Text, nullable=True)
    is_authorized = Column(Boolean, default=True)
    registration_number = Column(String(100), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    photos = relationship("PersonPhoto", back_populates="person", cascade="all, delete-orphan")
    logs = relationship("RecognitionLog", back_populates="person")


class PersonPhoto(Base):
    __tablename__ = "person_photos"

    id = Column(Integer, primary_key=True, index=True)
    person_id = Column(Integer, ForeignKey("persons.id", ondelete="CASCADE"), nullable=False)
    photo_path = Column(String(500), nullable=False)
    face_encoding = Column(Text, nullable=True)
    label = Column(String(100), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    person = relationship("Person", back_populates="photos")


class Camera(Base):
    __tablename__ = "cameras"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(255))
    camera_type = Column(String(50), default="webcam")
    url = Column(String(500), nullable=True)
    description = Column(String(500), nullable=True)
    location = Column(String(255), nullable=True)
    is_active = Column(Boolean, default=False)
    created_at = Column(DateTime, default=datetime.utcnow)

    logs = relationship("RecognitionLog", back_populates="camera")


class RecognitionLog(Base):
    __tablename__ = "recognition_logs"

    id = Column(Integer, primary_key=True, index=True)
    camera_id = Column(Integer, ForeignKey("cameras.id", ondelete="SET NULL"), nullable=True)
    person_id = Column(Integer, ForeignKey("persons.id", ondelete="SET NULL"), nullable=True)
    recognized = Column(Boolean, default=False)
    is_authorized = Column(Boolean, default=False)
    confidence = Column(Float, nullable=True)
    photo_path = Column(String(500), nullable=True)
    notes = Column(String(1000), nullable=True)
    timestamp = Column(DateTime, default=datetime.utcnow)

    camera = relationship("Camera", back_populates="logs")
    person = relationship("Person", back_populates="logs")
