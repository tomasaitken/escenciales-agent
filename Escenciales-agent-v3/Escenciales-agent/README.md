# Escenciales — agente comercial omnicanal

Agente para WhatsApp, Instagram y Facebook Messenger. Atiende consultas sobre el
electroestimulador TENS, el cabezal de ducha y la antena HD; explica contraentrega
y despacho vía Dropi; y recopila datos para una solicitud de compra.

Versión 3: usa OpenAI, transcribe audios y pausa el bot cuando una persona debe
continuar la conversación.

## Estado real

- Conversación omnicanal: implementada.
- Validación criptográfica de webhooks Meta: implementada.
- Catálogo inyectado como fuente de verdad: implementado.
- Historial, deduplicación y retención: implementados.
- OpenAI Responses API (`gpt-5.6-terra` por defecto): implementada.
- Audios Meta → `gpt-transcribe`: implementados.
- Cola humana y panel `/admin`: implementados.
- Checkout contraentrega existente: el agente dirige al formulario Releasit COD de
  cada producto, que crea el pedido en Shopify.
- Creación directa de pedidos desde el chat/Dropi: **no activada**. Requiere definir
  y probar el flujo operativo de Dropi.
- Conexión a Meta producción: **no activada**. Requiere accesos listados en
  `MISSING-ACCESS.md`.

## Inicio local

1. Crea un entorno Python 3.12 e instala `requirements.txt`.
2. Copia `.env.example` a `.env` y llena solo las variables necesarias.
3. Completa todos los `[PENDIENTE...]` de `config/business.yaml`.
4. Ejecuta `python tests/test_local.py` para probar el tono sin Meta.
5. Ejecuta `uvicorn agent.main:app --host 127.0.0.1 --port 8000`.

No uses SQLite en producción. Lee `DEPLOYMENT.md` y `SECURITY-AUDIT.md` antes de
conectar la app a Meta Business.

## Estructura

- `agent/`: servidor, IA, memoria y proveedor Meta.
- `config/business.yaml`: catálogo y reglas comerciales; fuente de verdad.
- `config/prompts.yaml`: comportamiento del agente.
- `tests/`: prueba local y controles automatizados.
- `DEPLOYMENT.md`: despliegue y conexión Meta.
- `MISSING-ACCESS.md`: credenciales y decisiones pendientes.
- `SECURITY-AUDIT.md`: auditoría y controles de producción.
- `WEBSITE-DATA.md`: información extraída de la tienda y contradicciones detectadas.
- `HUMAN-HANDOFF.md`: operación de pedidos asistidos y pausa del bot.
