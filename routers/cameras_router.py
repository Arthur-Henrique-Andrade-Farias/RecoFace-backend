from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from typing import List
from database import get_db
import models
import schemas
import auth

router = APIRouter()


@router.get("/", response_model=List[schemas.CameraResponse])
def list_cameras(
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth.require_any),
):
    return (
        db.query(models.Camera)
        .filter(models.Camera.org_id == current_user.org_id)
        .order_by(models.Camera.created_at.desc())
        .all()
    )


@router.post("/", response_model=schemas.CameraResponse)
def create_camera(
    camera: schemas.CameraCreate,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth.require_manager),
):
    db_camera = models.Camera(org_id=current_user.org_id, **camera.dict())
    db.add(db_camera)
    db.commit()
    db.refresh(db_camera)
    return db_camera


@router.put("/{camera_id}", response_model=schemas.CameraResponse)
def update_camera(
    camera_id: int,
    camera: schemas.CameraCreate,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth.require_manager),
):
    db_camera = db.query(models.Camera).filter(
        models.Camera.id == camera_id,
        models.Camera.org_id == current_user.org_id,
    ).first()
    if not db_camera:
        raise HTTPException(status_code=404, detail="Câmera não encontrada")
    for key, value in camera.dict().items():
        setattr(db_camera, key, value)
    db.commit()
    db.refresh(db_camera)
    return db_camera


@router.delete("/{camera_id}")
def delete_camera(
    camera_id: int,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth.require_manager),
):
    db_camera = db.query(models.Camera).filter(
        models.Camera.id == camera_id,
        models.Camera.org_id == current_user.org_id,
    ).first()
    if not db_camera:
        raise HTTPException(status_code=404, detail="Câmera não encontrada")
    db.delete(db_camera)
    db.commit()
    return {"message": "Câmera removida com sucesso"}


@router.patch("/{camera_id}/toggle", response_model=schemas.CameraResponse)
def toggle_camera(
    camera_id: int,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth.require_manager),
):
    db_camera = db.query(models.Camera).filter(
        models.Camera.id == camera_id,
        models.Camera.org_id == current_user.org_id,
    ).first()
    if not db_camera:
        raise HTTPException(status_code=404, detail="Câmera não encontrada")
    db_camera.is_active = not db_camera.is_active
    db.commit()
    db.refresh(db_camera)
    return db_camera
