"""Telegram notification service for RecoFace."""

import os
import threading
from typing import Optional, List
from sqlalchemy.orm import Session
import models
from tz import now_brt


def _telegram_post(token: str, method: str, **kwargs) -> Optional[dict]:
    """Make a synchronous request to Telegram API. Safe to call from any context."""
    import httpx
    try:
        url = f"https://api.telegram.org/bot{token}/{method}"
        with httpx.Client(timeout=10) as client:
            r = client.post(url, **kwargs)
            if r.status_code == 200:
                return r.json()
            print(f"[Telegram] {method} returned {r.status_code}: {r.text[:200]}")
    except Exception as e:
        print(f"[Telegram] Error in {method}: {e}")
    return None


class TelegramService:
    @staticmethod
    def send_message(token: str, chat_id: str, text: str) -> bool:
        result = _telegram_post(
            token, "sendMessage",
            json={"chat_id": chat_id, "text": text, "parse_mode": "HTML"},
        )
        return result is not None and result.get("ok", False)

    @staticmethod
    def send_photo(token: str, chat_id: str, photo_path: str, caption: str) -> bool:
        try:
            with open(photo_path, "rb") as f:
                result = _telegram_post(
                    token, "sendPhoto",
                    data={"chat_id": chat_id, "caption": caption, "parse_mode": "HTML"},
                    files={"photo": ("photo.jpg", f, "image/jpeg")},
                )
            return result is not None and result.get("ok", False)
        except Exception as e:
            print(f"[Telegram] Photo error: {e}")
            return False

    @staticmethod
    def verify_token(token: str) -> Optional[str]:
        result = _telegram_post(token, "getMe")
        if result and result.get("ok"):
            return result["result"].get("username")
        return None

    @staticmethod
    def _api(token: str, method: str, **kwargs) -> Optional[dict]:
        return _telegram_post(token, method, **kwargs)

    @staticmethod
    def notify_log(db: Session, org_id: int, face: dict, camera_name: str, photo_path: Optional[str]):
        """Send notification in a background thread to avoid blocking the WebSocket."""
        org = db.query(models.Organization).filter(models.Organization.id == org_id).first()
        if not org or not org.telegram_bot_token:
            return

        is_recognized = face.get("recognized", False)
        if is_recognized and not org.telegram_notify_recognized:
            return
        if not is_recognized and not org.telegram_notify_unrecognized:
            return

        users = (
            db.query(models.User)
            .filter(
                models.User.org_id == org_id,
                models.User.telegram_active == True,
                models.User.telegram_chat_id.isnot(None),
            )
            .all()
        )
        if not users:
            return

        # Collect data before passing to thread (avoid lazy loading issues)
        token = org.telegram_bot_token
        chat_ids = [u.telegram_chat_id for u in users]

        timestamp = now_brt().strftime("%d/%m/%Y %H:%M:%S")
        if is_recognized:
            person_name = face.get("person_name", "—")
            confidence = face.get("confidence", 0)
            is_auth = face.get("is_authorized", False)
            status = "Autorizado" if is_auth else "NAO AUTORIZADO"
            msg = (
                f"<b>{'✅' if is_auth else '⚠️'} Pessoa Identificada</b>\n\n"
                f"<b>Nome:</b> {person_name}\n"
                f"<b>Status:</b> {status}\n"
                f"<b>Confiança:</b> {confidence}%\n"
                f"<b>Câmera:</b> {camera_name}\n"
                f"<b>Horário:</b> {timestamp}"
            )
        else:
            msg = (
                f"<b>🚨 Pessoa Não Identificada</b>\n\n"
                f"<b>Câmera:</b> {camera_name}\n"
                f"<b>Horário:</b> {timestamp}\n"
                f"Pessoa não consta na base de dados."
            )

        resolved_photo = photo_path if photo_path and os.path.exists(photo_path) else None

        def _send():
            for cid in chat_ids:
                try:
                    if resolved_photo:
                        TelegramService.send_photo(token, cid, resolved_photo, msg)
                    else:
                        TelegramService.send_message(token, cid, msg)
                except Exception as e:
                    print(f"[Telegram] Notify error: {e}")

        threading.Thread(target=_send, daemon=True).start()


telegram_service = TelegramService()
