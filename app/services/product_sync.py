import time
from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import Session

from app.config import settings
from app.core.logging import get_logger
from app.models.db_models import SyncMapping
from app.services.odoo_client import get_odoo_client
from app.services.woocommerce_client import get_woocommerce_client

logger = get_logger(__name__)


def _attach_taxonomies(odoo, woo, product_rec: dict, woo_payload: dict) -> None:
    categ_ids = product_rec.get("public_categ_ids")
    if categ_ids:
        try:
            all_categs = odoo.call(
                "product.public.category", "search_read",
                [],
                fields=["id", "name", "parent_id"],
                context={"lang": "es_GT"}
            )
            categ_map = {c["id"]: c for c in all_categs}
            
            cat_ids_payload = []
            for cid in categ_ids:
                path_names = []
                current_id = cid
                
                while current_id and current_id in categ_map:
                    node = categ_map[current_id]
                    path_names.insert(0, node["name"].strip())
                    
                    parent = node.get("parent_id")
                    if parent and isinstance(parent, list):
                        current_id = parent[0]
                    else:
                        current_id = None
                        
                if path_names:
                    woo_cat_ids = woo.get_or_create_hierarchical_category(path_names)
                    for w_cid in woo_cat_ids:
                        if not any(c.get("id") == w_cid for c in cat_ids_payload):
                            cat_ids_payload.append({"id": w_cid})
                        
            if cat_ids_payload:
                woo_payload["categories"] = cat_ids_payload
        except Exception as e:
            logger.warning("No se pudieron cargar las categorías web jerárquicas: %s", e)

    tag_ids = product_rec.get("product_tag_ids")
    if tag_ids:
        try:
            tags = odoo.call(
                "product.tag", "search_read",
                [["id", "in", tag_ids]],
                fields=["name"],
                context={"lang": "es_GT"}
            )
            t_ids = []
            for t in tags:
                t_id = woo.get_or_create_tag_id(t["name"])
                if t_id:
                    t_ids.append({"id": t_id})
            if t_ids:
                woo_payload["tags"] = t_ids
        except Exception as e:
            logger.warning("No se pudieron cargar las etiquetas: %s", e)


def _odoo_product_to_woo_payload(odoo, woo, product: dict) -> dict:
    sku = str(product["id"])
    
    website_desc = product.get("website_description") or product.get("description_ecommerce") or product.get("description") or ""
    short_desc = product.get("description_sale") or product.get("description_picking") or ""
    
    # Separamos las variables:
    is_active = product.get("active", True)          # Controla Archivado vs Activo
    is_published = product.get("is_published", True) # Controla Publicado vs No Publicado
    
    payload = {
        "name": product["name"],
        "sku": sku,
        "regular_price": str(product.get("list_price", 0)),
        "manage_stock": True,
        "stock_quantity": int(product.get("qty_available", 0)),
        "short_description": short_desc,
        "description": website_desc,
        "status": "publish" if is_active else "draft",               # Si se archiva, va a borrador
        "catalog_visibility": "visible" if is_published else "hidden", # Si no está publicado web, se oculta
    }
    
    # Si el producto se archiva (borrador), omitimos la imagen para evitar el error 404 del endpoint de Odoo
    if is_active:
        images = []
        if product.get("image_128"):
            ts = int(time.time())
            images.append({"src": f"{settings.public_bridge_url}/products/{sku}/image.jpg?t={ts}"})
        if images:
            payload["images"] = images

    _attach_taxonomies(odoo, woo, product, payload)

    return payload


def sync_products_changed_since(db: Session, minutes: int = 15) -> int:
    odoo = get_odoo_client()
    woo = get_woocommerce_client()

    since = (datetime.now(timezone.utc) - timedelta(minutes=minutes)).strftime("%Y-%m-%d %H:%M:%S")
    products = odoo.get_products_updated_since(since)

    processed = 0
    for product in products:
        sku = str(product["id"])
        payload = _odoo_product_to_woo_payload(odoo, woo, product)
        mapping = db.query(SyncMapping).filter_by(entity_type="product", sku=sku).first()

        if mapping:
            woo.update_product(mapping.woo_id, payload)
        else:
            existing_in_woo = woo.get_product_by_sku(sku)
            if existing_in_woo:
                woo_product_id = existing_in_woo["id"]
                woo.update_product(woo_product_id, payload)
            else:
                created = woo.create_product(payload)
                if not created:
                    logger.error("No se pudo crear en WooCommerce el producto sku=%s, se omite", sku)
                    continue
                woo_product_id = created["id"]

            db.add(SyncMapping(
                entity_type="product",
                woo_id=woo_product_id,
                odoo_id=product["id"],
                sku=sku,
            ))
            db.commit()

        processed += 1

    logger.info("Sync de productos: %s productos procesados", processed)
    return processed


