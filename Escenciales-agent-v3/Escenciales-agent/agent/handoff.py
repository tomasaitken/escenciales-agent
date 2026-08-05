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
            r"\bmi pedido\b.{0,30}\b(no llega|atras|demor|problema|equivoc)\w*\b",
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
            r"\b(marcapasos|embaraz|implante|epilep|cardiac|lesion|dolor fuerte)\w*\b",
            r"\btens\b.{0,35}\b(contraindic|riesgo|seguro|medico|duele)\w*\b",
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
            "Sí, podemos ayudarte a ingresar el pedido. Voy a dejar esta conversación "
            "pendiente para que una persona del equipo continúe contigo por aquí. "
            "No envíes datos de tarjeta, claves ni contraseñas."
        )
    if motivo == "seguridad_tens":
        return (
            "Por seguridad, esa consulta sobre el TENS debe revisarla una persona. "
            "Dejaré la conversación pendiente para que el equipo continúe contigo."
        )
    return (
        "Voy a dejar esta conversación pendiente para que una persona del equipo "
        "continúe contigo por aquí."
    )
