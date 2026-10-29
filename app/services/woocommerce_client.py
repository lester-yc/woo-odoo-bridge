import requests

from app.config import settings
from app.core.logging import get_logger

logger = get_logger(__name__)


class WooCommerceClient:
    """
    Cliente sobre requests utilizando autenticación HTTP Basic explícita.
    """

    def __init__(self):
        self.base_url = f"{settings.wc_url.rstrip('/')}/wp-json/wc/v3"
        self.auth = (settings.wc_consumer_key, settings.wc_consumer_secret)
        self.timeout = 120

    def _log_error(self, action: str, resp: requests.Response) -> None:
        try:
            detail = resp.json()
        except ValueError:
            detail = resp.text[:300]
        logger.error("WooCommerce devolvió un error en %s (status=%s): %s", action, resp.status_code, detail)

    def get_product_by_sku(self, sku: str) -> dict | None:
        resp = requests.get(
            f"{self.base_url}/products", auth=self.auth, params={"sku": sku}, timeout=self.timeout,
        )
        if resp.status_code != 200:
            self._log_error("get_product_by_sku", resp)
            return None

        data = resp.json()
        return data[0] if data else None

    def create_product(self, payload: dict) -> dict | None:
        resp = requests.post(
            f"{self.base_url}/products", auth=self.auth, json=payload, timeout=self.timeout,
        )
        if resp.status_code not in (200, 201):
            self._log_error("create_product", resp)
            return None

        data = resp.json()
        logger.info("Producto creado en WooCommerce: id=%s sku=%s", data.get("id"), payload.get("sku"))
        return data

    def update_product(self, woo_product_id: int, payload: dict) -> dict | None:
        resp = requests.put(
            f"{self.base_url}/products/{woo_product_id}", auth=self.auth, json=payload, timeout=self.timeout,
        )
        if resp.status_code != 200:
            self._log_error("update_product", resp)
            return None

        logger.info("Producto actualizado en WooCommerce: id=%s", woo_product_id)
        return resp.json()

    def delete_product(self, woo_product_id: int, force: bool = True) -> dict | None:
        resp = requests.delete(
            f"{self.base_url}/products/{woo_product_id}", auth=self.auth,
            params={"force": force}, timeout=self.timeout,
        )
        if resp.status_code != 200:
            self._log_error("delete_product", resp)
            return None

        logger.info("Producto eliminado en WooCommerce: id=%s (force=%s)", woo_product_id, force)
        return resp.json()

    def batch_update_products(self, updates: list[dict]) -> dict | None:
        resp = requests.post(
            f"{self.base_url}/products/batch", auth=self.auth,
            json={"update": updates}, timeout=self.timeout,
        )
        if resp.status_code != 200:
            self._log_error("batch_update_products", resp)
            return None

        return resp.json()

    # --- NUEVO MÉTODO PARA ACTUALIZAR PEDIDOS USANDO BASIC AUTH ---
    def update_order(self, woo_order_id: int, payload: dict) -> dict | None:
        """Actualiza el estado u otros campos de un pedido en WooCommerce usando Basic Auth."""
        resp = requests.put(
            f"{self.base_url}/orders/{woo_order_id}", auth=self.auth, json=payload, timeout=self.timeout,
        )
        if resp.status_code != 200:
            self._log_error("update_order", resp)
            return None

        logger.info("Pedido actualizado en WooCommerce: id=%s", woo_order_id)
        return resp.json()

    def _find_or_create_taxonomy_term(self, endpoint: str, name: str) -> int | None:
        resp = requests.get(
            f"{self.base_url}/{endpoint}", auth=self.auth,
            params={"search": name, "per_page": 20}, timeout=self.timeout,
        )
        if resp.status_code == 200:
            for term in resp.json():
                if term.get("name", "").strip().lower() == name.strip().lower():
                    return term["id"]
        else:
            self._log_error(f"buscar término en {endpoint}", resp)

        resp = requests.post(
            f"{self.base_url}/{endpoint}", auth=self.auth,
            json={"name": name}, timeout=self.timeout,
        )
        if resp.status_code not in (200, 201):
            self._log_error(f"crear término en {endpoint}", resp)
            return None
        return resp.json().get("id")

    def get_or_create_category_id(self, name: str) -> int | None:
        return self._find_or_create_taxonomy_term("products/categories", name)

    def get_or_create_hierarchical_category(self, category_names: list[str]) -> list[int]:
        parent_id = 0
        current_id = None
        ids_in_path = []
        
        for name in category_names:
            name = name.strip()
            if not name:
                continue
            
            resp = requests.get(
                f"{self.base_url}/products/categories", auth=self.auth,
                params={"search": name, "per_page": 50}, timeout=self.timeout,
            )
            
            found_id = None
            if resp.status_code == 200:
                for term in resp.json():
                    if term.get("name", "").strip().lower() == name.lower() and term.get("parent") == parent_id:
                        found_id = term["id"]
                        break
            
            if found_id:
                current_id = found_id
            else:
                resp_post = requests.post(
                    f"{self.base_url}/products/categories", auth=self.auth,
                    json={"name": name, "parent": parent_id}, timeout=self.timeout,
                )
                if resp_post.status_code not in (200, 201):
                    self._log_error(f"crear categoría jerárquica '{name}'", resp_post)
                    return ids_in_path
                current_id = resp_post.json().get("id")
            
            parent_id = current_id
            if current_id:
                ids_in_path.append(current_id)
            
        return ids_in_path

    def get_or_create_tag_id(self, name: str) -> int | None:
        return self._find_or_create_taxonomy_term("products/tags", name)


_client: WooCommerceClient | None = None


def get_woocommerce_client() -> WooCommerceClient:
    global _client
    if _client is None:
        _client = WooCommerceClient()
    return _clien