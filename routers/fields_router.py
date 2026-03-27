from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from typing import List
from database import get_db
import models
import schemas
import auth

router = APIRouter()


@router.get("/", response_model=List[schemas.PersonFieldResponse])
def list_fields(
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth.require_any),
):
    return (
        db.query(models.PersonField)
        .filter(models.PersonField.org_id == current_user.org_id)
        .order_by(models.PersonField.sort_order, models.PersonField.label)
        .all()
    )


@router.post("/", response_model=schemas.PersonFieldResponse)
def create_field(
    data: schemas.PersonFieldCreate,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth.require_admin),
):
    existing = (
        db.query(models.PersonField)
        .filter(
            models.PersonField.org_id == current_user.org_id,
            models.PersonField.key == data.key,
        )
        .first()
    )
    if existing:
        raise HTTPException(status_code=400, detail="Campo com esta chave já existe")

    field = models.PersonField(org_id=current_user.org_id, **data.dict())
    db.add(field)
    db.commit()
    db.refresh(field)
    return field


@router.put("/{field_id}", response_model=schemas.PersonFieldResponse)
def update_field(
    field_id: int,
    data: schemas.PersonFieldCreate,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth.require_admin),
):
    field = db.query(models.PersonField).filter(
        models.PersonField.id == field_id,
        models.PersonField.org_id == current_user.org_id,
    ).first()
    if not field:
        raise HTTPException(status_code=404, detail="Campo não encontrado")

    for key, value in data.dict().items():
        setattr(field, key, value)
    db.commit()
    db.refresh(field)
    return field


@router.delete("/{field_id}")
def delete_field(
    field_id: int,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth.require_admin),
):
    field = db.query(models.PersonField).filter(
        models.PersonField.id == field_id,
        models.PersonField.org_id == current_user.org_id,
    ).first()
    if not field:
        raise HTTPException(status_code=404, detail="Campo não encontrado")
    db.delete(field)
    db.commit()
    return {"message": "Campo removido"}
