import unicodedata
from sqlalchemy.orm import Session

from app.core.logging import get_logger
from app.models.db_models import SyncMapping
from app.services.odoo_client import get_odoo_client

logger = get_logger(__name__)


def normalize_str(text: str) -> str:
    """Normaliza un texto eliminando tildes, convirtiendo a minúsculas y limpiando espacios."""
    if not text:
        return ""
    return ''.join(
        c for c in unicodedata.normalize('NFD', str(text))
        if unicodedata.category(c) != 'Mn'
    ).lower().strip()


def sync_customer_from_payload(db: Session, payload: dict) -> int:
    email = payload.get("email") or payload.get("billing", {}).get("email")
    if not email:
        raise ValueError("El payload no trae email, no se puede mapear a un cliente en Odoo")

    billing = payload.get("billing", {})
    first_name = payload.get("first_name") or billing.get("first_name", "")
    last_name = payload.get("last_name") or billing.get("last_name", "")
    name = f"{first_name} {last_name}".strip() or email

    partner_data = {
        "name": name,
        "email": email,
        "customer_rank": 1, 
    }
    
    if billing.get("phone"):
        partner_data["phone"] = billing["phone"]
    if billing.get("address_1"):
        partner_data["street"] = billing["address_1"]
    if billing.get("address_2"):
        partner_data["street2"] = billing["address_2"]
    if billing.get("city"):
        partner_data["city"] = billing["city"]
    if billing.get("postcode"):
        partner_data["zip"] = billing["postcode"]

    odoo = get_odoo_client()

    # --- 1. Resolver y fijar el País base ---
    country_code = billing.get("country")
    target_country_id = None
    if country_code:
        try:
            country_ids = odoo.call("res.country", "search", [("code", "=", country_code)], limit=1)
            if country_ids:
                target_country_id = country_ids[0]
                partner_data["country_id"] = target_country_id
        except Exception as e:
            logger.warning("No se pudo resolver el país: %s", e)

    # --- 2. Búsqueda estricta y precisa de Estado/Departamento ---
    state_code = billing.get("state")
    logger.info("Analizando estado de facturación de WooCommerce: '%s' (País ID: %s)", state_code, target_country_id)

    if state_code and target_country_id:
        try:
            states = odoo.call(
                "res.country.state", "search_read",
                [("country_id", "=", target_country_id)],
                fields=["id", "name", "code"]
            )
            
            matched_state_id = None
            state_clean = normalize_str(state_code)
            state_no_prefix = state_clean.replace("gt-", "").replace("gt_", "")

            logger.info("Estados disponibles en Odoo: %s", [(s['code'], s['name']) for s in states])

            # Prioridad 1: Coincidencia exacta de código o nombre normalizado
            for st in states:
                st_code_clean = normalize_str(st.get("code"))
                st_name_clean = normalize_str(st.get("name"))
                st_code_no_prefix = st_code_clean.replace("gt-", "").replace("gt_", "")

                if state_no_prefix == st_code_no_prefix or state_no_prefix == st_name_clean:
                    matched_state_id = st["id"]
                    logger.info("¡Coincidencia exacta! ID=%s, Código=%s, Nombre=%s", matched_state_id, st.get("code"), st.get("name"))
                    break

            # Prioridad 2: Coincidencia por prefijo seguro (ej. abreviaturas válidas)
            if not matched_state_id and len(state_no_prefix) >= 2:
                for st in states:
                    st_code_clean = normalize_str(st.get("code"))
                    st_name_clean = normalize_str(st.get("name"))

                    if st_code_clean.startswith(state_no_prefix) or st_name_clean.startswith(state_no_prefix):
                        matched_state_id = st["id"]
                        logger.info("¡Coincidencia por prefijo! ID=%s, Código=%s, Nombre=%s", matched_state_id, st.get("code"), st.get("name"))
                        break

            if matched_state_id:
                partner_data["state_id"] = matched_state_id
            else:
                partner_data["state_id"] = False
                logger.warning("No se encontró coincidencia válida para el estado '%s'. Se limpiará el campo.", state_code)
        except Exception as e:
            logger.warning("Error al resolver el estado para el cliente: %s", e)

    # Capturar NIT desde los metadatos del pedido
    meta_data = payload.get("meta_data", [])
    for meta in meta_data:
        if meta.get("key") == "_billing_nit":
            partner_data["vat"] = meta.get("value")
            break
    
    try:
        customer_locations = odoo.call("stock.location", "search", [("usage", "=", "customer")])
        if customer_locations:
            partner_data["property_stock_customer"] = customer_locations[0]
    except Exception as e:
        logger.warning("No se pudo obtener la ubicación de clientes: %s", e)
    
    partner_ids = odoo.call("res.partner", "search", [("email", "=", email)])
    
    if partner_ids:
        partner_id = partner_ids[0]
        odoo.call("res.partner", "write", [partner_id], partner_data)
        logger.info("Cliente sincronizado (Actualizado): email=%s -> res.partner id=%s", email, partner_id)
    else:
        partner_id = odoo.call("res.partner", "create", partner_data)
        logger.info("Cliente sincronizado (Creado): email=%s -> res.partner id=%s", email, partner_id)

    woo_customer_id = payload.get("id") or payload.get("customer_id")
    if woo_customer_id:
        _upsert_mapping(db, "customer", woo_customer_id, partner_id)

    return partner_id


def _upsert_mapping(db: Session, entity_type: str, woo_id: int, odoo_id: int) -> None:
    existing = (
        db.query(SyncMapping)
        .filter_by(entity_type=entity_type, woo_id=woo_id)
        .first()
    )
    if existing:
        existing.odoo_id = odoo_id
    else:
        db.add(SyncMapping(entity_type=entity_type, woo_id=woo_id, odoo_id=odoo_id))
    db.commit()