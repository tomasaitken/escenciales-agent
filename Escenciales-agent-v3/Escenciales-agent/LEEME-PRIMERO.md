# Escenciales — leer antes de activar

Esta carpeta es la versión convertida del agente de clínicas a un agente comercial
para Escenciales.

Todavía **no debe conectarse a producción**. Primero:

1. Completa `config/business.yaml` con catálogo y políticas reales.
2. Revisa `MISSING-ACCESS.md` y consigue los accesos faltantes.
3. Sigue `DEPLOYMENT.md` para infraestructura y Meta Business.
4. Resuelve todos los riesgos abiertos de `SECURITY-AUDIT.md`.
5. Prueba los tres canales antes de poner la app en modo público.

Nunca pegues API keys o tokens en chats. Guárdalos directamente en el gestor de
secretos del hosting. La integración automática Shopify/Dropi queda pendiente hasta
definir el flujo real de pedidos y entregar credenciales de prueba.

