import re
import unicodedata


def _normalizar(texto: str) -> str:
    texto = unicodedata.normalize("NFKD", texto.lower())
    return "".join(c for c in texto if not unicodedata.combining(c))


REGLAS = (
    (
        "pedido_asistido",
        (
            r"\b(haz|hagan|hacer|haces|hacen|ingresa|ingresen|toma|tomen|arma|armen)(me)?\b.{0,35}\bpedido\b",
            r"\b(llen|rellen|complet)\w*\b.{0,35}\b(formulario|pedido)\b",
            r"\b(no se|no puedo|no entiendo)\b.{0,30}\b(comprar|pedido|formulario)\b",
            r"\b(ayudame|ayudenme)\b.{0,25}\b(comprar|pedido)\b",
            r"\b(quiero|puedo)\b.{0,20}\bcomprar por (aqui|chat|whatsapp)\b",
            r"\bme (lo|la) (puede|pueden|podria|podrian) pedir\b",
            r"\b(no\s*(?:se|c)|nose|no\s*pued\w*)\b.{0,35}\b(compr\w*|kompr\w*|pedido|formu\w*)\b",
            r"\b(hazme|hasme|aseme|haceme|agame)\b.{0,25}\bpedido\b",
            r"\b(kiero|qro)\b.{0,25}\bcompr\w*\b.{0,20}\b(aki|aqui|chat|wsp|whatsapp)\b",
        ),
    ),
    (
        "solicita_humano",
        (
            r"\b(hablar|contactar|atender)\w*\b.{0,25}\b(persona|humano|ejecutiv|vendedor)\w*\b",
            r"\bquiero una persona\b",
        ),
    ),
    (
        "pedido_existente",
        (
            r"\b(cancel|anul|cambiar direccion|modificar pedido|no quiero el pedido)\w*\b",
            r"\bmi pedido\b.{0,30}\b(no (?:llega|yega)|atras|demor|problema|equivoc)\w*\b",
        ),
    ),
    (
        "reclamo",
        (
            r"\b(reclamo|denuncia|estafa|fraude|devolucion|reembolso|producto malo|producto roto)\b",
        ),
    ),
    (
        "seguridad_tens",
        (
            r"\b(marcapas|embaraz|enbaras|implante|epilep|cardiac|lesion|dolor fuerte)\w*\b",
            r"\b(tens|electroestimulador|aparato)\b.{0,40}\b(corazon|corazón)\b",
            r"\btens\b.{0,35}\b(contraindic|riesgo|seguro|medico|duele)\w*\b",
        ),
    ),
    (
        "privacidad",
        (
            r"\b(borr|elimin|suprim|olvid)\w*\b.{0,35}\b(datos|numero|informacion|cuenta)\b",
            r"\b(mis datos|mi informacion)\b.{0,25}\b(borr|elimin|suprim)\w*\b",
        ),
    ),
    (
        "condicion_no_confirmada",
        (
            r"\b(garanti|devolucion|reembolso)\w*\b",
            r"\b(conexion|rosca|medida)\s+(especial|distinta|diferente)\b",
        ),
    ),
    (
        "destino_especial",
        (
            r"\b(envian|despachan|mandan|envio)\w*\b.{0,40}\b(extranjero|fuera de chile|peru|argentina|bolivia|colombia|ecuador|uruguay|paraguay)\b",
            r"\b(arica|tarapaca|antofagasta|atacama|aysen|magallanes)\b.{0,40}\b(envio|despacho|entrega|mandan)\w*\b",
            r"\b(soy|vivo|estoy)\s+(?:en|de)\s+(peru|argentina|bolivia|colombia|ecuador|uruguay|paraguay)\b",
        ),
    ),
    (
        "emergencia",
        (
            r"\b(suicid|autoles|matarme|quitarme la vida)\w*\b",
            r"\bme quiero morir\b",
        ),
    ),
)


def detectar_handoff(texto: str) -> str | None:
    normalizado = _normalizar(texto)
    for motivo, patrones in REGLAS:
        if any(re.search(patron, normalizado) for patron in patrones):
            return motivo
    return None


def mensaje_handoff(motivo: str) -> str:
    if motivo == "pedido_asistido":
        return (
            "Claro, podemos ayudarte a ingresar el pedido. Una persona del equipo "
            "continuará contigo por este mismo chat; no necesitas escribir a otro número. "
            "No envíes datos de tarjeta, claves ni contraseñas."
        )
    if motivo == "seguridad_tens":
        return (
            "Por seguridad, esa consulta sobre el TENS debe revisarla una persona. "
            "Dejaré la conversación pendiente para que el equipo continúe contigo."
        )
    if motivo == "privacidad":
        return (
            "Claro. Dejaré tu solicitud pendiente para que una persona del equipo "
            "gestione tus datos de forma segura por este mismo chat."
        )
    if motivo == "destino_especial":
        return (
            "Ese destino necesita confirmación de costo, plazo y forma de pago. "
            "Dejaré la conversación pendiente para que una persona del equipo "
            "continúe contigo por aquí."
        )
    if motivo == "condicion_no_confirmada":
        return (
            "Prefiero no asegurarte algo que todavía debemos revisar. Dejaré la "
            "conversación pendiente para que una persona del equipo te confirme."
        )
    if motivo == "emergencia":
        return (
            "Siento que estés pasando por esto. Busca ayuda inmediata de una persona "
            "de confianza y contacta ahora a los servicios de emergencia de tu zona. "
            "También dejaré esta conversación marcada para revisión humana."
        )
    return (
        "Voy a dejar esta conversación pendiente para que una persona del equipo "
        "continúe contigo por este mismo chat. No necesitas escribir a otro número."
    )


def respuesta_promete_handoff(texto: str) -> bool:
    """Detecta cuando el modelo anuncia una acción humana que debemos cumplir."""
    normalizado = _normalizar(texto)
    patrones = (
        r"\b(persona|alguien) del equipo\b.{0,50}\b(continu|ayud|revis|confirm|segu|ver)\w*\b",
        r"\b(dejar|dejare|voy a dejar)\w*\b.{0,40}\b(marcad|pendiente|revision)\w*\b",
        r"\b(lo|la|esto) revisamos con el equipo\b",
        r"\bdebe revisarl[oa] una persona\b",
    )
    return any(re.search(patron, normalizado) for patron in patrones)
