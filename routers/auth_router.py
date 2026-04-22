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
        whatsapp_phone=u.whatsapp_phone,
        whatsapp_active=u.whatsapp_active or False,
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


# ─── WhatsApp Config ─────────────────────────────────────────────────────────

@router.get("/whatsapp-config")
def get_whatsapp_config(
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth.require_manager),
):
    org = db.query(models.Organization).filter(models.Organization.id == current_user.org_id).first()
    return {
        "webhook_url": org.whatsapp_webhook_url or "",
        "phone_field": org.whatsapp_phone_field or "phone",
        "notify_recognized": org.whatsapp_notify_recognized if org else True,
        "notify_unrecognized": org.whatsapp_notify_unrecognized if org else False,
        "frontend_url": org.frontend_url or "",
    }


@router.put("/whatsapp-config")
def update_whatsapp_config(
    data: dict,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth.require_manager),
):
    org = db.query(models.Organization).filter(models.Organization.id == current_user.org_id).first()
    if not org:
        raise HTTPException(status_code=404, detail="Organização não encontrada")

    if "webhook_url" in data:
        org.whatsapp_webhook_url = data["webhook_url"] or None
    if "phone_field" in data:
        org.whatsapp_phone_field = data["phone_field"] or "phone"
    if "notify_recognized" in data:
        org.whatsapp_notify_recognized = data["notify_recognized"]
    if "notify_unrecognized" in data:
        org.whatsapp_notify_unrecognized = data["notify_unrecognized"]
    if "frontend_url" in data:
        org.frontend_url = data["frontend_url"].rstrip("/") if data["frontend_url"] else None

    db.commit()
    db.refresh(org)
    return {
        "webhook_url": org.whatsapp_webhook_url or "",
        "phone_field": org.whatsapp_phone_field or "phone",
        "notify_recognized": org.whatsapp_notify_recognized,
        "notify_unrecognized": org.whatsapp_notify_unrecognized,
        "frontend_url": org.frontend_url or "",
    }


@router.post("/whatsapp-test")
def test_whatsapp(
    data: dict,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth.require_manager),
):
    org = db.query(models.Organization).filter(models.Organization.id == current_user.org_id).first()
    if not org or not org.whatsapp_webhook_url:
        raise HTTPException(status_code=400, detail="Configure a URL do webhook primeiro")

    phone = data.get("phone", "")
    if not phone:
        raise HTTPException(status_code=400, detail="Informe um número de telefone para teste")

    from whatsapp_service import WhatsAppService
    from tz import now_brt

    ok = WhatsAppService.send_webhook(org.whatsapp_webhook_url, {
        "telefone": phone,
        "nome": "Teste RecoFace",
        "data_hora": now_brt().isoformat(),
        "local": "Teste do sistema",
        "camera_id": "TEST",
    })
    if not ok:
        raise HTTPException(status_code=500, detail="Falha ao enviar para o webhook")
    return {"message": "Mensagem de teste enviada com sucesso"}


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
        telegram_chat_id=user_data.telegram_chat_id if user_data.telegram_chat_id else None,
        telegram_active=user_data.telegram_active if user_data.telegram_chat_id else False,
        whatsapp_phone=user_data.whatsapp_phone if hasattr(user_data, 'whatsapp_phone') else None,
        whatsapp_active=user_data.whatsapp_active if hasattr(user_data, 'whatsapp_active') and user_data.whatsapp_phone else False,
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
    if data.whatsapp_phone is not None:
        user.whatsapp_phone = data.whatsapp_phone if data.whatsapp_phone else None
    if data.whatsapp_active is not None:
        user.whatsapp_active = data.whatsapp_active

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
