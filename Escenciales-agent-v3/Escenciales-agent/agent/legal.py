import html
import os

from fastapi import APIRouter
from fastapi.responses import HTMLResponse


router = APIRouter()


def _datos_negocio() -> tuple[str, str, str, str]:
    nombre = os.getenv("LEGAL_BUSINESS_NAME", "ESENCIALES")
    correo = os.getenv("LEGAL_CONTACT_EMAIL", "contacto@chilessentials.cl")
    telefono = os.getenv("LEGAL_CONTACT_PHONE", "+56 9 3866 3898")
    direccion = os.getenv(
        "LEGAL_BUSINESS_ADDRESS",
        "Juan XXIII 5560, 33, Santiago, Región Metropolitana, Chile",
    )
    return tuple(html.escape(valor) for valor in (nombre, correo, telefono, direccion))


def _pagina(titulo: str, contenido: str) -> HTMLResponse:
    nombre, correo, telefono, direccion = _datos_negocio()
    documento = f"""<!doctype html>
<html lang="es">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{html.escape(titulo)} — {nombre}</title>
  <style>
    :root {{ color-scheme: light; font-family: system-ui, -apple-system, sans-serif; }}
    body {{ margin: 0; background: #f7f7f5; color: #202020; line-height: 1.65; }}
    main {{ max-width: 780px; margin: 0 auto; padding: 48px 24px 72px; }}
    article {{ background: white; border: 1px solid #e5e5e2; border-radius: 16px;
               padding: clamp(24px, 5vw, 48px); box-shadow: 0 8px 30px #0000000a; }}
    h1 {{ line-height: 1.15; margin-top: 0; }}
    h2 {{ margin-top: 2rem; line-height: 1.25; }}
    a {{ color: #185a48; }}
    .meta {{ color: #666; }}
    footer {{ margin-top: 36px; padding-top: 24px; border-top: 1px solid #e5e5e2; }}
  </style>
</head>
<body>
  <main><article>
    <h1>{html.escape(titulo)}</h1>
    <p class="meta">Última actualización: 7 de agosto de 2026</p>
    {contenido}
    <footer>
      <strong>{nombre}</strong><br>
      {direccion}<br>
      <a href="mailto:{correo}">{correo}</a> · {telefono}
    </footer>
  </article></main>
</body>
</html>"""
    response = HTMLResponse(documento)
    response.headers["Cache-Control"] = "public, max-age=300"
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    response.headers["Content-Security-Policy"] = (
        "default-src 'none'; style-src 'unsafe-inline'; "
        "base-uri 'none'; form-action 'none'; frame-ancestors 'none'"
    )
    return response


@router.get("/privacy", response_class=HTMLResponse)
@router.get("/privacidad", response_class=HTMLResponse)
def politica_privacidad() -> HTMLResponse:
    _, correo, _, _ = _datos_negocio()
    dias = html.escape(os.getenv("DATA_RETENTION_DAYS", "90"))
    return _pagina(
        "Política de privacidad del agente de atención",
        f"""
<p>Esta política complementa la política de privacidad de la tienda
<a href="https://chilessentials.cl/policies/privacy-policy">chilessentials.cl</a>
y explica el tratamiento de datos realizado por el agente de atención de
WhatsApp, Messenger e Instagram de ESENCIALES.</p>

<h2>Información que tratamos</h2>
<p>Podemos tratar el contenido de los mensajes, identificadores del canal,
número de teléfono, nombre de perfil, archivos de audio, historial de la
conversación y los datos que la persona entregue voluntariamente para una
consulta o pedido, como nombre, teléfono, dirección, comuna, producto,
cantidad y observaciones.</p>
<p>No solicitamos contraseñas, códigos de verificación ni datos completos de
tarjetas bancarias por mensajería.</p>

<h2>Finalidades</h2>
<p>Usamos esta información para responder consultas, explicar productos,
gestionar solicitudes de compra, coordinar pago contra entrega, entregar
soporte, detectar casos que requieren atención humana, prevenir abusos y
mantener la seguridad del servicio.</p>

<h2>Automatización e intervención humana</h2>
<p>Algunas respuestas son generadas con inteligencia artificial. El sistema
puede derivar la conversación a una persona cuando detecta una solicitud de
pedido asistido, una situación sensible, una consulta médica o un caso que no
puede resolver con seguridad. El agente no reemplaza asesoría médica ni atiende
emergencias.</p>

<h2>Proveedores</h2>
<p>Para prestar el servicio podemos utilizar proveedores tecnológicos y
comerciales, entre ellos Meta (WhatsApp, Facebook e Instagram), OpenAI,
Railway, PostgreSQL, Shopify y los servicios logísticos o de gestión de pedidos
utilizados por ESENCIALES, incluido Dropi cuando corresponda. Solo se comparte
la información necesaria para cada finalidad.</p>

<h2>Conservación y seguridad</h2>
<p>El historial operativo del agente se conserva normalmente por hasta {dias}
días, salvo que una obligación legal, una controversia o la gestión de un
pedido requiera conservarlo por más tiempo. Los audios se procesan para su
transcripción y el agente no los almacena como archivo permanente. Aplicamos
controles de acceso, validación de webhooks y almacenamiento separado de
credenciales.</p>

<h2>Derechos y solicitudes</h2>
<p>Puede solicitar acceso, corrección o eliminación de sus datos escribiendo a
<a href="mailto:{correo}">{correo}</a>. Podemos pedir información razonable
para verificar la identidad y localizar la conversación antes de responder.</p>

<h2>Transferencias y cambios</h2>
<p>Algunos proveedores pueden tratar datos fuera de Chile conforme a sus
condiciones y medidas de protección. Esta política puede actualizarse para
reflejar cambios técnicos, comerciales o legales.</p>
""",
    )


