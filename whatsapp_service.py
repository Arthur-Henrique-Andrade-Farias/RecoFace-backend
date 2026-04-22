"""WhatsApp notification service via n8n webhook for RecoFace.
Works like Telegram: each User configures their phone and receives alerts."""

import threading
from typing import Optional
from sqlalchemy.orm import Session
import models
from tz import now_brt


class WhatsAppService:
    @staticmethod
    def send_webhook(webhook_url: str, payload: dict) -> tuple[bool, str]:
        """Send webhook and return (success, message)"""
        import httpx
        try:
            with httpx.Client(timeout=10) as client:
                r = client.post(webhook_url, json=payload)
                if r.status_code in (200, 201, 204):
                    return True, "Webhook enviado com sucesso"
                error_msg = f"Webhook retornou {r.status_code}: {r.text[:200]}"
                print(f"[WhatsApp] {error_msg}")
                return False, error_msg
        except httpx.ConnectError as e:
            msg = f"Erro de conexão ao webhook: {str(e)[:100]}"
            print(f"[WhatsApp] {msg}")
            return False, msg
        except httpx.TimeoutException:
            msg = "Timeout ao conectar ao webhook (10s)"
            print(f"[WhatsApp] {msg}")
            return False, msg
        except Exception as e:
            msg = f"Erro ao enviar webhook: {str(e)[:100]}"
            print(f"[WhatsApp] {msg}")
            return False, msg

    @staticmethod
    def notify_log(
        db: Session,
        org_id: int,
        face: dict,
        camera_name: str,
        camera_id: int,
        photo_path: Optional[str],
        log_id: Optional[int] = None,
    ):
        """Send WhatsApp notification to all active users in the org."""
        org = db.query(models.Organization).filter(models.Organization.id == org_id).first()
        if not org or not org.whatsapp_webhook_url:
            return

        is_recognized = face.get("recognized", False)
        if is_recognized and not org.whatsapp_notify_recognized:
            return
        if not is_recognized and not org.whatsapp_notify_unrecognized:
            return

        # Get users with active WhatsApp
        users = (
            db.query(models.User)
            .filter(
                models.User.org_id == org_id,
                models.User.whatsapp_active == True,
                models.User.whatsapp_phone.isnot(None),
            )
            .all()
        )
        if not users:
            return

        # Collect data
        webhook_url = org.whatsapp_webhook_url
        frontend_url = (org.frontend_url or "").rstrip("/")
        phones = [u.whatsapp_phone for u in users]
        timestamp = now_brt()
        person_name = face.get("person_name", "Desconhecido")
        confidence = face.get("confidence", 0)
        is_auth = face.get("is_authorized", False)

        if is_recognized:
            status = "Autorizado" if is_auth else "NAO AUTORIZADO"
            nome_msg = f"{person_name} ({status}) - Confiança: {confidence}%"
        else:
            nome_msg = "Pessoa não identificada na base de dados"

        # Build link to the log
        link = ""
        if frontend_url and log_id:
            link = f"{frontend_url}/logs?log={log_id}"

        # Append link to existing fields so n8n templates show it without modification
        if link:
            nome_msg = f"{nome_msg}\n\n🔗 Verificar alerta: {link}"
            local_with_link = f"{camera_name}\n🔗 {link}"
        else:
            local_with_link = camera_name

        def _send():
            for phone in phones:
                try:
                    success, message = WhatsAppService.send_webhook(webhook_url, {
                        "telefone": phone,
                        "link": link,
                        "nome": nome_msg,
                        "data_hora": timestamp.isoformat(),
                        "local": local_with_link,
                        "camera_id": str(camera_id),
                    })
                    if not success:
                        print(f"[WhatsApp] Falha ao enviar para {phone}: {message}")
                except Exception as e:
                    print(f"[WhatsApp] Notify error: {e}")

        threading.Thread(target=_send, daemon=True).start()


whatsapp_service = WhatsAppService()
