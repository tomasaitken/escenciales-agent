# Guía operativa de activación — Escenciales

Usa esta guía para acompañar la activación sin exponer credenciales.

## Reglas

- Trabajar en ambiente de prueba hasta completar la auditoría.
- Pedir que las claves se carguen directamente en el hosting, nunca en el chat.
- No inventar precios, stock, cobertura, plazos, garantías ni políticas.
- No afirmar que Shopify o Dropi están conectados hasta probar un pedido completo.
- Hacer un cambio por vez y verificarlo antes del siguiente.

## Secuencia

1. Completar los datos comerciales pendientes.
2. Preparar hosting HTTPS y PostgreSQL.
3. Cargar variables desde `.env.example` en el gestor de secretos.
4. Configurar la app Meta y el webhook firmado.
5. Probar WhatsApp, Messenger e Instagram en modo desarrollo.
6. Ejecutar la lista de seguridad.
7. Definir e implementar el flujo Shopify/Dropi.
8. Obtener aprobación de la dueña y pasar a producción con monitoreo.

La documentación detallada está en `DEPLOYMENT.md`, `MISSING-ACCESS.md` y
`SECURITY-AUDIT.md`.
