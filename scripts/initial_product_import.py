"""
Corre una sola vez para publicar en WooCommerce todo el catálogo que ya existe en Odoo.
Uso (desde dentro del contenedor del microservicio):
    docker compose exec microservicio python -m scripts.initial_product_import
"""
from app.core.logging import setup_logging, get_logger
from app.db.session import SessionLocal, init_db
from app.services.product_sync import full_import_products

logger = get_logger(__name__)

if __name__ == "__main__":
    setup_logging()
    init_db()
    db = SessionLocal()
    try:
        total = full_import_products(db)
        logger.info("Listo: %s productos publicados/actualizados en WooCommerce", total)
    finally:
        db.close()
