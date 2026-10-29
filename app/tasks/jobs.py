from app.core.logging import get_logger
from app.db.session import SessionLocal
from app.services.customer_sync import sync_customer_from_payload
from app.services.order_sync import sync_order_from_payload
from app.services.product_sync import handle_odoo_product_event, sync_products_changed_since

# Importación correcta apuntando a woocommerce_client (sin el _2)
from app.models.db_models import SyncMapping
from app.services.woocommerce_client import get_woocommerce_client

logger = get_logger(__name__)


def process_order_webhook(payload: dict) -> None:
    db = SessionLocal()
    try:
        sync_order_from_payload(db, payload)
    except Exception:
        logger.exception("Error procesando webhook de pedido woo id=%s", payload.get("id"))
        raise
    finally:
        db.close()


def process_customer_webhook(payload: dict) -> None:
    db = SessionLocal()
    try:
        sync_customer_from_payload(db, payload)
    except Exception:
        logger.exception("Error procesando webhook de cliente woo id=%s", payload.get("id"))
        raise
    finally:
        db.close()


def run_product_sync(minutes: int = 15) -> None:
    db = SessionLocal()
    try:
        sync_products_changed_since(db, minutes=minutes)
    except Exception:
        logger.exception("Error corriendo el sync periódico de productos")
        raise
    finally:
        db.close()


def process_odoo_product_event(payload: dict) -> None:
    db = SessionLocal()
    try:
        handle_odoo_product_event(db, payload)
    except Exception:
        logger.exception("Error procesando evento de producto de Odoo: %s", payload)
        raise
    finally:
        db.close()


def process_odoo_order_status(payload: dict) -> None:
    db = SessionLocal()
    try:
        odoo_order_id = payload.get("odoo_order_id")
        action = payload.get("action")

        if not odoo_order_id:
            sale_id = payload.get("sale_id")
            if isinstance(sale_id, list) and len(sale_id) > 0:
                odoo_order_id = sale_id[0]
            elif isinstance(sale_id, int):
                odoo_order_id = sale_id
            else:
                odoo_order_id = payload.get("id")

        if not action:
            state = payload.get("state")
            if state == "done":
                action = "completed"
            elif state == "cancel":
                action = "cancelled"
            else:
                action = "completed"

        if not odoo_order_id:
            logger.warning("No se pudo identificar el odoo_order_id en el payload: %s", payload)
            return

        mapping = db.query(SyncMapping).filter_by(entity_type="order", odoo_id=odoo_order_id).first()
        if not mapping:
            logger.warning("Orden Odoo id=%s ignorada (no proviene de WooCommerce o no está mapeada)", odoo_order_id)
            return

        woo_id = mapping.woo_id
        woo = get_woocommerce_client()

        woo_payload = {"status": action}
        updated_order = woo.update_order(woo_id, woo_payload) 
        
        if updated_order:
            logger.info("Pedido Woo id=%s actualizado exitosamente a estado: %s", woo_id, action)
        else:
            logger.error("Error actualizando estado del pedido Woo id=%s", woo_id)
            
    except Exception:
        logger.exception("Error procesando actualización de estado de Odoo para payload: %s", payload)
        raise
    finally:
        db.close()