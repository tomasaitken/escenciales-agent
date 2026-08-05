# Auditoría de seguridad previa a producción

Fecha: 2026-08-04. Alcance: código recibido en `lucia-estetica-holistica.zip` y
versión convertida a Escenciales. No se auditaron cuentas externas porque aún no
se entregaron accesos.

## Resultado

**No conectar a producción todavía.** El código quedó endurecido, pero faltan datos
comerciales, credenciales, base persistente, pruebas reales de permisos y revisión
del flujo Shopify/Dropi.

## Hallazgos corregidos

- **Crítico — webhook sin autenticidad:** el original aceptaba POST sin verificar
  `X-Hub-Signature-256`. Ahora valida HMAC-SHA256 con `META_APP_SECRET`.
- **Alto — catálogo no utilizado:** `business.yaml` nunca llegaba al modelo. Ahora
  se inyecta en cada prompt como fuente de verdad.
- **Alto — canal de salida inferido por ID:** podía responder por el canal equivocado.
  Ahora el canal viaja explícitamente desde el webhook hasta el envío.
- **Alto — reintentos duplicados:** no había idempotencia. Ahora el ID del mensaje
  se registra con restricción única.
- **Alto — datos y texto en logs:** se registraban teléfono y fragmento del mensaje.
  Ahora solo se registra un hash corto no reversible para correlación operativa.
- **Medio — filtración de errores:** se devolvía el texto interno de excepciones.
  Ahora producción entrega un error genérico.
- **Medio — respuesta lenta a Meta:** el webhook esperaba la llamada de IA. Ahora
  confirma recepción primero y procesa en segundo plano.
- **Medio — rutas dependientes del directorio actual:** la configuración podía no
  encontrarse al desplegar. Ahora usa rutas derivadas del paquete.
- **Medio — retención indefinida:** se agregó purga configurable con 90 días por
  defecto.
- **Medio — contenedor como root:** Docker ahora usa un usuario sin privilegios.

## Riesgos abiertos

- El procesamiento en segundo plano vive dentro del proceso web. Para volumen alto
  o garantía de entrega debe migrarse a una cola persistente.
- Los audios se descargan solo desde dominios Meta, con límite de 10 MB, y se borran
  después de transcribir. Debe informarse este tratamiento en privacidad.
- El panel humano usa autenticación HTTP Basic y requiere HTTPS, contraseña única y
  acceso restringido. Para un equipo mayor conviene identidad administrada y MFA.
- SQLite no es apropiado para producción ni múltiples réplicas. Usar PostgreSQL.
- Los mensajes y direcciones se almacenan sin cifrado a nivel de aplicación. Exigir
  cifrado de disco/base administrada y mínimo acceso operativo.
- No existe panel autenticado de pedidos ni handoff automático. El agente solo
  recopila la conversación hasta completar Shopify/Dropi.
- No hay borrado autoservicio; solicitudes de privacidad deben escalarse y ser
  ejecutadas por el responsable de datos.
- Las fichas y precios se cargaron desde Shopify. Garantías, devoluciones y algunos
  datos técnicos siguen sin publicarse.
- La seguridad médica del TENS requiere ficha/manual del producto y validación por
  una persona competente. El agente quedó restringido a no dar consejo médico.
- Debe probarse el token real con privilegio mínimo y rotación documentada.
- Verificar en los paneles oficiales las versiones de Meta, Shopify y Dropi antes
  del despliegue; no asumir que un valor de ejemplo sigue vigente.
- El formulario Releasit tiene marketing preseleccionado. Cambiarlo a consentimiento
  explícito antes de usar datos de mensajería para campañas.
- El enlace de términos responde 404 y la aceptación está desactivada. Publicar
  términos válidos antes de producción.
- El storefront anuncia todo Chile, pero Releasit excluye seis regiones. Corregir
  el marketing o la cobertura para evitar ventas engañosas.
- La oferta por dos TENS tiene una diferencia de $1.000 entre texto y descuento
  configurado. El agente quedó bloqueado para ofrecerla.

## Pruebas obligatorias antes de activar

1. Firma válida, firma inválida y payload mayor a 1 MB.
2. Un mismo webhook repetido no produce dos respuestas.
3. Envío y recepción real en los tres canales con usuarios de prueba.
4. Separación de historial para un mismo identificador en canales distintos.
5. Token sin permisos excesivos y rotación sin caída prolongada.
6. Reinicio y múltiples instancias con PostgreSQL.
7. Solicitud completa, incompleta, cancelación, reclamo y eliminación de datos.
8. Prompt injection, enlaces maliciosos y preguntas que intenten inventar precios.
9. Casos médicos y sensibles del TENS siempre escalan.
10. Backup, restauración, monitoreo y alertas de errores.
