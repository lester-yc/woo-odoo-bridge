from sqlalchemy.orm import Session

from app.core.logging import get_logger
from app.models.db_models import SyncMapping
from app.services.customer_sync import _upsert_mapping, sync_customer_from_payload
from app.services.odoo_client import get_odoo_client

logger = get_logger(__name__)

# --- Escenarios de Estados (Reglas de Negocio) ---
ESTADOS_CONFIRMAR_Y_DESCONTAR = {"processing", "completed"} # Pago asegurado o contra entrega
ESTADOS_SOLO_CONFIRMAR = {"on-hold"} # Transferencia/Cheque (Requiere validación)
ESTADOS_CANCELAR = {"cancelled", "refunded", "failed"}


def sync_order_from_payload(db: Session, payload: dict) -> int | None:
    status = payload.get("status")
    woo_order_id = payload.get("id")
    odoo = get_odoo_client()

    existing = db.query(SyncMapping).filter_by(entity_type="order", woo_id=woo_order_id).first()

    if status in ESTADOS_CANCELAR:
        return _handle_cancel(odoo, existing, woo_order_id, status)

    # Si no es un estado procesable, lo ignoramos
    if status not in ESTADOS_CONFIRMAR_Y_DESCONTAR and status not in ESTADOS_SOLO_CONFIRMAR:
        logger.info("Pedido woo id=%s en estado '%s', ignorado.", woo_order_id, status)
        return None

    # Si ya existe en Odoo, actualizamos la nota visual y evaluamos el stock
    if existing:
        nueva_nota = _build_payment_note(payload)
        try:
            odoo.call("sale.order", "write", [existing.odoo_id], {"note": nueva_nota})
            logger.info("Nota de pago actualizada para el pedido odoo id=%s", existing.odoo_id)
        except Exception as e:
            logger.warning("No se pudo actualizar la nota de pago en la orden: %s", e)
            
        _process_order_state(odoo, existing.odoo_id, woo_order_id, status)
        return existing.odoo_id

    # 1. Crear o actualizar Cliente con todos los datos
    partner_id = sync_customer_from_payload(db, payload)
    
    # 2. Construir líneas de la orden
    order_lines = _build_order_lines(odoo, payload, woo_order_id)

    if not order_lines:
        logger.error("Pedido woo id=%s no tiene líneas válidas, no se crea en Odoo", woo_order_id)
        return None

    # 3. Construir nota inicial de información de pago y advertencias
    nota_pago = _build_payment_note(payload)

    # 4. Crear la Cotización en Odoo
    odoo_order_id = odoo.create_sale_order(
        partner_id=partner_id,
        order_lines=order_lines,
        woo_order_ref=f"WOO-{woo_order_id}",
    )
    _upsert_mapping(db, "order", woo_order_id, odoo_order_id)

    # Inyectar la nota de pago inicial
    try:
        odoo.call("sale.order", "write", [odoo_order_id], {"note": nota_pago})
    except Exception as e:
        logger.warning("No se pudo guardar la nota de pago inicial en la orden: %s", e)

    # 5. Procesar la confirmación y el inventario según el estado del pedido
    _process_order_state(odoo, odoo_order_id, woo_order_id, status)

    return odoo_order_id


def _build_payment_note(payload: dict) -> str:
    """Genera la nota visible para el administrador en Odoo con base en el pago"""
    method_title = payload.get("payment_method_title", "No especificado")
    transaction_id = payload.get("transaction_id", "")
    status = payload.get("status")
    
    nota = f"MÉTODO DE PAGO WOOCOMMERCE: {method_title}\n"
    if transaction_id:
        nota += f"ID Transacción: {transaction_id}\n"
        
    if status == "on-hold":
        nota += "\n⚠️ ATENCIÓN: Pedido en espera de validación de pago (Transferencia/Cheque). Favor confirmar depósito bancario antes de despachar."
    elif status == "processing":
        nota += "\n✅ Pago verificado o Contra Reembolso. Listo para despachar."
        
    return nota


