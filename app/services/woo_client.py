from woocommerce import API
from app.config import settings

def get_woo_client() -> API:
    return API(
        url=settings.wc_url,
        consumer_key=settings.wc_consumer_key,
        consumer_secret=settings.wc_consumer_secret,
        version="wc/v3",
        timeout=30,
        query_string_auth=True  # <-- ADICIONE ESTA LINHA
    )