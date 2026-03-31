from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from pydantic import BaseModel
from typing import Optional
from database import get_db
import models
import auth
from telegram_service import telegram_service

router = APIRouter()


# ─── Schemas ─────────────────────────────────────────────────────────────────

class TelegramConfigResponse(BaseModel):
    bot_token_set: bool
    bot_username: Optional[str]
    notify_unrecognized: bool
    notify_recognized: bool


class TelegramConfigUpdate(BaseModel):
    bot_token: Optional[str] = None
    notify_unrecognized: Optional[bool] = None
    notify_recognized: Optional[bool] = None


class TelegramUserStatus(BaseModel):
    telegram_chat_id: Optional[str]
    telegram_active: bool


class TelegramLinkRequest(BaseModel):
    chat_id: str


# ─── Webhook (receives messages from Telegram) ──────────────────────────────

@router.post("/webhook/{org_id}")
async def telegram_webhook(org_id: int, body: dict, db: Session = Depends(get_db)):
    """Receives messages from Telegram. Responds to /start with the chat ID."""
    org = db.query(models.Organization).filter(models.Organization.id == org_id).first()
    if not org or not org.telegram_bot_token:
        return {"ok": True}

    message = body.get("message", {})
    text = message.get("text", "")
    chat = message.get("chat", {})
    chat_id = str(chat.get("id", ""))
    first_name = message.get("from", {}).get("first_name", "")

    if text.strip() == "/start" and chat_id:
        telegram_service.send_message(
            org.telegram_bot_token,
            chat_id,
            f"Olá {first_name}! 👋\n\n"
            f"Seu <b>Chat ID</b> é:\n<code>{chat_id}</code>\n\n"
            f"Copie este número e cole nas Configurações do RecoFace para receber alertas.",
        )

    return {"ok": True}


@router.post("/setup-webhook")
def setup_webhook(
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth.require_manager),
):
    """Register the Telegram webhook for this org's bot."""
    org = db.query(models.Organization).filter(models.Organization.id == current_user.org_id).first()
    if not org or not org.telegram_bot_token:
        raise HTTPException(status_code=400, detail="Configure o token do bot primeiro")

    import os
    api_url = os.getenv("API_URL", "")
    if not api_url:
        raise HTTPException(status_code=400, detail="Defina a variável API_URL no servidor (ex: https://seu-dominio.com)")

    webhook_url = f"{api_url}/api/telegram/webhook/{org.id}"
    result = telegram_service._api(
        org.telegram_bot_token, "setWebhook",
        json={"url": webhook_url},
    )
    if result and result.get("ok"):
        return {"message": f"Webhook configurado: {webhook_url}"}
    raise HTTPException(status_code=500, detail="Falha ao configurar webhook")


# ─── Org Config (admin/gerente) ──────────────────────────────────────────────

@router.get("/config", response_model=TelegramConfigResponse)
def get_telegram_config(
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth.require_manager),
):
    org = db.query(models.Organization).filter(models.Organization.id == current_user.org_id).first()
    bot_username = None
    if org and org.telegram_bot_token:
        bot_username = telegram_service.verify_token(org.telegram_bot_token)
    return TelegramConfigResponse(
        bot_token_set=bool(org and org.telegram_bot_token),
        bot_username=bot_username,
        notify_unrecognized=org.telegram_notify_unrecognized if org else True,
        notify_recognized=org.telegram_notify_recognized if org else False,
    )


