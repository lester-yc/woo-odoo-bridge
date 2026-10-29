from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # Odoo
    odoo_url: str = "http://odoo-19:8069"
    odoo_db: str = "postgres"
    odoo_user: str = "admin"
    odoo_password: str = "admin"

    # WooCommerce
    wc_url: str = "http://host.docker.internal/tu-sitio"
    wc_consumer_key: str = ""
    wc_consumer_secret: str = ""
    wc_webhook_secret: str = ""

    # Bridge Odoo -> microservicio (sync de productos en tiempo real)
    odoo_bridge_token: str = "cambia-este-token-por-uno-propio"

    # URL del microservicio vista desde WordPress/WooCommerce (el host), para
    # construir los links de imagen que WooCommerce va a descargar. Distinta
    # de odoo_url, que es la URL interna dentro de la red de Docker.
    public_bridge_url: str = "http://localhost:8080"

    # Infra
    redis_url: str = "redis://redis:6379/0"
    database_url: str = "sqlite:////srv/data/bridge.db"
    log_level: str = "INFO"


settings = Settings()
