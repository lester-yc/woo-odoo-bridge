# -*- coding: utf-8 -*-
{
    "name": "Odoo - WooCommerce Bridge (Sync de productos)",
    "version": "19.0.1.0.0",
    "summary": "Notifica al microservicio puente cuando se crea, actualiza o elimina un producto, "
               "para reflejarlo en tiempo real en WooCommerce.",
    "category": "Sales",
    "author": "woo-odoo-bridge",
    "depends": ["product", "sale", "stock"],
    "data": [
        "data/ir_config_parameter.xml",
    ],
    "installable": True,
    "application": False,
    "license": "LGPL-3",
}
