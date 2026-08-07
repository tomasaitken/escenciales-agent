# Despliegue y conexión de Escenciales

## 1. Cerrar la configuración comercial

Completa cada `[PENDIENTE...]` de `config/business.yaml` usando las páginas y
políticas oficiales de Escenciales. No despliegues mientras queden precios, stock,
despacho, garantías o contacto humano sin confirmar.

## 2. Preparar infraestructura

1. Crea un servicio desde este repositorio usando el `Dockerfile`.
2. Conecta PostgreSQL persistente y configura `DATABASE_URL` con SSL si el proveedor
   lo soporta. No uses el archivo SQLite de desarrollo.
3. Configura HTTPS y una URL estable, por ejemplo
   `https://agente.example.com/webhook`.
4. Copia las variables de `.env.example` al gestor de secretos del hosting. No
   subas un `.env`.
5. Crea un proyecto API en OpenAI y configura `OPENAI_API_KEY`. La facturación API
   es independiente de una suscripción ChatGPT.
6. Define `ENVIRONMENT=production`, `ADMIN_PASSWORD`, `META_ACCESS_TOKEN` para
   WhatsApp, `META_PAGE_ACCESS_TOKEN` para Messenger/Instagram y un
   `WHATSAPP_VERIFY_TOKEN` aleatorio y largo.
7. Configura `ADMIN_PUBLIC_URL=https://TU_DOMINIO` y, opcionalmente, Telegram.
8. Limita el acceso a logs y habilita alertas de errores.

## 3. Configurar Meta Business

1. Crea o usa una app Business asociada al Business Manager correcto.
2. Agrega WhatsApp, Messenger e Instagram y vincula el número, página de Facebook
   y cuenta profesional de Instagram de Escenciales.
3. Genera un usuario de sistema/token de producción con privilegio mínimo. Valida
   los permisos listados en `MISSING-ACCESS.md` y completa App Review cuando aplique.
4. En cada producto configura la callback `https://TU_DOMINIO/webhook` y el mismo
   `WHATSAPP_VERIFY_TOKEN` guardado en el hosting.
5. Suscribe el campo `messages` para WhatsApp y los eventos de mensajería necesarios
   para Página/Instagram. No suscribas eventos ajenos a este agente.
6. Copia IDs y token al gestor de secretos. Mantén `META_APP_SECRET` separado del
   token y rota ambos si fueron expuestos.
7. Confirma en el panel la versión Graph API activa y actualiza
   `META_GRAPH_API_VERSION`. El valor del ejemplo debe verificarse, no asumirse.

## 4. Prueba controlada

1. Mantén la app en modo desarrollo y usa cuentas/números de prueba.
2. Comprueba `GET /` y luego la verificación `GET /webhook` desde Meta.
3. Prueba una conversación independiente en WhatsApp, Messenger e Instagram.
4. Envía un audio en cada canal y revisa la transcripción.
5. Escribe "no sé comprar, háganme el pedido" y confirma que aparezca en `/admin`,
   que el bot quede pausado y que se reactive al resolver el caso.
6. Reenvía el mismo webhook y verifica que no haya respuesta duplicada.
7. Ejecuta los casos de `SECURITY-AUDIT.md` y revisa que los logs no contengan
   mensajes, teléfonos, direcciones ni tokens.

## 5. Shopify, Releasit y Dropi

La tienda ya tiene Releasit COD Form: desde cada URL de producto el cliente puede
completar sus datos y crear un pedido contraentrega en Shopify. El agente usa esa
ruta como opción preferida. No llama directamente al endpoint interno de Releasit.

La versión entregada **no crea pedidos directamente desde el chat**. Primero define
si se mantendrá el formulario o se implementará un adaptador autorizado. Después:

1. Crea una app personalizada de Shopify con el permiso mínimo requerido.
2. Mapea cada producto a su Variant ID y valida stock/precio desde Shopify.
3. Corrige en Releasit cobertura, términos, consentimiento de marketing y la oferta
   inconsistente del TENS.
4. Prueba un pedido Releasit → Shopify → Dropi y su despacho por Blue Express/Copec.
5. Confirma quién puede cancelar, editar dirección y resolver pedidos rechazados.
6. Solo entonces implementa y activa el adaptador; nunca registres un pedido si
   falla la confirmación de Shopify o Dropi.

## 6. Paso a producción

- Completa la lista de accesos y riesgos abiertos.
- Haz una prueba de aceptación firmada por la dueña de la tienda.
- Publica inicialmente con monitoreo cercano y un contacto humano disponible.
- Rota secretos tras cualquier exposición y revisa dependencias mensualmente.
