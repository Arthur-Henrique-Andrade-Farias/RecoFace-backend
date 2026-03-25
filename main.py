import os
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from sqlalchemy.orm import joinedload

from database import engine, Base, SessionLocal
import models
from routers import auth_router, cameras_router, persons_router, logs_router, ws_router
from face_service import face_service

# ─── DB Init ─────────────────────────────────────────────────────────────────
Base.metadata.create_all(bind=engine)

# Create upload directories
os.makedirs("uploads/photos", exist_ok=True)
os.makedirs("uploads/captures", exist_ok=True)

# ─── App ─────────────────────────────────────────────────────────────────────
app = FastAPI(
    title="RecoFace API",
    description="Sistema de Reconhecimento Facial para Escolas",
    version="1.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:3000",
        "http://127.0.0.1:3000",
        os.getenv("FRONTEND_URL", ""),
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Serve uploaded files
app.mount("/uploads", StaticFiles(directory="uploads"), name="uploads")

# ─── Routers ─────────────────────────────────────────────────────────────────
app.include_router(auth_router.router, prefix="/api/auth", tags=["Autenticação"])
app.include_router(cameras_router.router, prefix="/api/cameras", tags=["Câmeras"])
app.include_router(persons_router.router, prefix="/api/persons", tags=["Pessoas"])
app.include_router(logs_router.router, prefix="/api/logs", tags=["Logs"])
app.include_router(ws_router.router, prefix="/ws", tags=["WebSocket"])


# ─── Startup ─────────────────────────────────────────────────────────────────
@app.on_event("startup")
def startup_event():
    db = SessionLocal()
    try:
        # Load from PersonPhoto table (multi-photo)
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

        print(f"[RecoFace] {len(face_service.known_encodings)} face encoding(s) carregado(s).")
    finally:
        db.close()


@app.get("/")
def root():
    return {"app": "RecoFace", "version": "1.0.0", "status": "online"}
