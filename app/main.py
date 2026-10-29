from fastapi import FastAPI

from app.api.routers import odoo_webhooks, products, sync, woo_webhooks
from app.core.logging import setup_logging
from app.db.session import init_db

from app.api.routers import panel

setup_logging()

app = FastAPI(title="WooCommerce-Odoo Bridge")

app.include_router(woo_webhooks.router)
app.include_router(odoo_webhooks.router)
app.include_router(products.router)
app.include_router(sync.router)
app.include_router(panel.router)


@app.on_event("startup")
def on_startup():
    init_db()
