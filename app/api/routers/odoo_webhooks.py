from fastapi import APIRouter, Header, HTTPException, Request

from app.config import settings
from app.core.logging import get_logger
from app.tasks.jobs import process_odoo_product_event, process_odoo_order_status
from app.tasks.worker import queue

router = APIRouter(prefix="/webhooks/odoo", tags=["odoo"])
logger = get_logger(__name__)

@router.post("/products")
async def odoo_product_event(
    request: Request,
    x_bridge_token: str | None = Header(default=None),
):
    if not x_bridge_token or x_bridge_token != settings.odoo_bridge_token:
        logger.warning("Token de bridge inválido en aviso de producto de Odoo")
        raise HTTPException(status_code=401, detail="Token inválido")

    payload = await request.json()
    queue.enqueue(process_odoo_product_event, payload)
    logger.info(
        "Evento de producto de Odoo encolado: event=%s sku=%s",
        payload.get("event"), payload.get("sku"),
    )

    return {"status": "queued"}


# --- Endpoint para escuchar cambios en los pedidos (Flexible) ---
@router.post("/orders/status")
async def odoo_order_event(
    request: Request,
    x_bridge_token: str | None = Header(default=None),
):
    if x_bridge_token and x_bridge_token != settings.odoo_bridge_token:
        logger.warning("Token de bridge inválido en aviso de pedido de Odoo")
        raise HTTPException(status_code=401, detail="Token inválido")

    payload = await request.json()
    queue.enqueue(process_odoo_order_status, payload)
    logger.info("Evento de pedido de Odoo encolado: payload=%s", payload)

    return {"status": "queued"}