# -*- coding: utf-8 -*-
import logging
import requests

from odoo import api, models

_logger = logging.getLogger(__name__)

# Campos que, si cambian, justifican avisarle a WooCommerce
RELEVANT_FIELDS = {
    "name", "list_price", "default_code", "description_sale", "website_description",
    "active", "is_published", "categ_id", "image_1920",
}

REQUEST_TIMEOUT = 5  # segundos - no queremos bloquear una transacción de Odoo esperando al bridge


def _safe_get(obj, path, default=None):
    """
    Accede a un campo relacionado de forma defensiva (por ejemplo 'product_tmpl_id.product_tag_ids').
    Si el campo no existe en esta instalación de Odoo (versión distinta, módulo no instalado),
    devuelve el default en vez de romper toda la notificación.
    """
    try:
        current = obj
        for part in path.split("."):
            current = getattr(current, part)
        return current if current is not None else default
    except Exception:
        return default


class ProductProduct(models.Model):
    _inherit = "product.product"

    def _bridge_config(self):
        icp = self.env["ir.config_parameter"].sudo()
        url = icp.get_param("woo_bridge.url", default="")
        token = icp.get_param("woo_bridge.token", default="")
        return url, token

    def _build_snapshot(self, p):
        # Categoría: usamos solo el último tramo del nombre (Odoo las muestra como "Todas / Oficina")
        categ_name = None
        if p.categ_id:
            categ_name = p.categ_id.name

        # Etiquetas: el campo se llama distinto según versión/módulos instalados de Odoo,
        # probamos las variantes más comunes sin romper si ninguna existe.
        tags = _safe_get(p, "product_tmpl_id.product_tag_ids", [])
        if not tags:
            tags = _safe_get(p, "all_product_tag_ids", [])
        tag_names = [t.name for t in tags] if tags else []

        # Imágenes extra (galería), a nivel de plantilla de producto
        extra_images = _safe_get(p, "product_tmpl_id.product_template_image_ids", [])
        extra_image_ids = [img.id for img in extra_images] if extra_images else []

        # Lógica para extraer el Precio de Oferta adaptada para Odoo 18
        sale_price = 0.0
        pricelist = self.env["product.pricelist"].sudo().search([("name", "=", "Precio oferta")], limit=1)
        if pricelist:
            # Corrección: Se elimina el 'False' que causaba el TypeError en los argumentos posicionales
            computed_price = pricelist._get_product_price(p, 1.0)
            if computed_price < p.list_price:
                sale_price = computed_price

        return {
            "odoo_id": p.id,
            "sku": str(p.id),
            "name": p.name,
            "list_price": p.list_price,
            "sale_price": sale_price,
            "qty_available": p.qty_available,
            "description_sale": p.description_sale or "",
            "website_description": p.website_description or "",
            "active": p.active,
            "is_published": p.is_published,
            "has_image": bool(p.image_128),
            "category_name": categ_name,
            "tag_names": tag_names,
            "extra_image_ids": extra_image_ids,
        }

    def _notify_bridge(self, event, snapshot=None):
        """
        event: 'created' | 'updated' | 'deleted'
        snapshot: dict opcional con los datos ya capturados (necesario para 'deleted',
                  donde el registro ya no existe al momento de notificar).
        """
        url, token = self._bridge_config()
        if not url:
            return  # bridge no configurado todavía, no hacer nada

        records = [snapshot] if snapshot else [self._build_snapshot(p) for p in self]

        for data in records:
            if not data.get("sku"):
                _logger.info("Producto id=%s sin SKU, se omite notificación al bridge", data.get("odoo_id"))
                continue

            payload = {"event": event, **data}
            try:
                requests.post(
                    f"{url.rstrip('/')}/webhooks/odoo/products",
                    json=payload,
                    headers={"X-Bridge-Token": token},
                    timeout=REQUEST_TIMEOUT,
                )
            except Exception:
                _logger.exception(
                    "No se pudo notificar al bridge sobre el producto sku=%s (evento=%s)",
                    data.get("sku"), event,
                )

    @api.model_create_multi
    def create(self, vals_list):
        products = super().create(vals_list)
        products._notify_bridge("created")
        return products

    def write(self, vals):
        result = super().write(vals)
        if RELEVANT_FIELDS.intersection(vals.keys()):
            self._notify_bridge("updated")
        return result

    def unlink(self):
        # Capturamos los datos ANTES de borrar, porque después del unlink
        # el recordset ya no tiene campos que leer.
        snapshots = [
            {
                "odoo_id": p.id,
                "sku": str(p.id),
                "name": p.name,
            }
            for p in self
        ]
        result = super().unlink()
        for snap in snapshots:
            self._notify_bridge("deleted", snapshot=snap)
        return result


class ProductTemplate(models.Model):
    _inherit = "product.template"

    def write(self, vals):
        result = super().write(vals)
        # Si se modificó algún campo relevante, forzamos la actualización de todas sus variantes
        if RELEVANT_FIELDS.intersection(vals.keys()):
            for template in self:
                # Dispara el evento 'updated' para cada variante (product.product) asociada a esta plantilla
                template.product_variant_ids._notify_bridge("updated")
        return result

    def unlink(self):
        # 1. Capturar las variantes (product.product) antes de que el SQL cascade las destruya
        variants = self.with_context(active_test=False).mapped("product_variant_ids")
        snapshots = [
            {
                "odoo_id": p.id,
                "sku": str(p.id),
                "name": p.name,
            }
            for p in variants
        ]
        
        # 2. Dejar que Odoo elimine el template y sus variantes
        result = super().unlink()
        
        # 3. Notificar al microservicio puente
        Product = self.env["product.product"].sudo()
        for snap in snapshots:
            Product._notify_bridge("deleted", snapshot=snap)
            
        return result


class ProductPricelistItem(models.Model):
    _inherit = "product.pricelist.item"

    def write(self, vals):
        res = super().write(vals)
        self._trigger_product_sync()
        return res

    @api.model_create_multi
    def create(self, vals_list):
        records = super().create(vals_list)
        records._trigger_product_sync()
        return records

    def unlink(self):
        self._trigger_product_sync()
        return super().unlink()

    def _trigger_product_sync(self):
        for item in self:
            if item.pricelist_id.name == 'Precio oferta':
                if item.product_tmpl_id:
                    item.product_tmpl_id.product_variant_ids._notify_bridge("updated")
                elif item.product_id:
                    item.product_id._notify_bridge("updated")