@router.get("/terms", response_class=HTMLResponse)
@router.get("/terminos", response_class=HTMLResponse)
def terminos_servicio() -> HTMLResponse:
    _, correo, _, _ = _datos_negocio()
    return _pagina(
        "Términos de uso del agente de atención",
        f"""
<p>Estos términos regulan el uso del agente de atención de ESENCIALES en
WhatsApp, Messenger e Instagram. Al conversar con el agente, la persona acepta
estas condiciones y la política de privacidad aplicable.</p>

<h2>Función del agente</h2>
<p>El agente entrega información comercial, responde preguntas frecuentes,
ayuda a recopilar datos para pedidos y deriva conversaciones al equipo humano.
Las respuestas automáticas pueden contener errores; cuando una información sea
decisiva para una compra, debe confirmarse en la tienda o con el equipo.</p>

<h2>Compras, despacho y pago</h2>
<p>Los precios, promociones, disponibilidad, cobertura y plazos vigentes son
los informados por ESENCIALES al confirmar el pedido. La oferta comercial
actual contempla despacho gratuito donde exista cobertura y pago contra
entrega o contra recepción del producto. Un pedido solicitado por mensajería
queda sujeto a validación de datos, disponibilidad y confirmación.</p>

<h2>Productos y seguridad</h2>
<p>La información sobre el electroestimulador TENS es general y no constituye
diagnóstico, tratamiento ni recomendación médica personalizada. No debe
utilizarse para emergencias. Ante embarazo, marcapasos, epilepsia, enfermedad
cardíaca, dolor intenso, lesión reciente u otra duda de salud, corresponde
consultar a un profesional antes de utilizarlo y seguir siempre el manual.</p>

<h2>Uso permitido</h2>
<p>No se permite utilizar el servicio para fraude, suplantación, amenazas,
envío de código malicioso, extracción automatizada de datos ni actividades
contrarias a la ley o a las políticas de Meta. Podemos limitar o suspender la
atención cuando sea necesario para proteger a clientes, al negocio o al
servicio.</p>

<h2>Disponibilidad y responsabilidad</h2>
<p>El servicio puede interrumpirse por mantenimiento o fallas de proveedores.
ESENCIALES procura mantener información correcta y atención oportuna, pero no
garantiza disponibilidad continua ni que toda respuesta automática sea
completa. Nada de estos términos limita los derechos irrenunciables que
correspondan a consumidores conforme a la legislación chilena.</p>

<h2>Contacto</h2>
<p>Las consultas sobre estos términos pueden enviarse a
<a href="mailto:{correo}">{correo}</a>.</p>
""",
    )


@router.get("/data-deletion", response_class=HTMLResponse)
@router.get("/eliminacion-de-datos", response_class=HTMLResponse)
def eliminacion_datos() -> HTMLResponse:
    _, correo, _, _ = _datos_negocio()
    return _pagina(
        "Solicitud de eliminación de datos",
        f"""
<p>Puede solicitar la eliminación de los datos asociados a sus conversaciones
con ESENCIALES.</p>

<h2>Cómo solicitarla</h2>
<ol>
  <li>Envíe un correo a <a href="mailto:{correo}?subject=Solicitud%20de%20eliminación%20de%20datos">{correo}</a>
  con el asunto <strong>Solicitud de eliminación de datos</strong>.</li>
  <li>Indique el canal utilizado: WhatsApp, Messenger o Instagram.</li>
  <li>Incluya el número de teléfono o nombre de usuario con el que se comunicó.
  No envíe contraseñas, códigos ni información bancaria.</li>
  <li>Si es necesario, ESENCIALES solicitará una verificación razonable para
  evitar que otra persona elimine sus datos sin autorización.</li>
</ol>

<h2>Qué ocurrirá</h2>
<p>Una vez verificada la solicitud, eliminaremos o anonimizaremos el historial
del agente y los datos que no sea necesario conservar. Informaremos la
finalización por correo. Algunos antecedentes pueden conservarse cuando sean
necesarios para cumplir obligaciones legales, tributarias, de protección al
consumidor, prevención de fraude o gestión de una compra.</p>

<p>También puede solicitar acceso o corrección de sus datos mediante el mismo
correo.</p>
""",
    )
