from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from sqlalchemy.orm import Session, joinedload
from database import SessionLocal
import models
from face_service import face_service
import json
from tz import now_brt

router = APIRouter()


def _reload_all_encodings(db: Session, org_id: int) -> None:
    photos = (
        db.query(models.PersonPhoto)
        .join(models.Person)
        .options(joinedload(models.PersonPhoto.person))
        .filter(
            models.Person.org_id == org_id,
            models.PersonPhoto.face_encoding.isnot(None),
        )
        .all()
    )
    face_service.load_encodings_from_db(photos)

    person_ids_with_photos = {ph.person_id for ph in photos}
    q = db.query(models.Person).filter(
        models.Person.org_id == org_id,
        models.Person.face_encoding.isnot(None),
    )
    if person_ids_with_photos:
        q = q.filter(~models.Person.id.in_(person_ids_with_photos))
    face_service.load_encodings_legacy(q.all())


@router.websocket("/camera/{camera_id}")
async def camera_websocket(websocket: WebSocket, camera_id: int):
    await websocket.accept()
    db: Session = SessionLocal()

    try:
        # Get camera to find org_id
        camera = db.query(models.Camera).filter(models.Camera.id == camera_id).first()
        if not camera:
            await websocket.close(code=4004, reason="Câmera não encontrada")
            return

        org_id = camera.org_id
        camera.is_active = True
        db.commit()

        # Load encodings for this org
        _reload_all_encodings(db, org_id)

        await websocket.send_text(json.dumps({
            "type": "connected",
            "message": f"Câmera {camera_id} conectada. {len(face_service.known_encodings)} pessoas carregadas.",
        }))

        while True:
            raw = await websocket.receive_text()
            message = json.loads(raw)

            if message.get("type") != "frame":
                continue

            frame_b64 = message.get("frame", "")
            if not frame_b64:
                continue

            results = face_service.process_frame(frame_b64)

            for face in results:
                if face["recognized"]:
                    person_key = f"person_{face['person_id']}"
                    interval = 900
                else:
                    person_key = "unknown"
                    interval = 60

                if face_service.should_capture(camera_id, person_key, interval_seconds=interval):
                    photo_path = face_service.capture_photo(frame_b64, camera_id, face.get("person_id"))

                    log_entry = models.RecognitionLog(
                        org_id=org_id,
                        camera_id=camera_id,
                        person_id=face.get("person_id"),
                        recognized=face["recognized"],
                        is_authorized=face["is_authorized"],
                        confidence=face.get("confidence"),
                        photo_path=photo_path,
                        notes=(
                            f"Pessoa identificada: {face['person_name']}"
                            if face["recognized"]
                            else "Pessoa não identificada na base de dados"
                        ),
                    )
                    db.add(log_entry)
                    db.commit()

            await websocket.send_text(json.dumps({
                "type": "result",
                "faces": results,
                "timestamp": now_brt().isoformat(),
            }))

    except WebSocketDisconnect:
        pass
    except Exception as e:
        print(f"[WebSocket] Error on camera {camera_id}: {e}")
    finally:
        try:
            cam = db.query(models.Camera).filter(models.Camera.id == camera_id).first()
            if cam:
                cam.is_active = False
                db.commit()
        except Exception:
            pass
        db.close()
