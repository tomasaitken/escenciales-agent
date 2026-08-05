# Pedidos asistidos e intervención humana

## Qué ocurre

Cuando el cliente pide que le hagan el pedido, solicita una persona, reclama,
cancela o hace una consulta sensible sobre el TENS:

1. El agente responde que una persona continuará por el mismo chat.
2. Crea un caso pendiente en PostgreSQL.
3. Cambia la conversación a `esperando_humano`.
4. Deja de responder automáticamente a los mensajes siguientes.
5. Envía un aviso por Telegram si está configurado.
6. La conversación sigue disponible en Meta Business Suite.

## Panel

El panel está en:

```text
https://TU-DOMINIO/admin
```

El navegador pedirá `ADMIN_USERNAME` y `ADMIN_PASSWORD`. Desde el panel se abre
Meta Business Suite y se marca cada caso como resuelto. Al resolverlo, el agente
vuelve a quedar activo para esa conversación.

## Pedido hecho por una persona

La persona del equipo debe:

1. Confirmar producto, cantidad, región, nombre, apellido, WhatsApp, dirección,
   referencia y ciudad/comuna.
2. Repetir el resumen y obtener confirmación explícita.
3. Ingresar el pedido mediante el formulario Releasit del producto o el panel de
   Shopify definido por el negocio.
4. Confirmar por el chat que el pedido quedó ingresado.
5. Marcar el caso como resuelto en `/admin`.

Nunca pedir tarjeta, claves, contraseña ni foto de documentos.

## Audios

- Meta entrega el audio al agente mediante un identificador o URL firmada.
- El agente limita la descarga a 10 MB y dominios Meta.
- OpenAI `gpt-transcribe` lo convierte a texto.
- El archivo temporal se elimina después de la transcripción.
- Solo se guarda la transcripción en el historial.
- Si falla, se crea automáticamente un caso humano.

## Avisos por Telegram (opcional)

Configura `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID` y `ADMIN_PUBLIC_URL`. El aviso
solo contiene canal, motivo e ID del caso; no envía dirección ni texto completo.
