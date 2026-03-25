from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from sqlalchemy.orm import Session, joinedload
from database import SessionLocal
import models
from face_service import face_service
import json
from datetime import datetime

router = APIRouter()


def _reload_all_encodings(db: Session) -> None:
    """Load encodings from PersonPhoto table + legacy Person encodings."""
    photos = (
        db.query(models.PersonPhoto)
        .options(joinedload(models.PersonPhoto.person))
        .filter(models.PersonPhoto.face_encoding.isnot(None))
        .all()
    )
    face_service.load_encodings_from_db(photos)

    # Also load legacy encodings from persons without photos
    person_ids_with_photos = {ph.person_id for ph in photos}
    if person_ids_with_photos:
        legacy = (
            db.query(models.Person)
            .filter(
                models.Person.face_encoding.isnot(None),
                ~models.Person.id.in_(person_ids_with_photos),
            )
            .all()
        )
    else:
        legacy = (
            db.query(models.Person)
            .filter(models.Person.face_encoding.isnot(None))
            .all()
        )
    face_service.load_encodings_legacy(legacy)


@router.websocket("/camera/{camera_id}")
async def camera_websocket(websocket: WebSocket, camera_id: int):
    await websocket.accept()
    db: Session = SessionLocal()

    try:
        # Load latest encodings on connection
        _reload_all_encodings(db)

        # Ensure camera record exists and mark active
        camera = db.query(models.Camera).filter(models.Camera.id == camera_id).first()
        if camera:
            camera.is_active = True
            db.commit()

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

            # Detect & recognize faces
            results = face_service.process_frame(frame_b64)

            # Persist logs and capture photos
            # Recognized: 1 photo every 15 minutes per person
            # Unrecognized: 1 photo every 1 minute per camera (all unknowns share key)
            for face in results:
                if face["recognized"]:
                    person_key = f"person_{face['person_id']}"
                    interval = 900  # 15 minutes
                else:
                    person_key = "unknown"
                    interval = 60  # 1 minute

                if face_service.should_capture(camera_id, person_key, interval_seconds=interval):
                    photo_path = face_service.capture_photo(frame_b64, camera_id, face.get("person_id"))

                    log_entry = models.RecognitionLog(
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

            # Send results back to client
            await websocket.send_text(json.dumps({
                "type": "result",
                "faces": results,
                "timestamp": datetime.now().isoformat(),
            }))

    except WebSocketDisconnect:
        pass
    except Exception as e:
        print(f"[WebSocket] Error on camera {camera_id}: {e}")
    finally:
        # Mark camera inactive when client disconnects
        try:
            cam = db.query(models.Camera).filter(models.Camera.id == camera_id).first()
            if cam:
                cam.is_active = False
                db.commit()
        except Exception:
            pass
        db.close()
