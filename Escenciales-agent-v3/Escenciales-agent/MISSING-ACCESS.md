# Accesos y datos pendientes

No pegues secretos en chats ni documentos. Cárgalos directamente en las variables
del proveedor de hosting.

## Bloqueantes para Meta

- Usuario con rol administrador o desarrollador en Meta Business de Escenciales.
- App ID y App Secret de la app Meta.
- Token de usuario del sistema para WhatsApp (`META_ACCESS_TOKEN`) y token de
  página separado para Messenger/Instagram (`META_PAGE_ACCESS_TOKEN`).
- WhatsApp Business Account ID y Phone Number ID.
- Número habilitado para WhatsApp Cloud API.
- ID de la página de Facebook y de la cuenta profesional de Instagram vinculada.
- Verify token nuevo y aleatorio para el webhook.
- Versión Graph API seleccionada en la app; revisar antes de desplegar el valor de
  ejemplo `v25.0`.
- App Review/Advanced Access para los permisos que Meta exija fuera de modo prueba.

Permisos a validar en Meta según los canales activados:
`whatsapp_business_messaging`, `whatsapp_business_management`, `pages_messaging`,
`pages_manage_metadata`, `instagram_basic` e `instagram_manage_messages`. Meta puede
pedir permisos adicionales según la configuración exacta de la página y la app.

## Datos comerciales que la web no publica

- Garantía, soporte, cambios, devoluciones, rechazo y cancelación.
- Compatibilidad/medidas del cabezal y conectores/requisitos de la antena.
- Contenido exacto de cada paquete.
- Confirmar si los plazos publicados son días hábiles o corridos.
- Resolver la contradicción de cobertura nacional versus seis regiones excluidas.
- Corregir la oferta de 2 TENS: texto $10.000 versus configuración $9.000.
- Confirmar horario del equipo que recibirá escalaciones.

## Bloqueantes para automatizar pedidos

- Acceso administrador a Shopify y Releasit COD Form.
- Admin API access token con el mínimo permiso de escritura necesario.
- Versión de Shopify Admin API y IDs de variantes.
- Definir si el agente seguirá enviando al formulario Releasit o también creará
  pedidos COD directamente desde el chat.
- Documentación y token oficial de la cuenta Dropi, si su flujo no se resuelve por
  la sincronización existente con Shopify.
- Mapeo probado Shopify → Dropi para pedidos contraentrega, estados y cancelaciones.

## Infraestructura

- Hosting con HTTPS y dominio estable.
- PostgreSQL persistente y sus credenciales.
- Responsable de logs, alertas, backups y rotación de secretos.
- Correo o canal interno para avisos de fallos y escalaciones.

## OpenAI y atención humana

- Proyecto API de OpenAI con facturación y límite mensual.
- `OPENAI_API_KEY` cargada directamente en Railway.
- Contraseña única de al menos 16 caracteres para `/admin`.
- Decidir si los avisos serán solo por el panel o también por Telegram.
- Si se usa Telegram: bot token y chat ID de la persona responsable.
