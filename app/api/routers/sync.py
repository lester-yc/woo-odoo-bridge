from fastapi import APIRouter, Depends
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.models.db_models import SyncMapping
from app.tasks.jobs import run_product_sync
from app.tasks.worker import queue

router = APIRouter(tags=["sync"])


@router.get("/health")
def health():
    return {"status": "ok"}


@router.post("/sync/products")
def trigger_product_sync(minutes: int = 15):
    """Encola un sync incremental (productos modificados en los últimos N minutos)."""
    job = queue.enqueue(run_product_sync, minutes)
    return {"status": "queued", "job_id": job.id}


@router.get("/sync/status")
def sync_status(db: Session = Depends(get_db)):
    counts = (
        db.query(SyncMapping.entity_type, func.count(SyncMapping.id))
        .group_by(SyncMapping.entity_type)
        .all()
    )
    return {entity_type: count for entity_type, count in counts}
