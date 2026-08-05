import hashlib
import hmac
import html
import os
import secrets

from fastapi import APIRouter, Depends, Form, HTTPException, status
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.security import HTTPBasic, HTTPBasicCredentials

from agent.memory import listar_handoffs, resolver_handoff

router = APIRouter()
security = HTTPBasic()


def _autenticar(credentials: HTTPBasicCredentials = Depends(security)) -> None:
    usuario = os.getenv("ADMIN_USERNAME", "admin")
    password = os.getenv("ADMIN_PASSWORD", "")
    if not password:
        raise HTTPException(status_code=503, detail="Panel no configurado")
    valido = secrets.compare_digest(credentials.username, usuario) and secrets.compare_digest(
        credentials.password, password
    )
    if not valido:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Credenciales inválidas",
            headers={"WWW-Authenticate": "Basic"},
        )


def _csrf(ticket_id: str) -> str:
    password = os.getenv("ADMIN_PASSWORD", "")
    return hmac.new(password.encode(), ticket_id.encode(), hashlib.sha256).hexdigest()


def _pagina(contenido: str) -> HTMLResponse:
    response = HTMLResponse(contenido)
    response.headers["Cache-Control"] = "no-store"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Robots-Tag"] = "noindex, nofollow"
    response.headers["Referrer-Policy"] = "no-referrer"
    response.headers["Content-Security-Policy"] = (
        "default-src 'none'; form-action 'self'; base-uri 'none'; frame-ancestors 'none'"
    )
    return response


@router.get("/admin", response_class=HTMLResponse)
async def panel_admin(_: None = Depends(_autenticar)):
    tickets = await listar_handoffs("pendiente")
    filas = []
    for ticket in tickets:
        filas.append(
            "<tr>"
            f"<td>{html.escape(ticket['creado'] or '')}</td>"
            f"<td>{html.escape(ticket['canal'])}</td>"
            f"<td>{html.escape(ticket['contacto'])}</td>"
            f"<td>{html.escape(ticket['motivo'])}</td>"
            f"<td>{html.escape(ticket['resumen'])}</td>"
            "<td>"
            f"<form method='post' action='/admin/handoffs/{ticket['id']}/resolve'>"
            f"<input type='hidden' name='csrf' value='{_csrf(ticket['id'])}'>"
            "<button type='submit'>Marcar resuelto y reactivar bot</button>"
            "</form></td></tr>"
        )
    cuerpo = "".join(filas) or "<tr><td colspan='6'>No hay casos pendientes.</td></tr>"
    return _pagina(
        "<!doctype html><html lang='es'><head><meta charset='utf-8'>"
        "<meta name='viewport' content='width=device-width,initial-scale=1'>"
        "<title>ESENCIALES — Casos pendientes</title></head><body>"
        "<h1>Casos pendientes</h1>"
        "<p><a href='https://business.facebook.com/latest/inbox/all' "
        "target='_blank' rel='noopener'>Abrir Meta Business Suite</a></p>"
        "<table border='1' cellpadding='6'><thead><tr>"
        "<th>Creado</th><th>Canal</th><th>Contacto</th><th>Motivo</th>"
        "<th>Mensaje inicial</th><th>Acción</th></tr></thead>"
        f"<tbody>{cuerpo}</tbody></table></body></html>"
    )


@router.post("/admin/handoffs/{ticket_id}/resolve")
async def resolver_desde_panel(
    ticket_id: str,
    csrf: str = Form(...),
    _: None = Depends(_autenticar),
):
    if not secrets.compare_digest(csrf, _csrf(ticket_id)):
        raise HTTPException(status_code=403, detail="CSRF inválido")
    if not await resolver_handoff(ticket_id):
        raise HTTPException(status_code=404, detail="Caso no encontrado o ya resuelto")
    return RedirectResponse(url="/admin", status_code=303)
