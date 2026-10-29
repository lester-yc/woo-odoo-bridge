from datetime import datetime

from sqlalchemy import DateTime, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.session import Base


class SyncMapping(Base):
    """
    Tabla puente: relaciona un registro de WooCommerce con su equivalente en Odoo.
    entity_type: 'order' | 'customer' | 'product'
    """
    __tablename__ = "sync_mapping"
    __table_args__ = (UniqueConstraint("entity_type", "woo_id", name="uq_entity_woo_id"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    entity_type: Mapped[str] = mapped_column(String(20), index=True)
    woo_id: Mapped[int] = mapped_column(Integer, index=True)
    odoo_id: Mapped[int] = mapped_column(Integer, index=True)
    sku: Mapped[str | None] = mapped_column(String(64), nullable=True)  # solo para productos
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow
    )


class WebhookEventLog(Base):
    """
    Registro simple de eventos recibidos, para depurar sin tener que leer logs de docker.
    """
    __tablename__ = "webhook_event_log"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    source: Mapped[str] = mapped_column(String(20))       # 'woocommerce' | 'odoo'
    event_type: Mapped[str] = mapped_column(String(50))   # 'order.updated', 'customer.created', etc
    reference_id: Mapped[str] = mapped_column(String(50))
    status: Mapped[str] = mapped_column(String(20), default="queued")  # queued|ok|error
    detail: Mapped[str | None] = mapped_column(String(500), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
