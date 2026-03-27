from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from typing import List
from database import get_db
import models
import schemas
import auth

router = APIRouter()


@router.get("/", response_model=List[schemas.PersonCategoryResponse])
def list_categories(
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth.require_any),
):
    return (
        db.query(models.PersonCategory)
        .filter(models.PersonCategory.org_id == current_user.org_id)
        .order_by(models.PersonCategory.sort_order, models.PersonCategory.label)
        .all()
    )


@router.post("/", response_model=schemas.PersonCategoryResponse)
def create_category(
    data: schemas.PersonCategoryCreate,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth.require_admin),
):
    existing = (
        db.query(models.PersonCategory)
        .filter(
            models.PersonCategory.org_id == current_user.org_id,
            models.PersonCategory.key == data.key,
        )
        .first()
    )
    if existing:
        raise HTTPException(status_code=400, detail="Categoria com esta chave já existe")

    cat = models.PersonCategory(org_id=current_user.org_id, **data.dict())
    db.add(cat)
    db.commit()
    db.refresh(cat)
    return cat


@router.put("/{category_id}", response_model=schemas.PersonCategoryResponse)
def update_category(
    category_id: int,
    data: schemas.PersonCategoryCreate,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth.require_admin),
):
    cat = db.query(models.PersonCategory).filter(
        models.PersonCategory.id == category_id,
        models.PersonCategory.org_id == current_user.org_id,
    ).first()
    if not cat:
        raise HTTPException(status_code=404, detail="Categoria não encontrada")

    dup = (
        db.query(models.PersonCategory)
        .filter(
            models.PersonCategory.org_id == current_user.org_id,
            models.PersonCategory.key == data.key,
            models.PersonCategory.id != category_id,
        )
        .first()
    )
    if dup:
        raise HTTPException(status_code=400, detail="Outra categoria já usa esta chave")

    old_key = cat.key
    for key, value in data.dict().items():
        setattr(cat, key, value)

    if old_key != data.key:
        db.query(models.Person).filter(
            models.Person.org_id == current_user.org_id,
            models.Person.role == old_key,
        ).update({"role": data.key})

    db.commit()
    db.refresh(cat)
    return cat


@router.delete("/{category_id}")
def delete_category(
    category_id: int,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth.require_admin),
):
    cat = db.query(models.PersonCategory).filter(
        models.PersonCategory.id == category_id,
        models.PersonCategory.org_id == current_user.org_id,
    ).first()
    if not cat:
        raise HTTPException(status_code=404, detail="Categoria não encontrada")

    person_count = db.query(models.Person).filter(
        models.Person.org_id == current_user.org_id,
        models.Person.role == cat.key,
    ).count()
    if person_count > 0:
        raise HTTPException(
            status_code=400,
            detail=f"Não é possível remover: {person_count} pessoa(s) usam esta categoria",
        )

    db.delete(cat)
    db.commit()
    return {"message": "Categoria removida"}
