import base64
import hashlib
import hmac

from app.config import settings
from app.core.logging import get_logger

logger = get_logger(__name__)


def verify_woo_signature(raw_body: bytes, signature_header: str | None) -> bool:
    """
    WooCommerce firma el payload como base64(HMAC-SHA256(body, secret)).
    El header llega en X-WC-Webhook-Signature.
    """
    if not signature_header or not settings.wc_webhook_secret:
        logger.warning(
            "Falta header o secret. header_presente=%s secret_configurado=%s",
            bool(signature_header), bool(settings.wc_webhook_secret),
        )
        return False

    computed = hmac.new(
        settings.wc_webhook_secret.encode("utf-8"),
        raw_body,
        hashlib.sha256,
    ).digest()
    computed_b64 = base64.b64encode(computed).decode("utf-8")

    is_valid = hmac.compare_digest(computed_b64, signature_header)

    if not is_valid:
        logger.warning(
            "DEBUG FIRMA -> body_len=%s body_preview=%r recibido=%r calculado=%r secret_usado=%r",
            len(raw_body), raw_body[:200], signature_header, computed_b64, settings.wc_webhook_secret,
        )

    return is_valid
