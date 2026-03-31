from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from sqlalchemy import func, and_, cast, Date
from typing import Optional
from datetime import date, datetime, timedelta
from database import get_db
import models
import auth

router = APIRouter()


@router.get("/daily")
def daily_report(
    report_date: date = Query(..., description="Data do relatório (YYYY-MM-DD)"),
    camera_id: Optional[int] = None,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth.require_manager),
):
    oid = current_user.org_id
    day_start = datetime.combine(report_date, datetime.min.time())
    day_end = datetime.combine(report_date + timedelta(days=1), datetime.min.time())

    # Base query: logs for this org on this date
    base = db.query(models.RecognitionLog).filter(
        models.RecognitionLog.org_id == oid,
        models.RecognitionLog.timestamp >= day_start,
        models.RecognitionLog.timestamp < day_end,
    )

    # Camera filter
    camera_info = None
    if camera_id:
        cam = db.query(models.Camera).filter(
            models.Camera.id == camera_id,
            models.Camera.org_id == oid,
        ).first()
        if not cam:
            raise HTTPException(status_code=404, detail="Câmera não encontrada")
        base = base.filter(models.RecognitionLog.camera_id == camera_id)
        camera_info = {"id": cam.id, "name": cam.name, "location": cam.location}

    logs = base.order_by(models.RecognitionLog.timestamp.asc()).all()

    # Summary
    total = len(logs)
    recognized_logs = [l for l in logs if l.recognized]
    unrecognized_logs = [l for l in logs if not l.recognized]
    authorized_logs = [l for l in logs if l.is_authorized]

    # Unique persons seen
    person_ids_seen = set()
    persons_data = {}
    for log in logs:
        if log.person_id and log.recognized:
            person_ids_seen.add(log.person_id)
            if log.person_id not in persons_data:
                persons_data[log.person_id] = {
                    "person_id": log.person_id,
                    "name": log.person.name if log.person else "—",
                    "role": log.person.role if log.person else "—",
                    "is_authorized": log.person.is_authorized if log.person else False,
                    "first_seen": log.timestamp.strftime("%H:%M:%S"),
                    "last_seen": log.timestamp.strftime("%H:%M:%S"),
                    "detection_count": 0,
                    "avg_confidence": 0.0,
                    "total_confidence": 0.0,
                }
            pd = persons_data[log.person_id]
            pd["last_seen"] = log.timestamp.strftime("%H:%M:%S")
            pd["detection_count"] += 1
            pd["total_confidence"] += (log.confidence or 0)

    # Calculate averages
    persons_seen = []
    for pd in persons_data.values():
        if pd["detection_count"] > 0:
            pd["avg_confidence"] = round(pd["total_confidence"] / pd["detection_count"], 1)
        del pd["total_confidence"]
        persons_seen.append(pd)
    persons_seen.sort(key=lambda p: p["first_seen"])

    # Unrecognized events
    unrecognized_events = []
    for log in unrecognized_logs:
        unrecognized_events.append({
            "id": log.id,
            "timestamp": log.timestamp.strftime("%H:%M:%S"),
            "photo_path": log.photo_path,
            "camera_name": log.camera.name if log.camera else None,
            "notes": log.notes,
        })

    # Hourly breakdown
    hourly = {}
    for h in range(24):
        hourly[h] = {"hour": h, "total": 0, "recognized": 0, "unrecognized": 0}
    for log in logs:
        h = log.timestamp.hour
        hourly[h]["total"] += 1
        if log.recognized:
            hourly[h]["recognized"] += 1
        else:
            hourly[h]["unrecognized"] += 1
    # Only return hours that have data
    hourly_breakdown = [v for v in hourly.values() if v["total"] > 0]

    # All cameras active that day (for the selector)
    cameras_active = (
        db.query(models.Camera.id, models.Camera.name)
        .filter(models.Camera.org_id == oid)
        .order_by(models.Camera.name)
        .all()
    )

    return {
        "date": report_date.isoformat(),
        "camera": camera_info,
        "cameras_available": [{"id": c.id, "name": c.name} for c in cameras_active],
        "summary": {
            "total_detections": total,
            "unique_persons": len(person_ids_seen),
            "recognized": len(recognized_logs),
            "unrecognized": len(unrecognized_logs),
            "authorized": len(authorized_logs),
            "unauthorized": len(recognized_logs) - len(authorized_logs),
        },
        "persons_seen": persons_seen,
        "unrecognized_events": unrecognized_events,
        "hourly_breakdown": hourly_breakdown,
    }
