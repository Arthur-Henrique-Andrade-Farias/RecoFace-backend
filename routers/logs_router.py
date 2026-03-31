from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from typing import List, Optional
from database import get_db
import models
import schemas
import auth

router = APIRouter()


def _build_log_response(log: models.RecognitionLog) -> schemas.LogResponse:
    return schemas.LogResponse(
        id=log.id,
        camera_id=log.camera_id,
        camera_name=log.camera.name if log.camera else None,
        person_id=log.person_id,
        person_name=log.person.name if log.person else None,
        person_role=log.person.role if log.person else None,
        recognized=log.recognized,
        is_authorized=log.is_authorized,
        confidence=log.confidence,
        photo_path=log.photo_path,
        notes=log.notes,
        timestamp=log.timestamp,
    )


@router.get("/", response_model=List[schemas.LogResponse])
def get_logs(
    skip: int = Query(0, ge=0),
    limit: int = Query(100, le=500),
    camera_id: Optional[int] = None,
    recognized: Optional[bool] = None,
    authorized: Optional[bool] = None,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth.require_any),
):
    query = db.query(models.RecognitionLog).filter(
        models.RecognitionLog.org_id == current_user.org_id,
    )
    if camera_id is not None:
        query = query.filter(models.RecognitionLog.camera_id == camera_id)
    if recognized is not None:
        query = query.filter(models.RecognitionLog.recognized == recognized)
    if authorized is not None:
        query = query.filter(models.RecognitionLog.is_authorized == authorized)

    logs = (
        query.order_by(models.RecognitionLog.timestamp.desc())
        .offset(skip)
        .limit(limit)
        .all()
    )
    return [_build_log_response(log) for log in logs]


# NOTE: /stats and /clear MUST be defined BEFORE /{log_id} to avoid path conflicts

@router.get("/stats")
def get_stats(
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth.require_any),
):
    oid = current_user.org_id
    base = db.query(models.RecognitionLog).filter(models.RecognitionLog.org_id == oid)
    total = base.count()
    recognized = base.filter(models.RecognitionLog.recognized == True).count()
    authorized = base.filter(models.RecognitionLog.is_authorized == True).count()
    alerts = base.filter(models.RecognitionLog.recognized == False).count()
    persons = db.query(models.Person).filter(models.Person.org_id == oid).count()
    cameras = db.query(models.Camera).filter(models.Camera.org_id == oid).count()
    active_cameras = db.query(models.Camera).filter(models.Camera.org_id == oid, models.Camera.is_active == True).count()

    return {
        "total_detections": total,
        "recognized": recognized,
        "authorized": authorized,
        "alerts": alerts,
        "total_persons": persons,
        "total_cameras": cameras,
        "active_cameras": active_cameras,
    }


@router.delete("/clear")
def clear_logs(
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth.require_any),
):
    if current_user.role not in ("admin", "gerente"):
        raise HTTPException(status_code=403, detail="Apenas administradores podem limpar os logs")
    db.query(models.RecognitionLog).filter(
        models.RecognitionLog.org_id == current_user.org_id,
    ).delete()
    db.commit()
    return {"message": "Logs removidos com sucesso"}


# Dynamic path parameter - must come AFTER fixed paths like /stats and /clear
@router.patch("/{log_id}", response_model=schemas.LogResponse)
def update_log(
    log_id: int,
    data: schemas.LogUpdate,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth.require_admin_or_configurador),
):
    log = db.query(models.RecognitionLog).filter(
        models.RecognitionLog.id == log_id,
        models.RecognitionLog.org_id == current_user.org_id,
    ).first()
    if not log:
        raise HTTPException(status_code=404, detail="Log não encontrado")

    if data.person_id is not None:
        person = db.query(models.Person).filter(
            models.Person.id == data.person_id,
            models.Person.org_id == current_user.org_id,
        ).first()
        if not person:
            raise HTTPException(status_code=404, detail="Pessoa não encontrada")
        log.person_id = person.id
        log.recognized = True
        log.is_authorized = person.is_authorized

    if data.notes is not None:
        log.notes = data.notes

    db.commit()
    db.refresh(log)
    return _build_log_response(log)