@router.put("/config", response_model=TelegramConfigResponse)
def update_telegram_config(
    data: TelegramConfigUpdate,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth.require_manager),
):
    org = db.query(models.Organization).filter(models.Organization.id == current_user.org_id).first()
    if not org:
        raise HTTPException(status_code=404, detail="Organização não encontrada")

    if data.bot_token is not None:
        if data.bot_token == "":
            org.telegram_bot_token = None
        else:
            username = telegram_service.verify_token(data.bot_token)
            if not username:
                raise HTTPException(status_code=400, detail="Token do bot inválido")
            org.telegram_bot_token = data.bot_token

    if data.notify_unrecognized is not None:
        org.telegram_notify_unrecognized = data.notify_unrecognized
    if data.notify_recognized is not None:
        org.telegram_notify_recognized = data.notify_recognized

    db.commit()
    db.refresh(org)

    bot_username = None
    if org.telegram_bot_token:
        bot_username = telegram_service.verify_token(org.telegram_bot_token)

    return TelegramConfigResponse(
        bot_token_set=bool(org.telegram_bot_token),
        bot_username=bot_username,
        notify_unrecognized=org.telegram_notify_unrecognized,
        notify_recognized=org.telegram_notify_recognized,
    )


@router.post("/test")
def test_telegram(
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth.require_manager),
):
    """Send a test message to verify the bot works."""
    if not current_user.telegram_chat_id or not current_user.telegram_active:
        raise HTTPException(status_code=400, detail="Vincule seu Telegram primeiro")
    org = db.query(models.Organization).filter(models.Organization.id == current_user.org_id).first()
    if not org or not org.telegram_bot_token:
        raise HTTPException(status_code=400, detail="Configure o token do bot primeiro")

    ok = telegram_service.send_message(
        org.telegram_bot_token,
        current_user.telegram_chat_id,
        "✅ <b>RecoFace - Teste</b>\n\nSe você recebeu esta mensagem, as notificações estão funcionando!",
    )
    if not ok:
        raise HTTPException(status_code=500, detail="Falha ao enviar mensagem de teste")
    return {"message": "Mensagem de teste enviada com sucesso"}


# ─── User Telegram Link ─────────────────────────────────────────────────────

@router.get("/me", response_model=TelegramUserStatus)
def get_my_telegram(
    current_user: models.User = Depends(auth.get_current_active_user),
):
    return TelegramUserStatus(
        telegram_chat_id=current_user.telegram_chat_id,
        telegram_active=current_user.telegram_active,
    )


@router.post("/link", response_model=TelegramUserStatus)
def link_telegram(
    data: TelegramLinkRequest,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth.get_current_active_user),
):
    org = db.query(models.Organization).filter(models.Organization.id == current_user.org_id).first()
    if not org or not org.telegram_bot_token:
        raise HTTPException(status_code=400, detail="Bot do Telegram não configurado. Contate o administrador.")

    # Verify chat_id works by sending a welcome message
    ok = telegram_service.send_message(
        org.telegram_bot_token,
        data.chat_id,
        f"🔗 <b>RecoFace - Vinculado!</b>\n\nOlá {current_user.name}, você receberá alertas do sistema aqui.",
    )
    if not ok:
        raise HTTPException(
            status_code=400,
            detail="Não foi possível enviar mensagem. Verifique se você iniciou uma conversa com o bot (/start).",
        )

    user = db.query(models.User).filter(models.User.id == current_user.id).first()
    user.telegram_chat_id = data.chat_id
    user.telegram_active = True
    db.commit()

    return TelegramUserStatus(
        telegram_chat_id=data.chat_id,
        telegram_active=True,
    )


@router.post("/unlink", response_model=TelegramUserStatus)
def unlink_telegram(
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth.get_current_active_user),
):
    user = db.query(models.User).filter(models.User.id == current_user.id).first()
    user.telegram_chat_id = None
    user.telegram_active = False
    db.commit()
    return TelegramUserStatus(telegram_chat_id=None, telegram_active=False)


@router.patch("/toggle", response_model=TelegramUserStatus)
def toggle_telegram(
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth.get_current_active_user),
):
    if not current_user.telegram_chat_id:
        raise HTTPException(status_code=400, detail="Vincule seu Telegram primeiro")
    user = db.query(models.User).filter(models.User.id == current_user.id).first()
    user.telegram_active = not user.telegram_active
    db.commit()
    return TelegramUserStatus(
        telegram_chat_id=user.telegram_chat_id,
        telegram_active=user.telegram_active,
    )
