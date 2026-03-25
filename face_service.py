import numpy as np
import cv2
import base64
import json
import os
from datetime import datetime
from typing import List, Tuple, Optional, Dict
from PIL import Image
import io

# Try to import face_recognition; fall back to OpenCV-only detection
try:
    import face_recognition
    FACE_RECOGNITION_AVAILABLE = True
    print("[FaceService] face_recognition carregado com sucesso.")
except Exception:
    FACE_RECOGNITION_AVAILABLE = False
    print("[FaceService] face_recognition não disponível. Usando detecção OpenCV (sem reconhecimento).")


class FaceService:
    def __init__(self):
        self.known_encodings: List[np.ndarray] = []
        self.known_ids: List[int] = []
        self.known_names: List[str] = []
        self.known_authorized: List[bool] = []
        self.last_capture_time: Dict[str, datetime] = {}

        # OpenCV fallback: Haar cascade face detector
        if not FACE_RECOGNITION_AVAILABLE:
            cascade_path = cv2.data.haarcascades + "haarcascade_frontalface_default.xml"
            self.face_cascade = cv2.CascadeClassifier(cascade_path)

    # ─── Encoding Management ─────────────────────────────────────────────────

    def load_encodings_from_db(self, person_photos) -> None:
        """Load face encodings from PersonPhoto records.
        Each photo produces one encoding entry. Multiple photos of the same
        person result in multiple entries, improving recognition accuracy."""
        self.known_encodings = []
        self.known_ids = []
        self.known_names = []
        self.known_authorized = []

        if not FACE_RECOGNITION_AVAILABLE:
            return

        for photo in person_photos:
            if photo.face_encoding:
                try:
                    encoding = np.array(json.loads(photo.face_encoding))
                    self.known_encodings.append(encoding)
                    self.known_ids.append(photo.person.id)
                    self.known_names.append(photo.person.name)
                    self.known_authorized.append(photo.person.is_authorized)
                except Exception as e:
                    print(f"[FaceService] Error loading encoding for photo {photo.id}: {e}")

        unique_persons = set(self.known_ids)
        print(f"[FaceService] Carregados {len(self.known_encodings)} encoding(s) de {len(unique_persons)} pessoa(s): {list(set(self.known_names))}")

    def load_encodings_legacy(self, persons) -> None:
        """Append encodings from Person.face_encoding (backward compat).
        NOTE: Does NOT clear lists — call after load_encodings_from_db."""
        if not FACE_RECOGNITION_AVAILABLE:
            return

        for person in persons:
            if person.face_encoding:
                try:
                    encoding = np.array(json.loads(person.face_encoding))
                    self.known_encodings.append(encoding)
                    self.known_ids.append(person.id)
                    self.known_names.append(person.name)
                    self.known_authorized.append(person.is_authorized)
                except Exception as e:
                    print(f"[FaceService] Error loading encoding for person {person.id}: {e}")

    def extract_encoding_from_image(self, image_path: str) -> Optional[List[float]]:
        if not FACE_RECOGNITION_AVAILABLE:
            return None
        try:
            image = face_recognition.load_image_file(image_path)
            encodings = face_recognition.face_encodings(image)
            if encodings:
                return encodings[0].tolist()
            return None
        except Exception as e:
            print(f"[FaceService] Error extracting encoding from file: {e}")
            return None

    def extract_encoding_from_bytes(self, image_bytes: bytes) -> Optional[List[float]]:
        if not FACE_RECOGNITION_AVAILABLE:
            return None
        try:
            pil_image = Image.open(io.BytesIO(image_bytes))
            image = np.array(pil_image.convert("RGB"))
            encodings = face_recognition.face_encodings(image)
            if encodings:
                return encodings[0].tolist()
            return None
        except Exception as e:
            print(f"[FaceService] Error extracting encoding from bytes: {e}")
            return None

    # ─── Frame Processing ────────────────────────────────────────────────────

    def _process_frame_face_recognition(self, frame_rgb: np.ndarray) -> List[dict]:
        """Process using face_recognition library (detection + recognition).

        Uses per-person best-match: groups all encodings by person_id,
        takes the minimum distance for each person, then picks the person
        with the lowest minimum distance. This ensures multiple photos
        per person only helps (best angle wins), never hurts.
        """
        h, w = frame_rgb.shape[:2]
        scale = 0.5
        small = cv2.resize(frame_rgb, (int(w * scale), int(h * scale)))

        face_locations = face_recognition.face_locations(small)
        face_encodings = face_recognition.face_encodings(small, face_locations)

        results = []
        for (top, right, bottom, left), face_encoding in zip(face_locations, face_encodings):
            top = int(top / scale)
            right = int(right / scale)
            bottom = int(bottom / scale)
            left = int(left / scale)

            recognized = False
            person_id = None
            person_name = "Desconhecido"
            is_authorized = False
            confidence = 0.0

            if self.known_encodings:
                distances = face_recognition.face_distance(self.known_encodings, face_encoding)

                # Group distances by person_id → pick best (min) distance per person
                person_best: Dict[int, dict] = {}
                for idx, dist in enumerate(distances):
                    pid = self.known_ids[idx]
                    if pid not in person_best or dist < person_best[pid]["distance"]:
                        person_best[pid] = {
                            "distance": float(dist),
                            "idx": idx,
                        }

                if person_best:
                    # Find person with lowest best-distance
                    best_person_id = min(person_best, key=lambda pid: person_best[pid]["distance"])
                    best = person_best[best_person_id]
                    best_name = self.known_names[best["idx"]]
                    print(f"[FaceService] Melhor match: {best_name} (distância={best['distance']:.3f}, limite=0.6)")

                    # Check if within tolerance (0.6 is the default, more forgiving)
                    if best["distance"] <= 0.6:
                        recognized = True
                        best_idx = best["idx"]
                        person_id = self.known_ids[best_idx]
                        person_name = self.known_names[best_idx]
                        is_authorized = self.known_authorized[best_idx]
                        confidence = float(1.0 - best["distance"])

            results.append({
                "location": {"top": top, "right": right, "bottom": bottom, "left": left},
                "recognized": recognized,
                "person_id": person_id,
                "person_name": person_name,
                "is_authorized": is_authorized,
                "confidence": round(confidence * 100, 1),
            })
        return results

    def _process_frame_opencv(self, frame_rgb: np.ndarray) -> List[dict]:
        """Fallback: detect faces with OpenCV Haar cascade (no recognition)."""
        gray = cv2.cvtColor(frame_rgb, cv2.COLOR_RGB2GRAY)
        faces = self.face_cascade.detectMultiScale(
            gray, scaleFactor=1.1, minNeighbors=5, minSize=(60, 60)
        )

        results = []
        for (x, y, w, h) in faces:
            results.append({
                "location": {"top": int(y), "right": int(x + w), "bottom": int(y + h), "left": int(x)},
                "recognized": False,
                "person_id": None,
                "person_name": "Desconhecido",
                "is_authorized": False,
                "confidence": 0.0,
            })
        return results

    def process_frame(self, frame_base64: str) -> List[dict]:
        """Detect and recognize faces in a base64-encoded frame."""
        try:
            if "," in frame_base64:
                frame_base64 = frame_base64.split(",")[1]

            frame_bytes = base64.b64decode(frame_base64)
            pil_image = Image.open(io.BytesIO(frame_bytes)).convert("RGB")
            frame_rgb = np.array(pil_image)

            if FACE_RECOGNITION_AVAILABLE:
                return self._process_frame_face_recognition(frame_rgb)
            else:
                return self._process_frame_opencv(frame_rgb)

        except Exception as e:
            print(f"[FaceService] Error processing frame: {e}")
            return []

    # ─── Photo Capture ───────────────────────────────────────────────────────

    def capture_photo(
        self, frame_base64: str, camera_id: int, person_id: Optional[int]
    ) -> Optional[str]:
        try:
            if "," in frame_base64:
                frame_base64 = frame_base64.split(",")[1]

            frame_bytes = base64.b64decode(frame_base64)
            pil_image = Image.open(io.BytesIO(frame_bytes)).convert("RGB")

            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            person_str = str(person_id) if person_id else "unknown"
            filename = f"capture_cam{camera_id}_{person_str}_{timestamp}.jpg"
            filepath = os.path.join("uploads", "captures", filename)

            pil_image.save(filepath, "JPEG", quality=88)
            return filepath
        except Exception as e:
            print(f"[FaceService] Error capturing photo: {e}")
            return None

    def should_capture(
        self, camera_id: int, person_key: str, interval_seconds: int = 60
    ) -> bool:
        """Returns True once per interval_seconds per (camera, person)."""
        key = f"{camera_id}_{person_key}"
        now = datetime.now()
        last = self.last_capture_time.get(key)
        if last is None or (now - last).total_seconds() >= interval_seconds:
            self.last_capture_time[key] = now
            return True
        return False


# Singleton instance shared across the app
face_service = FaceService()
