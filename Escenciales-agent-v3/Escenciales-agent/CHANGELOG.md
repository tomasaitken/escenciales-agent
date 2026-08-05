# Cambios

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
