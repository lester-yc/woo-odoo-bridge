# woo-odoo-bridge

Microservicio puente entre WordPress/WooCommerce (en el host) y Odoo 19 (en Docker).

## Estructura

```
woo-odoo-bridge/
├── docker-compose.yml     # Odoo + Postgres (tu config original) + microservicio + worker + redis
├── Dockerfile
├── requirements.txt
├── .env.example
├── app/
│   ├── main.py             # FastAPI app
│   ├── config.py           # Settings (lee .env)
│   ├── api/routers/
│   │   ├── woo_webhooks.py # POST /webhooks/woocommerce/orders y /customers
│   │   └── sync.py         # /health, /sync/products, /sync/status
│   ├── services/
│   │   ├── odoo_client.py
│   │   ├── woocommerce_client.py
│   │   ├── order_sync.py
│   │   ├── customer_sync.py
│   │   └── product_sync.py
│   ├── tasks/
│   │   ├── worker.py       # entrypoint del worker RQ
│   │   └── jobs.py         # funciones que se encolan
│   ├── models/db_models.py # tabla SyncMapping (woo_id <-> odoo_id)
│   ├── db/session.py
│   └── core/
│       ├── security.py     # verificación de firma HMAC del webhook
│       └── logging.py
└── scripts/
    └── initial_product_import.py   # carga inicial de catálogo Odoo -> Woo
```

## 1. Instalación

Coloca este proyecto **en la misma carpeta donde ya tienes tu `docker-compose.yml` de Odoo**
(sustituye el que ya usabas por el nuevo, ya incluye tus servicios `basedatos19` y `odoo-19`
tal cual, más `redis`, `microservicio` y `worker`).

```bash
cp .env.example .env
```

Edita `.env` y completa:

- `WC_URL`: la URL de tu sitio vista desde el contenedor, ej `http://host.docker.internal/mitienda`
- `WC_CONSUMER_KEY` / `WC_CONSUMER_SECRET`: los generas en WordPress → WooCommerce → Ajustes →
  Avanzado → REST API → Añadir clave (permisos "Lectura/Escritura")
- `WC_WEBHOOK_SECRET`: cualquier string largo, debe coincidir con el que pongas en el webhook de WooCommerce
- `ODOO_USER` / `ODOO_PASSWORD`: las credenciales del usuario admin de tu instancia Odoo 19

Levanta todo:

```bash
docker compose up -d --build
```

Verifica:

```bash
curl http://localhost:8080/health
# {"status":"ok"}
```

> **Nota sobre el puerto**: se publica en `8080` (no `8000`) a propósito. WordPress, por seguridad,
> solo permite peticiones HTTP salientes (como los webhooks de WooCommerce) a los puertos
> `80`, `443` y `8080` por defecto — cualquier otro puerto lo rechaza con un error tipo
> "no se ha facilitado una URL válida", aunque la URL esté bien formada. Si necesitas usar
> otro puerto, hay que agregar un filtro `http_allowed_safe_ports` en `functions.php`.

## 2. Configurar WooCommerce

**API REST** (WooCommerce → Ajustes → Avanzado → REST API): crea la clave, cópiala a `.env`.

**Webhooks** (WooCommerce → Ajustes → Avanzado → Webhooks):

| Webhook | Topic | Delivery URL |
|---|---|---|
| Pedidos | `Order updated` | `http://localhost:8080/webhooks/woocommerce/orders` |
| Clientes | `Customer created` | `http://localhost:8080/webhooks/woocommerce/customers` |
| Clientes | `Customer updated` | `http://localhost:8080/webhooks/woocommerce/customers` |

En cada uno, el campo **Secret** debe ser idéntico a `WC_WEBHOOK_SECRET` en tu `.env`.

## 3. Carga inicial de productos (Odoo → WooCommerce)

Antes de recibir pedidos necesitas que los productos existan en ambos lados con el mismo SKU:

```bash
docker compose exec microservicio python -m scripts.initial_product_import
```

Para sincronizaciones incrementales posteriores (precio/stock), puedes disparar manualmente:

```bash
curl -X POST http://localhost:8080/sync/products
```

O automatizarlo con un cron del sistema operativo que llame a ese mismo endpoint cada N minutos.

## 4. Ver el estado de la sincronización

```bash
curl http://localhost:8080/sync/status
# {"order": 3, "customer": 5, "product": 42}
```

## 5. WP-Cron (importante en local)

WooCommerce dispara sus webhooks vía WP-Cron, que normalmente solo corre cuando alguien visita
el sitio. En local, fuerza su ejecución tras crear un pedido de prueba:

```bash
wp cron event run --due-now --path=/var/www/html/tu-sitio
```

O instala un cron real del sistema que golpee `wp-cron.php` cada minuto.

## 6. Logs

```bash
docker compose logs -f microservicio   # API / webhooks recibidos
docker compose logs -f worker          # procesamiento en segundo plano
```

## Próximos pasos sugeridos

- Migrar de `sqlite` a Postgres compartido si el volumen de datos crece
- Añadir reintentos con backoff en los jobs (RQ soporta `retry=Retry(max=3)`)
- Fase 2: módulo Odoo con Automated Action para push de productos en tiempo real
  en vez de polling (ver carpeta `extra-addons` de tu compose de Odoo)