def _build_order_lines(odoo, payload: dict, woo_order_id: int) -> list[dict]:
    order_lines = []
    
    for item in payload.get("line_items", []):
        sku = item.get("sku")
        odoo_product_id = odoo.find_product_by_sku(sku) if sku else None

        if not odoo_product_id:
            logger.warning("SKU '%s' del pedido woo id=%s no existe en Odoo", sku, woo_order_id)
            continue

        order_lines.append({
            "product_id": odoo_product_id,
            "product_uom_qty": item.get("quantity", 1),
            "price_unit": float(item.get("price", 0)),
        })
        
    shipping_total = float(payload.get("shipping_total", 0.0))
    if shipping_total > 0:
        order_lines.append({
            "name": "Costo de Envío Web",
            "product_uom_qty": 1,
            "price_unit": shipping_total,
        })
        
    return order_lines


def _process_order_state(odoo, odoo_order_id: int, woo_order_id: int, status: str):
    """Ejecuta los movimientos logísticos en Odoo según el estado del pedido"""
    try:
        # 1. Leemos el estado actual de la orden en Odoo
        order_data = odoo.call("sale.order", "read", [odoo_order_id], ["state"])
        if not order_data:
            return
            
        odoo_state = order_data[0].get("state")

        # 2. Si está en borrador, la confirmamos para RESERVAR el stock
        if odoo_state in ["draft", "sent"]:
            odoo.call("sale.order", "action_confirm", [odoo_order_id])
            logger.info("Pedido odoo id=%s confirmado/reservado (woo id=%s)", odoo_order_id, woo_order_id)
        else:
            logger.info("Pedido odoo id=%s ya estaba confirmado. Avanzando a revisión de entrega...", odoo_order_id)
        
        # 3. Si el pago está asegurado, avanzamos a DESCONTAR el stock físico
        if status in ESTADOS_CONFIRMAR_Y_DESCONTAR:
            _validate_delivery(odoo, odoo_order_id)
        else:
            logger.info("Pedido odoo id=%s en on-hold. Stock reservado pero NO descontado.", odoo_order_id)
            
    except Exception:
        logger.exception("Error procesando confirmación/stock del pedido odoo id=%s", odoo_order_id)


def _validate_delivery(odoo, order_id: int) -> None:
    """Valida el albarán de entrega para descontar físicamente el inventario"""
    try:
        picking_ids = odoo.call("stock.picking", "search", [
            ("sale_id", "=", order_id), ("state", "not in", ["done", "cancel"])
        ])
        
        if not picking_ids:
            return  # Probablemente ya fue entregado
            
        picking_id = picking_ids[0]
        
        # Reservar
        odoo.call("stock.picking", "action_assign", [picking_id])
        
        # Emparejar cantidad demandada con cantidad entregada
        move_ids = odoo.call("stock.move", "search", [("picking_id", "=", picking_id)])
        for move_id in move_ids:
            move_data = odoo.call("stock.move", "read", [move_id], ["product_uom_qty"])[0]
            odoo.call("stock.move", "write", [move_id], {"quantity": move_data["product_uom_qty"]})
            
        # Validar (Descuenta Stock)
        odoo.call("stock.picking", "button_validate", [picking_id])
        logger.info("Stock descontado exitosamente para la orden odoo id=%s", order_id)
        
    except Exception:
        logger.exception("No se pudo descontar automáticamente el stock de odoo id=%s", order_id)


def _handle_cancel(odoo, existing: SyncMapping | None, woo_order_id: int, status: str) -> int | None:
    if not existing:
        return None

    try:
        odoo.call("sale.order", "action_cancel", [existing.odoo_id])
        logger.info("Venta odoo id=%s cancelada por estado woo '%s'", existing.odoo_id, status)
    except Exception:
        logger.exception("No se pudo cancelar automáticamente la venta odoo id=%s", existing.odoo_id)

    return existing.odoo_id