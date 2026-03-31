"""Telegram notification service for RecoFace."""

import httpx
import os
from typing import Optional, List
from sqlalchemy.orm import Session
import models
from tz import now_brt


class TelegramService:
    @staticmethod
    def _api(token: str, method: str, **kwargs) -> Optional[dict]:
        try:
            url = f"https://api.telegram.org/bot{token}/{method}"
            r = httpx.post(url, timeout=10, **kwargs)
            if r.status_code == 200:
                return r.json()
        except Exception as e:
            print(f"[Telegram] Error: {e}")
        return None

    @staticmethod
    def send_message(token: str, chat_id: str, text: str) -> bool:
        result = TelegramService._api(
            token, "sendMessage",
            json={"chat_id": chat_id, "text": text, "parse_mode": "HTML"},
        )
        return result is not None and result.get("ok", False)

    @staticmethod
    def send_photo(token: str, chat_id: str, photo_path: str, caption: str) -> bool:
        try:
            with open(photo_path, "rb") as f:
                result = TelegramService._api(
                    token, "sendPhoto",
                    data={"chat_id": chat_id, "caption": caption, "parse_mode": "HTML"},
                    files={"photo": f},
                )
            return result is not None and result.get("ok", False)
        except Exception as e:
            print(f"[Telegram] Photo error: {e}")
            return False

    @staticmethod
    def verify_token(token: str) -> Optional[str]:
        """Returns bot username if token is valid, None otherwise."""
        result = TelegramService._api(token, "getMe")
        if result and result.get("ok"):
            return result["result"].get("username")
        return None

    @staticmethod
    def get_updates(token: str) -> List[dict]:
        """Get recent messages sent to the bot (for linking chat_ids)."""
        result = TelegramService._api(token, "getUpdates", json={"limit": 50})
        if result and result.get("ok"):
            return result.get("result", [])
        return []

    @staticmethod
    def notify_log(db: Session, org_id: int, face: dict, camera_name: str, photo_path: Optional[str]):
        """Send notification to all active Telegram users in the org."""
        org = db.query(models.Organization).filter(models.Organization.id == org_id).first()
        if not org or not org.telegram_bot_token:
            return

        # Check if this type of event should be notified
        is_recognized = face.get("recognized", False)
        if is_recognized and not org.telegram_notify_recognized:
            return
        if not is_recognized and not org.telegram_notify_unrecognized:
            return

        # Get users with active telegram
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

        # Build message
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

        token = org.telegram_bot_token
        for user in users:
            try:
                if photo_path and os.path.exists(photo_path):
                    TelegramService.send_photo(token, user.telegram_chat_id, photo_path, msg)
                else:
                    TelegramService.send_message(token, user.telegram_chat_id, msg)
            except Exception as e:
                print(f"[Telegram] Notify error for user {user.id}: {e}")


telegram_service = TelegramService()
