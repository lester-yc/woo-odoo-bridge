# -*- coding: utf-8 -*-
from odoo import models


class StockMove(models.Model):
    _inherit = "stock.move"

    def _action_done(self, cancel_backorder=False):
        moves = super()._action_done(cancel_backorder=cancel_backorder)
        products = moves.mapped("product_id")
        if products:
            # qty_available ya está actualizado en este punto
            products._notify_bridge("updated")
        return moves
