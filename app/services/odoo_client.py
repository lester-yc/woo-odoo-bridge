import xmlrpc.client
import base64
from typing import Any

from app.config import settings
from app.core.logging import get_logger

logger = get_logger(__name__)


class OdooClient:
    def __init__(self):
        self.url = settings.odoo_url
        self.db = settings.odoo_db
        self.user = settings.odoo_user
        self.password = settings.odoo_password

        self._common = xmlrpc.client.ServerProxy(f"{self.url}/xmlrpc/2/common")
        self._models = xmlrpc.client.ServerProxy(f"{self.url}/xmlrpc/2/object")
        self.uid = self._common.authenticate(self.db, self.user, self.password, {})

        if not self.uid:
            raise RuntimeError("No se pudo autenticar contra Odoo. Revisa ODOO_DB/USER/PASSWORD.")

    def call(self, model: str, method: str, *args, **kwargs) -> Any:
        return self._models.execute_kw(
            self.db, self.uid, self.password, model, method, list(args), kwargs
        )

    # ---------- Clientes ----------

    def find_or_create_partner(self, email: str, name: str, extra: dict | None = None) -> int:
        extra = extra or {}
        ids = self.call("res.partner", "search", [["email", "=", email]], limit=1)
        if ids:
            partner_id = ids[0]
            if extra:
                self.call("res.partner", "write", [partner_id], extra)
            return partner_id

        payload = {"name": name, "email": email, **extra}
        return self.call("res.partner", "create", payload)

    # ---------- Productos ----------

    def find_product_by_sku(self, sku: str) -> int | None:
        """
        El SKU de WooCommerce es, por diseño, el ID de Odoo (ver odoo_woo_bridge).
        Si viene numérico, se busca directo por ID. Si no (productos migrados del
        esquema anterior, con código manual), se cae a buscar por default_code.
        """
        if not sku:
            return None

        if sku.isdigit():
            ids = self.call("product.product", "search", [["id", "=", int(sku)]], limit=1)
            if ids:
                return ids[0]

        ids = self.call("product.product", "search", [["default_code", "=", sku]], limit=1)
        return ids[0] if ids else None

    def get_product_image(self, sku: str) -> bytes | None:
        """Trae la imagen (image_1920, la de mayor resolución) de un producto por su SKU."""
        if not sku:
            return None
            
        # Si el sku es numérico (el ID de Odoo), busca por id; si no, por default_code
        domain = [["id", "=", int(sku)]] if sku.isdigit() else [["default_code", "=", sku]]
        
        results = self.call(
            "product.product", "search_read",
            domain, fields=["image_1920"], limit=1,
        )
        if not results or not results[0].get("image_1920"):
            return None
        return base64.b64decode(results[0]["image_1920"])

    def get_extra_image(self, image_id: int):
        """
        Obtiene la imagen binaria de la galería adicional del producto 
        desde el modelo product.image en Odoo.
        """
        import base64
        try:
            domain = [["id", "=", int(image_id)]]
            records = self.call("product.image", "search_read", domain, fields=["image_1920"], limit=1)
            if records and records[0].get("image_1920"):
                return base64.b64decode(records[0]["image_1920"])
        except Exception as e:
            pass
        return None

    def get_products_updated_since(self, since_iso: str) -> list[dict]:
        domain = [["write_date", ">", since_iso]]
        fields = [
            "id", "default_code", "name", "list_price",
            "qty_available", "description_sale", "write_date", "image_128",
            "public_categ_ids",           # Categorías de eCommerce (Ventas)
            "product_tag_ids",            # Etiquetas
            "website_description",        # Descripción larga
            "product_template_image_ids", # Galería de imágenes
            "is_published"                # Estado publicado en sitio web
        ]
        return self.call("product.product", "search_read", domain, fields=fields)

    # ---------- Pedidos ----------

    def create_sale_order(self, partner_id: int, order_lines: list[dict], woo_order_ref: str) -> int:
        lines = [(0, 0, line) for line in order_lines]
        order_id = self.call(
            "sale.order",
            "create",
            {
                "partner_id": partner_id,
                "client_order_ref": woo_order_ref,
                "order_line": lines,
            },
        )
        logger.info("Pedido creado en Odoo: sale.order id=%s (woo ref=%s)", order_id, woo_order_ref)
        return order_id


_client: OdooClient | None = None


def get_odoo_client() -> OdooClient:
    global _client
    if _client is None:
        _client = OdooClient()
    return _client