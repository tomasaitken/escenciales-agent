# Cambios

## 3.5.0 — 2026-08-10

- Identificación de anuncios endurecida con evidencia ponderada de título, texto y
  URL, más clasificación visual con confianza mínima.
- Si los metadatos y la miniatura se contradicen, el agente pregunta el producto en
  vez de adivinar o heredar uno anterior de la conversación.
- Las miniaturas se analizan con mayor detalle y criterios visuales específicos para
  TENS, antena y ducha.
- Descripción corregida de la antena amplificada: mayor capacidad de captación y
  refuerzo de señales débiles que una antena convencional, sin prometer señal donde
  no existe transmisión digital terrestre.

## 3.4.0 — 2026-08-09

- Paridad comercial obligatoria entre WhatsApp, Messenger e Instagram.
- Las preguntas de ubicación reciben una respuesta uniforme con Santiago, envío
  gratis a todo Chile, pago contraentrega y una pregunta sobre el producto.
- Seguimiento único 15 minutos después de entregar el enlace de compra, persistente
  ante reinicios y cancelado automáticamente por respuesta del cliente, intervención
  humana o handoff.
- Los clientes con dificultad para comprar reciben una oferta de ayuda temprana y
  el pedido asistido continúa por el mismo chat.

## 3.3.0 — 2026-08-09

- Flujo comercial semiautomático: precio, envío gratis y pago al recibir aparecen
  antes del enganche comercial en la primera explicación del producto.
- El enlace de compra deja de enviarse ante consultas genéricas o de precio y se
  reserva para intención explícita de compra.
- El mensaje de checkout ofrece ayuda con el formulario por el mismo chat.
- Los pedidos asistidos se derivan a una persona del equipo sin repetir el número
  de WhatsApp y el agente queda pausado para permitir el cierre humano.

## 3.2.1 — 2026-08-08

- Reconocimiento visual de anuncios de Meta en video cuando el título y el texto
  del anuncio no nombran el producto.
- La miniatura temporal del anuncio se clasifica únicamente como TENS, antena,
  ducha o desconocido; no se conserva la imagen.
- El producto identificado se guarda en una caché acotada por ID de anuncio para
  evitar análisis repetidos dentro de la misma ejecución.
- Validación de dominio, formato y tamaño antes de procesar la miniatura.

## 3.2.0 — 2026-08-08

- Reconocimiento del producto desde el contexto de anuncios de Meta en WhatsApp,
  Messenger e Instagram.
- Las consultas genéricas provenientes de un anuncio responden directamente sobre
  Antena HD, Cabezal de ducha o TENS, sin volver a preguntar qué producto interesa.
- El contexto del anuncio se conserva al agrupar mensajes consecutivos.
- Tono con un emoji cálido ocasional, limitado a uno por mensaje y excluido de temas
  sensibles.
- Enlace oficial de compra enviado como segundo mensaje breve, una sola vez por
  producto y conversación, sin duplicarlo dentro de la explicación.
- Pruebas automatizadas y evaluación real del caso observado en producción.

## 3.0.0 — 2026-08-04

- Migración de Anthropic a OpenAI Responses API.
- Modelo conversacional configurable; valor inicial `gpt-5.6-terra`.
- Transcripción de audios con `gpt-transcribe`.
- Descarga limitada a dominios Meta y 10 MB.
- Conversión segura de notas de voz OGG/AMR con FFmpeg.
- Detección de pedido asistido, solicitud humana, reclamo, cancelación y consultas
  sensibles del TENS.
- Creación de casos pendientes y pausa por conversación.
- Panel `/admin` protegido para resolver casos y reactivar el agente.
- Notificación opcional por Telegram sin incluir el contenido del cliente.
- Responses API configurada con `store=false` y `safety_identifier` seudónimo.
- 14 pruebas automatizadas sin llamadas reales ni consumo de créditos.

## 2.0.0 — 2026-08-04

- Conversión desde clínica a ESENCIALES.
- Catálogo y checkout extraídos desde chilessentials.cl.
- Firma HMAC de webhooks, idempotencia, retención y logs seudonimizados.
