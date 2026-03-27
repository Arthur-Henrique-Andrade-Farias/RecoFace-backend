import os
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from sqlalchemy.orm import joinedload

from database import engine, Base, SessionLocal
import models
from routers import auth_router, cameras_router, persons_router, logs_router, ws_router, categories_router, fields_router
from face_service import face_service

# ─── DB Init ─────────────────────────────────────────────────────────────────
Base.metadata.create_all(bind=engine)

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

app.mount("/uploads", StaticFiles(directory="uploads"), name="uploads")

# ─── Routers ─────────────────────────────────────────────────────────────────
app.include_router(auth_router.router, prefix="/api/auth", tags=["Autenticação"])
app.include_router(cameras_router.router, prefix="/api/cameras", tags=["Câmeras"])
app.include_router(persons_router.router, prefix="/api/persons", tags=["Pessoas"])
app.include_router(logs_router.router, prefix="/api/logs", tags=["Logs"])
app.include_router(categories_router.router, prefix="/api/categories", tags=["Categorias"])
app.include_router(fields_router.router, prefix="/api/fields", tags=["Campos"])
app.include_router(ws_router.router, prefix="/ws", tags=["WebSocket"])


# ─── Startup ─────────────────────────────────────────────────────────────────
@app.on_event("startup")
def startup_event():
    db = SessionLocal()
    try:
        # Load all face encodings at startup
        photos = (
            db.query(models.PersonPhoto)
            .options(joinedload(models.PersonPhoto.person))
            .filter(models.PersonPhoto.face_encoding.isnot(None))
            .all()
        )
        face_service.load_encodings_from_db(photos)

        person_ids_with_photos = {ph.person_id for ph in photos}
        q = db.query(models.Person).filter(models.Person.face_encoding.isnot(None))
        if person_ids_with_photos:
            q = q.filter(~models.Person.id.in_(person_ids_with_photos))
        face_service.load_encodings_legacy(q.all())

        print(f"[RecoFace] {len(face_service.known_encodings)} face encoding(s) carregado(s).")
    finally:
        db.close()


@app.get("/")
def root():
    return {"app": "RecoFace", "version": "1.0.0", "status": "online"}
