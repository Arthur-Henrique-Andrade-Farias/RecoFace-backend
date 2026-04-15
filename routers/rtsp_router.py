"""WebSocket endpoint for RTSP/DVR cameras.
The server reads the RTSP stream via OpenCV, processes frames with
face_recognition, and sends annotated JPEG frames + results to the client."""

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from sqlalchemy.orm import Session, joinedload
from database import SessionLocal
import models
from face_service import face_service
from telegram_service import telegram_service
from whatsapp_service import whatsapp_service
import json
import cv2
import base64
import asyncio
import threading
import numpy as np
from tz import now_brt

router = APIRouter()

PROCESS_EVERY_N = 3  # Process face recognition every Nth frame (skip others for speed)
JPEG_QUALITY = 60


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


def _draw_boxes(frame: np.ndarray, faces: list) -> np.ndarray:
    """Draw bounding boxes on frame for RTSP stream display."""
    for face in faces:
        loc = face["location"]
        top, right, bottom, left = loc["top"], loc["right"], loc["bottom"], loc["left"]
        recognized = face["recognized"]
        is_auth = face.get("is_authorized", False)
        color = (0, 255, 0) if (recognized and is_auth) else (0, 0, 255)

        cv2.rectangle(frame, (left, top), (right, bottom), color, 2)

        label = face["person_name"]
        if recognized:
            label += f" {face.get('confidence', 0):.0f}%"

        (tw, th), _ = cv2.getTextSize(label, cv2.FONT_HERSHEY_SIMPLEX, 0.5, 1)
        cv2.rectangle(frame, (left, top - th - 10), (left + tw + 6, top), color, -1)
        cv2.putText(frame, label, (left + 3, top - 5), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 1)

    return frame


@router.websocket("/rtsp/{camera_id}")
async def rtsp_camera_websocket(websocket: WebSocket, camera_id: int):
    await websocket.accept()
    db: Session = SessionLocal()
    stop_event = threading.Event()

    try:
        camera = db.query(models.Camera).filter(models.Camera.id == camera_id).first()
        if not camera:
            await websocket.send_text(json.dumps({"type": "error", "message": "Câmera não encontrada"}))
            await websocket.close()
            return

        if not camera.url:
            await websocket.send_text(json.dumps({"type": "error", "message": "URL RTSP não configurada para esta câmera"}))
            await websocket.close()
            return

        org_id = camera.org_id
        camera.is_active = True
        db.commit()

        _reload_all_encodings(db, org_id)

        await websocket.send_text(json.dumps({
            "type": "connected",
            "message": f"Conectando à câmera {camera.name}... {len(face_service.known_encodings)} pessoas carregadas.",
        }))

        # RTSP capture runs in a separate thread
        frame_buffer = {"frame": None, "faces": [], "lock": threading.Lock()}

        def rtsp_worker():
            cap = cv2.VideoCapture(camera.url)
            if not cap.isOpened():
                frame_buffer["error"] = "Não foi possível conectar à câmera RTSP"
                return

            cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
            frame_count = 0
            worker_db = SessionLocal()

            try:
                while not stop_event.is_set():
                    ret, frame = cap.read()
                    if not ret:
                        # Try reconnecting
                        cap.release()
                        cap = cv2.VideoCapture(camera.url)
                        if not cap.isOpened():
                            frame_buffer["error"] = "Conexão com câmera perdida"
                            break
                        continue

                    frame_count += 1
                    faces = []

                    # Process face recognition every Nth frame
                    if frame_count % PROCESS_EVERY_N == 0:
                        rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                        _, buf = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 85])
                        b64 = base64.b64encode(buf).decode("utf-8")
                        faces = face_service.process_frame(b64)

                        # Log and capture
                        for face in faces:
                            if face["recognized"]:
                                person_key = f"person_{face['person_id']}"
                                interval = 900
                            else:
                                person_key = "unknown"
                                interval = 60

                            if face_service.should_capture(camera_id, person_key, interval_seconds=interval):
                                photo_path = face_service.capture_photo(b64, camera_id, face.get("person_id"))
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
                                worker_db.add(log_entry)
                                worker_db.commit()
                                telegram_service.notify_log(worker_db, org_id, face, camera.name, photo_path)
                                whatsapp_service.notify_log(worker_db, org_id, face, camera.name, camera_id, photo_path)

                    # Draw boxes and encode frame for streaming
                    annotated = _draw_boxes(frame.copy(), faces) if faces else frame
                    _, jpeg = cv2.imencode(".jpg", annotated, [cv2.IMWRITE_JPEG_QUALITY, JPEG_QUALITY])

                    with frame_buffer["lock"]:
                        frame_buffer["frame"] = base64.b64encode(jpeg).decode("utf-8")
                        frame_buffer["faces"] = faces

            finally:
                cap.release()
                worker_db.close()

        # Start RTSP thread
        worker_thread = threading.Thread(target=rtsp_worker, daemon=True)
        worker_thread.start()

        # Stream frames to WebSocket client
        last_frame = None
        while True:
            # Check for error
            if "error" in frame_buffer:
                await websocket.send_text(json.dumps({
                    "type": "error",
                    "message": frame_buffer["error"],
                }))
                break

            # Check for disconnect message from client
            try:
                msg = await asyncio.wait_for(websocket.receive_text(), timeout=0.1)
                data = json.loads(msg)
                if data.get("type") == "stop":
                    break
            except asyncio.TimeoutError:
                pass

            # Send current frame
            with frame_buffer["lock"]:
                current_frame = frame_buffer.get("frame")
                current_faces = frame_buffer.get("faces", [])

            if current_frame and current_frame != last_frame:
                last_frame = current_frame
                await websocket.send_text(json.dumps({
                    "type": "rtsp_frame",
                    "frame": f"data:image/jpeg;base64,{current_frame}",
                    "faces": current_faces,
                    "timestamp": now_brt().isoformat(),
                }))

            await asyncio.sleep(0.1)  # ~10 FPS to client

    except WebSocketDisconnect:
        pass
    except Exception as e:
        print(f"[RTSP WebSocket] Error on camera {camera_id}: {e}")
    finally:
        stop_event.set()
        try:
            cam = db.query(models.Camera).filter(models.Camera.id == camera_id).first()
            if cam:
                cam.is_active = False
                db.commit()
        except Exception:
            pass
        db.close()
