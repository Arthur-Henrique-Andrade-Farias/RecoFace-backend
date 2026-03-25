from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form
from sqlalchemy.orm import Session, joinedload
from typing import List, Optional
import json
import os
import shutil
from database import get_db
import models
import schemas
import auth
from face_service import face_service

router = APIRouter()


def _build_person_response(p: models.Person) -> schemas.PersonResponse:
    photos_with_encoding = [ph for ph in p.photos if ph.face_encoding]
    has_encoding = len(photos_with_encoding) > 0 or p.face_encoding is not None
    return schemas.PersonResponse(
        id=p.id,
        name=p.name,
        role=p.role,
        department=p.department,
        photo_path=p.photo_path,
        is_authorized=p.is_authorized,
        registration_number=p.registration_number,
        has_face_encoding=has_encoding,
        photo_count=len(p.photos),
        created_at=p.created_at,
    )


def _reload_encodings(db: Session) -> None:
    photos = (
        db.query(models.PersonPhoto)
        .options(joinedload(models.PersonPhoto.person))
        .filter(models.PersonPhoto.face_encoding.isnot(None))
        .all()
    )
    face_service.load_encodings_from_db(photos)

    # Also load legacy encodings from persons without photos
    person_ids_with_photos = {ph.person_id for ph in photos}
    legacy = (
        db.query(models.Person)
        .filter(
            models.Person.face_encoding.isnot(None),
            ~models.Person.id.in_(person_ids_with_photos) if person_ids_with_photos else True,
        )
        .all()
    )
    for person in legacy:
        try:
            import numpy as np
            encoding = np.array(json.loads(person.face_encoding))
            face_service.known_encodings.append(encoding)
            face_service.known_ids.append(person.id)
            face_service.known_names.append(person.name)
            face_service.known_authorized.append(person.is_authorized)
        except Exception:
            pass


def _save_photo_file(name: str, photo: UploadFile, suffix: str = "") -> str:
    safe_name = name.replace(" ", "_").replace("/", "_")
    filename = f"person_{safe_name}{suffix}_{photo.filename}"
    filepath = os.path.join("uploads", "photos", filename)
    with open(filepath, "wb") as f:
        shutil.copyfileobj(photo.file, f)
    return filepath


@router.get("/", response_model=List[schemas.PersonResponse])
def list_persons(
    db: Session = Depends(get_db),
    _: models.User = Depends(auth.require_any),
):
    persons = (
        db.query(models.Person)
        .options(joinedload(models.Person.photos))
        .order_by(models.Person.name)
        .all()
    )
    return [_build_person_response(p) for p in persons]


@router.post("/", response_model=schemas.PersonResponse)
async def create_person(
    name: str = Form(...),
    role: str = Form("student"),
    department: Optional[str] = Form(None),
    is_authorized: bool = Form(True),
    registration_number: Optional[str] = Form(None),
    photo: Optional[UploadFile] = File(None),
    db: Session = Depends(get_db),
    _: models.User = Depends(auth.require_admin_or_vigia),
):
    person = models.Person(
        name=name,
        role=role,
        department=department,
        is_authorized=is_authorized,
        registration_number=registration_number,
    )

    if photo and photo.filename:
        filepath = _save_photo_file(name, photo)
        person.photo_path = filepath

        encoding = face_service.extract_encoding_from_image(filepath)
        if encoding:
            person.face_encoding = json.dumps(encoding)

        db.add(person)
        db.flush()

        # Also create a PersonPhoto entry
        person_photo = models.PersonPhoto(
            person_id=person.id,
            photo_path=filepath,
            face_encoding=json.dumps(encoding) if encoding else None,
            label="Foto principal",
        )
        db.add(person_photo)
    else:
        db.add(person)

    db.commit()
    db.refresh(person)
    _reload_encodings(db)
    return _build_person_response(person)


@router.put("/{person_id}", response_model=schemas.PersonResponse)
async def update_person(
    person_id: int,
    name: str = Form(...),
    role: str = Form("student"),
    department: Optional[str] = Form(None),
    is_authorized: bool = Form(True),
    registration_number: Optional[str] = Form(None),
    photo: Optional[UploadFile] = File(None),
    db: Session = Depends(get_db),
    _: models.User = Depends(auth.require_admin_or_vigia),
):
    person = db.query(models.Person).options(joinedload(models.Person.photos)).filter(models.Person.id == person_id).first()
    if not person:
        raise HTTPException(status_code=404, detail="Pessoa não encontrada")

    person.name = name
    person.role = role
    person.department = department
    person.is_authorized = is_authorized
    person.registration_number = registration_number

    if photo and photo.filename:
        filepath = _save_photo_file(name, photo)
        person.photo_path = filepath

        encoding = face_service.extract_encoding_from_image(filepath)
        if encoding:
            person.face_encoding = json.dumps(encoding)

        # Also create a PersonPhoto entry
        person_photo = models.PersonPhoto(
            person_id=person.id,
            photo_path=filepath,
            face_encoding=json.dumps(encoding) if encoding else None,
            label="Foto principal",
        )
        db.add(person_photo)

    db.commit()
    db.refresh(person)
    _reload_encodings(db)
    return _build_person_response(person)


