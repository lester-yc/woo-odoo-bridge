from fastapi import APIRouter, HTTPException, Response

from app.core.logging import get_logger
from app.services.odoo_client import get_odoo_client

router = APIRouter(prefix="/products", tags=["products"])
logger = get_logger(__name__)


def _guess_content_type(data: bytes) -> str:
    if data[:2] == b"\xff\xd8":
        return "image/jpeg"
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        return "image/png"
    if data[:6] in (b"GIF87a", b"GIF89a"):
        return "image/gif"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    return "image/png"  # por defecto


@router.get("/{sku}/image.jpg")
def get_product_image(sku: str):
    odoo = get_odoo_client()
    image_bytes = odoo.get_product_image(sku)

    if not image_bytes:
        raise HTTPException(status_code=404, detail="Producto sin imagen o SKU no encontrado")

    return Response(content=image_bytes, media_type=_guess_content_type(image_bytes))


@router.get("/image/{image_id}.jpg")
def get_extra_product_image(image_id: int):
    odoo = get_odoo_client()
    try:
        image_bytes = odoo.get_extra_image(image_id)
    except Exception:
        logger.exception("Error trayendo imagen extra id=%s desde Odoo (¿existe el modelo product.image?)", image_id)
        raise HTTPException(status_code=404, detail="No se pudo obtener la imagen")

    if not image_bytes:
        raise HTTPException(status_code=404, detail="Imagen no encontrada")

    return Response(content=image_bytes, media_type=_guess_content_type(image_bytes))
