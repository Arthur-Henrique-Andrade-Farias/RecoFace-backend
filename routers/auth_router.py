from fastapi import APIRouter, Depends, HTTPException, status, UploadFile, File
from sqlalchemy.orm import Session
from typing import List, Optional
import os
import shutil
from database import get_db
import models
import schemas
import auth

router = APIRouter()


def _user_response(u: models.User) -> schemas.UserResponse:
    return schemas.UserResponse(
        id=u.id,
        name=u.name,
        email=u.email,
        role=u.role,
        is_active=u.is_active,
        org_name=u.organization.name if u.organization else None,
        telegram_chat_id=u.telegram_chat_id,
        telegram_active=u.telegram_active or False,
        created_at=u.created_at,
    )


@router.post("/login", response_model=schemas.Token)
def login(
    credentials: schemas.UserLogin,
    db: Session = Depends(get_db),
):
    user = db.query(models.User).filter(models.User.email == credentials.email.lower().strip()).first()
    if not user or not auth.verify_password(credentials.password, user.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Email ou senha incorretos",
        )
    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Conta desativada. Contate o administrador.",
        )
    token = auth.create_access_token(data={"sub": user.email})
    return {"access_token": token, "token_type": "bearer"}


@router.get("/me", response_model=schemas.UserResponse)
def get_me(current_user: models.User = Depends(auth.get_current_active_user)):
    return _user_response(current_user)


# ─── Branding ────────────────────────────────────────────────────────────────

def _branding_response(org: models.Organization) -> schemas.BrandingResponse:
    logo_url = f"/uploads/{org.brand_logo_path}" if org.brand_logo_path else None
    return schemas.BrandingResponse(
        brand_name=org.brand_name or "RecoFace",
        brand_subtitle=org.brand_subtitle or "Monitorando vidas",
        brand_logo_url=logo_url,
    )


@router.get("/branding", response_model=schemas.BrandingResponse)
def get_branding(
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth.get_current_active_user),
):
    org = db.query(models.Organization).filter(models.Organization.id == current_user.org_id).first()
    if not org:
        return schemas.BrandingResponse(brand_name="RecoFace", brand_subtitle="Monitorando vidas", brand_logo_url=None)
    return _branding_response(org)


@router.put("/branding", response_model=schemas.BrandingResponse)
def update_branding(
    data: schemas.BrandingUpdate,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth.require_manager),
):
    org = db.query(models.Organization).filter(models.Organization.id == current_user.org_id).first()
    if not org:
        raise HTTPException(status_code=404, detail="Organização não encontrada")
    if data.brand_name is not None:
        org.brand_name = data.brand_name
    if data.brand_subtitle is not None:
        org.brand_subtitle = data.brand_subtitle
    db.commit()
    db.refresh(org)
    return _branding_response(org)


@router.post("/branding/logo", response_model=schemas.BrandingResponse)
async def upload_branding_logo(
    logo: UploadFile = File(...),
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth.require_manager),
):
    org = db.query(models.Organization).filter(models.Organization.id == current_user.org_id).first()
    if not org:
        raise HTTPException(status_code=404, detail="Organização não encontrada")

    os.makedirs("uploads/branding", exist_ok=True)
    filename = f"logo_org{org.id}_{logo.filename}"
    filepath = os.path.join("branding", filename)
    full_path = os.path.join("uploads", filepath)
    with open(full_path, "wb") as f:
        shutil.copyfileobj(logo.file, f)

    org.brand_logo_path = filepath
    db.commit()
    db.refresh(org)
    return _branding_response(org)


# ─── User management: admin + gerente ────────────────────────────────────────

@router.get("/users", response_model=List[schemas.UserResponse])
def list_users(
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth.require_manager),
):
    users = (
        db.query(models.User)
        .filter(models.User.org_id == current_user.org_id)
        .order_by(models.User.created_at.desc())
        .all()
    )
    return [_user_response(u) for u in users]


@router.post("/users", response_model=schemas.UserResponse)
def create_user(
    user_data: schemas.UserCreate,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth.require_manager),
):
    # Gerente cannot create admin
    if current_user.role == "gerente" and user_data.role not in ("gerente", "configurador", "visualizador"):
        raise HTTPException(status_code=403, detail="Gerentes não podem criar administradores")

    existing = db.query(models.User).filter(
        models.User.email == user_data.email.lower().strip()
    ).first()
    if existing:
        raise HTTPException(status_code=400, detail="Este email já está cadastrado")

    new_user = models.User(
        org_id=current_user.org_id,
        name=user_data.name.strip(),
        email=user_data.email.lower().strip(),
        hashed_password=auth.get_password_hash(user_data.password),
        role=user_data.role,
    )
    db.add(new_user)
    db.commit()
    db.refresh(new_user)
    return _user_response(new_user)


@router.put("/users/{user_id}", response_model=schemas.UserResponse)
def update_user(
    user_id: int,
    data: schemas.UserUpdate,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth.require_manager),
):
    user = db.query(models.User).filter(
        models.User.id == user_id,
        models.User.org_id == current_user.org_id,
    ).first()
    if not user:
        raise HTTPException(status_code=404, detail="Usuário não encontrado")
    if user.role == "admin" and current_user.role != "admin":
        raise HTTPException(status_code=403, detail="Apenas administradores podem editar outros administradores")

    if data.name is not None:
        user.name = data.name.strip()
    if data.role is not None:
        if current_user.role == "gerente" and data.role == "admin":
            raise HTTPException(status_code=403, detail="Gerentes não podem promover a administrador")
        user.role = data.role
    if data.telegram_chat_id is not None:
        user.telegram_chat_id = data.telegram_chat_id if data.telegram_chat_id else None
    if data.telegram_active is not None:
        user.telegram_active = data.telegram_active

    db.commit()
    db.refresh(user)
    return _user_response(user)


@router.patch("/users/{user_id}/toggle")
def toggle_user(
    user_id: int,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth.require_manager),
):
    user = db.query(models.User).filter(
        models.User.id == user_id,
        models.User.org_id == current_user.org_id,
    ).first()
    if not user:
        raise HTTPException(status_code=404, detail="Usuário não encontrado")
    if user.id == current_user.id:
        raise HTTPException(status_code=400, detail="Você não pode desativar sua própria conta")
    if user.role == "admin" and current_user.role != "admin":
        raise HTTPException(status_code=403, detail="Apenas administradores podem gerenciar outros administradores")
    user.is_active = not user.is_active
    db.commit()
    return {"message": f"Usuário {'ativado' if user.is_active else 'desativado'}"}


@router.delete("/users/{user_id}")
def delete_user(
    user_id: int,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth.require_manager),
):
    user = db.query(models.User).filter(
        models.User.id == user_id,
        models.User.org_id == current_user.org_id,
    ).first()
    if not user:
        raise HTTPException(status_code=404, detail="Usuário não encontrado")
    if user.id == current_user.id:
        raise HTTPException(status_code=400, detail="Você não pode remover sua própria conta")
    if user.role == "admin":
        raise HTTPException(status_code=400, detail="Não é possível remover administradores pela interface")
    db.delete(user)
    db.commit()
    return {"message": "Usuário removido"}