@router.delete("/{person_id}")
def delete_person(
    person_id: int,
    db: Session = Depends(get_db),
    _: models.User = Depends(auth.require_admin_or_vigia),
):
    person = db.query(models.Person).filter(models.Person.id == person_id).first()
    if not person:
        raise HTTPException(status_code=404, detail="Pessoa não encontrada")
    db.delete(person)
    db.commit()
    _reload_encodings(db)
    return {"message": "Pessoa removida com sucesso"}


# ─── Multi-Photo Endpoints ───────────────────────────────────────────────────

@router.get("/{person_id}/photos", response_model=List[schemas.PersonPhotoResponse])
def list_person_photos(
    person_id: int,
    db: Session = Depends(get_db),
    _: models.User = Depends(auth.require_any),
):
    person = db.query(models.Person).filter(models.Person.id == person_id).first()
    if not person:
        raise HTTPException(status_code=404, detail="Pessoa não encontrada")

    photos = (
        db.query(models.PersonPhoto)
        .filter(models.PersonPhoto.person_id == person_id)
        .order_by(models.PersonPhoto.created_at.desc())
        .all()
    )
    return [
        schemas.PersonPhotoResponse(
            id=ph.id,
            person_id=ph.person_id,
            photo_path=ph.photo_path,
            has_face_encoding=ph.face_encoding is not None,
            label=ph.label,
            created_at=ph.created_at,
        )
        for ph in photos
    ]


@router.post("/{person_id}/photos", response_model=schemas.PersonPhotoResponse)
async def add_person_photo(
    person_id: int,
    photo: UploadFile = File(...),
    label: Optional[str] = Form(None),
    db: Session = Depends(get_db),
    _: models.User = Depends(auth.require_admin_or_vigia),
):
    person = db.query(models.Person).filter(models.Person.id == person_id).first()
    if not person:
        raise HTTPException(status_code=404, detail="Pessoa não encontrada")

    filepath = _save_photo_file(person.name, photo, suffix=f"_{person_id}_{int(datetime.now().timestamp())}")
    encoding = face_service.extract_encoding_from_image(filepath)

    person_photo = models.PersonPhoto(
        person_id=person_id,
        photo_path=filepath,
        face_encoding=json.dumps(encoding) if encoding else None,
        label=label or f"Foto {len(person.photos) + 1 if hasattr(person, 'photos') else 1}",
    )
    db.add(person_photo)

    # Update profile photo if person has none
    if not person.photo_path:
        person.photo_path = filepath
        if encoding:
            person.face_encoding = json.dumps(encoding)

    db.commit()
    db.refresh(person_photo)
    _reload_encodings(db)

    return schemas.PersonPhotoResponse(
        id=person_photo.id,
        person_id=person_photo.person_id,
        photo_path=person_photo.photo_path,
        has_face_encoding=person_photo.face_encoding is not None,
        label=person_photo.label,
        created_at=person_photo.created_at,
    )


@router.delete("/{person_id}/photos/{photo_id}")
def delete_person_photo(
    person_id: int,
    photo_id: int,
    db: Session = Depends(get_db),
    _: models.User = Depends(auth.require_admin_or_vigia),
):
    photo = (
        db.query(models.PersonPhoto)
        .filter(models.PersonPhoto.id == photo_id, models.PersonPhoto.person_id == person_id)
        .first()
    )
    if not photo:
        raise HTTPException(status_code=404, detail="Foto não encontrada")

    db.delete(photo)
    db.commit()
    _reload_encodings(db)
    return {"message": "Foto removida com sucesso"}


from datetime import datetime


@router.post("/reload-encodings")
def reload_encodings(
    db: Session = Depends(get_db),
    _: models.User = Depends(auth.require_any),
):
    _reload_encodings(db)
    return {"message": f"Encodings recarregados: {len(face_service.known_encodings)} encoding(s)"}