def handle_odoo_product_event(db: Session, payload: dict) -> None:
    event = payload.get("event")
    sku = payload.get("sku")

    if not sku:
        logger.warning("Evento de producto sin SKU, se ignora: %s", payload)
        return

    woo = get_woocommerce_client()
    odoo = get_odoo_client()
    mapping = db.query(SyncMapping).filter_by(entity_type="product", sku=sku).first()

    if event == "deleted":
        if mapping:
            woo.delete_product(mapping.woo_id, force=True)
            db.delete(mapping)
            db.commit()
        else:
            logger.info("Producto sku=%s eliminado en Odoo pero no tenía mapeo en Woo, nada que hacer", sku)
        return

    odoo_id = payload.get("odoo_id")
    product_rec = {}
    if odoo_id:
        try:
            odoo_records = odoo.call(
                "product.product", "search_read",
                [["id", "=", odoo_id]],
                fields=[
                    "name", "list_price", "qty_available", "description_sale",
                    "description_picking", "website_description", "description_ecommerce",
                    "description", "is_published", "active", "public_categ_ids",
                    "product_tag_ids", "image_128"
                ],
                limit=1,
                context={"lang": "es_GT", "active_test": False}
            )
            if odoo_records:
                product_rec = odoo_records[0]
                payload["website_description"] = product_rec.get("website_description") or product_rec.get("description_ecommerce") or product_rec.get("description") or ""
                payload["description_sale"] = product_rec.get("description_sale") or product_rec.get("description_picking") or ""
        except Exception as e:
            logger.warning("No se pudo obtener la data extra de Odoo para sku=%s: %s", sku, e)

    # Separar lógica de Activo vs Publicado
    is_active = payload.get("active", True)
    is_published = payload.get("is_published", True)
    
    if product_rec:
        is_active = product_rec.get("active", True)
        is_published = product_rec.get("is_published", True)

    woo_payload = {
        "name": payload.get("name", ""),
        "sku": sku,
        "regular_price": str(payload.get("list_price", 0)),
        "manage_stock": True,
        "stock_quantity": int(payload.get("qty_available", 0)),
        "short_description": payload.get("description_sale") or "",
        "description": payload.get("website_description") or "",
        "status": "publish" if is_active else "draft",               # Borrador si se archiva en Odoo
        "catalog_visibility": "visible" if is_published else "hidden", # Oculto si se quita el check de Publicado
    }

    sale_price = payload.get("sale_price")
    if sale_price:
        woo_payload["sale_price"] = str(sale_price)
    else:
        woo_payload["sale_price"] = ""

    # Solo intentamos actualizar las imágenes si el producto está Activo
    if is_active:
        images = []
        ts = int(time.time())
        
        if payload.get("has_image"):
            images.append({"src": f"{settings.public_bridge_url}/products/{sku}/image.jpg?t={ts}"})
        for image_id in payload.get("extra_image_ids", []):
            images.append({"src": f"{settings.public_bridge_url}/products/image/{image_id}.jpg?t={ts}"})
            
        if images:
            woo_payload["images"] = images

    if product_rec:
        _attach_taxonomies(odoo, woo, product_rec, woo_payload)

    if mapping:
        woo.update_product(mapping.woo_id, woo_payload)
        mapping.odoo_id = payload.get("odoo_id", mapping.odoo_id)
    else:
        existing = woo.get_product_by_sku(sku)
        if existing:
            woo.update_product(existing["id"], woo_payload)
            woo_product_id = existing["id"]
        else:
            created = woo.create_product(woo_payload)
            if not created:
                logger.error("No se pudo crear en WooCommerce el producto sku=%s, se aborta este evento", sku)
                return
            woo_product_id = created["id"]

        db.add(SyncMapping(
            entity_type="product",
            woo_id=woo_product_id,
            odoo_id=payload.get("odoo_id", 0),
            sku=sku,
        ))

    db.commit()
    logger.info("Evento '%s' de producto sku=%s procesado hacia WooCommerce", event, sku)


def full_import_products(db: Session) -> int:
    odoo = get_odoo_client()
    woo = get_woocommerce_client()
    
    all_products = odoo.call(
        "product.product",
        "search_read",
        [["sale_ok", "=", True]],
        context={"lang": "es_GT", "active_test": False}
    )

    processed = 0
    for product in all_products:
        sku = str(product["id"])
        payload = _odoo_product_to_woo_payload(odoo, woo, product)
        existing = woo.get_product_by_sku(sku)

        if existing:
            woo.update_product(existing["id"], payload)
            woo_product_id = existing["id"]
        else:
            created = woo.create_product(payload)
            if not created:
                logger.error("No se pudo crear en WooCommerce el producto sku=%s, se omite", sku)
                continue
            woo_product_id = created["id"]

        mapping = db.query(SyncMapping).filter_by(entity_type="product", sku=sku).first()
        if mapping:
            mapping.odoo_id = product["id"]
            mapping.woo_id = woo_product_id
        else:
            db.add(SyncMapping(
                entity_type="product", woo_id=woo_product_id, odoo_id=product["id"], sku=sku,
            ))
        db.commit()
        processed += 1

    logger.info("Importación inicial de productos completa: %s productos", processed)
    return processed