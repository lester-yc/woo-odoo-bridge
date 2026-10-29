from fastapi import APIRouter, Header, HTTPException, Request

from app.core.logging import get_logger
from app.core.security import verify_woo_signature
from app.tasks.jobs import process_customer_webhook, process_order_webhook
from app.tasks.worker import queue

router = APIRouter(prefix="/webhooks/woocommerce", tags=["woocommerce"])
logger = get_logger(__name__)


async def _validated_payload(request: Request, x_wc_webhook_signature: str | None) -> dict | None:
    raw_body = await request.body()

    # WooCommerce, al guardar/activar un webhook, manda un "ping" de prueba
    # (WC_Webhook::deliver_ping) con body="webhook_id=N" y SIN firma, a propósito.
    # No trae datos sensibles, así que lo aceptamos sin exigir HMAC.
    if not x_wc_webhook_signature and raw_body.startswith(b"webhook_id="):
        logger.info("Ping de prueba de WooCommerce recibido (sin firma, es normal)")
        return None

    if not verify_woo_signature(raw_body, x_wc_webhook_signature):
        logger.warning("Firma de webhook inválida, request rechazado")
        raise HTTPException(status_code=401, detail="Firma inválida")

    return await request.json()


@router.post("/orders")
async def woocommerce_order_webhook(
    request: Request,
    x_wc_webhook_signature: str | None = Header(default=None),
):
    payload = await _validated_payload(request, x_wc_webhook_signature)
    if payload is None:
        return {"status": "ping_ok"}

    # Responde rápido y deja el trabajo pesado al worker
    queue.enqueue(process_order_webhook, payload)
    logger.info("Webhook de pedido encolado: woo id=%s", payload.get("id"))

    return {"status": "queued"}


@router.post("/customers")
async def woocommerce_customer_webhook(
    request: Request,
    x_wc_webhook_signature: str | None = Header(default=None),
):
    payload = await _validated_payload(request, x_wc_webhook_signature)
    if payload is None:
        return {"status": "ping_ok"}

    queue.enqueue(process_customer_webhook, payload)
    logger.info("Webhook de cliente encolado: woo id=%s", payload.get("id"))

    return {"status": "queued"}
