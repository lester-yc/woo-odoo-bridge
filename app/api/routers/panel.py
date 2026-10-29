from fastapi import APIRouter, Request, Form, Depends
from fastapi.templating import Jinja2Templates
from fastapi.responses import HTMLResponse, RedirectResponse
import os

from app.db.session import SessionLocal
from app.models.db_models import SyncMapping

router = APIRouter()

BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
templates = Jinja2Templates(directory=os.path.join(BASE_DIR, "templates"))

# --- RUTAS DE AUTENTICACIÓN ---

@router.get("/login", response_class=HTMLResponse)
async def login_page(request: Request):
    # Si ya tiene la cookie, mandarlo directo al panel
    if request.cookies.get("panel_session") == "authenticated":
        return RedirectResponse(url="/panel", status_code=302)
    return templates.TemplateResponse("login.html", {"request": request})


@router.post("/login", response_class=HTMLResponse)
async def login_process(request: Request, username: str = Form(...), password: str = Form(...)):
    # Leer credenciales del .env
    admin_user = os.getenv("PANEL_USER", "admin")
    admin_pass = os.getenv("PANEL_PASSWORD", "admin")

    if username == admin_user and password == admin_pass:
        # Credenciales correctas: Crear respuesta, setear cookie y redirigir
        response = RedirectResponse(url="/panel", status_code=302)
        response.set_cookie(key="panel_session", value="authenticated", httponly=True, max_age=3600) # Expira en 1 hora
        return response
    else:
        # Credenciales incorrectas: Mostrar error
        return templates.TemplateResponse("login.html", {"request": request, "error": "Usuario o contraseña incorrectos"})


@router.get("/logout")
async def logout():
    # Eliminar la cookie y redirigir al login
    response = RedirectResponse(url="/login", status_code=302)
    response.delete_cookie("panel_session")
    return response


# --- RUTA DEL PANEL (PROTEGIDA) ---

@router.get("/panel", response_class=HTMLResponse)
async def read_panel(request: Request):
    # 0. PROTEGER LA RUTA: Validar si existe la cookie
    if request.cookies.get("panel_session") != "authenticated":
        return RedirectResponse(url="/login", status_code=302)

    db = SessionLocal()
    try:
        total_syncs = db.query(SyncMapping).count()
        clientes_sync = db.query(SyncMapping).filter(SyncMapping.entity_type == "customer").count()
        pedidos_sync = db.query(SyncMapping).filter(SyncMapping.entity_type == "order").count()
    except Exception as e:
        total_syncs, clientes_sync, pedidos_sync = 0, 0, 0
    finally:
        db.close()

    def mask_secret(secret: str):
        if not secret:
            return "No configurado"
        return "*" * 12 + str(secret)[-4:] if len(str(secret)) > 4 else "***"

    credenciales = {
        "Odoo URL": os.getenv("ODOO_URL", "No configurado"),
        "Odoo Base de Datos": os.getenv("ODOO_DB", "No configurado"),
        "Odoo Usuario": os.getenv("ODOO_USER", "No configurado"),
        "WooCommerce URL": os.getenv("WC_URL", "No configurado"),
        "WooCommerce Consumer Key": mask_secret(os.getenv("WC_CONSUMER_KEY", "")),
        "WooCommerce Consumer Secret": mask_secret(os.getenv("WC_CONSUMER_SECRET", "")),
        "Redis Host": os.getenv("REDIS_URL", "No configurado"),
    }

    context = {
        "request": request,
        "total_syncs": total_syncs,
        "clientes_sync": clientes_sync,
        "pedidos_sync": pedidos_sync,
        "credenciales": credenciales
    }
    return templates.TemplateResponse("panel.html", context)