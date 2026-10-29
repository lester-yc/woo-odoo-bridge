# -*- coding: utf-8 -*-
from odoo import models


class StockQuant(models.Model):
    _inherit = "stock.quant"

    def write(self, vals):
        result = super().write(vals)
        if "inventory_quantity" in vals or "quantity" in vals:
            products = self.mapped("product_id")
            if products:
                products._notify_bridge("updated")
        return result
