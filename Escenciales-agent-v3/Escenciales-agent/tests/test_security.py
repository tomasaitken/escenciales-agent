import hashlib
import hmac
import json
import os
import unittest
from unittest.mock import patch

from fastapi import HTTPException, Request

from agent.brain import cargar_system_prompt
from agent.providers.meta_multichannel import ProveedorMetaMulticanal


def request_con_firma(firma: str) -> Request:
    scope = {
        "type": "http",
        "method": "POST",
        "path": "/webhook",
        "headers": [(b"x-hub-signature-256", firma.encode("ascii"))],
        "query_string": b"",
        "server": ("test", 443),
        "client": ("127.0.0.1", 1234),
        "scheme": "https",
    }
    return Request(scope)


def request_con_body(body: bytes, firma: str) -> Request:
    scope = {
        "type": "http",
        "method": "POST",
        "path": "/webhook",
        "headers": [(b"x-hub-signature-256", firma.encode("ascii"))],
        "query_string": b"",
        "server": ("test", 443),
        "client": ("127.0.0.1", 1234),
        "scheme": "https",
    }
    entregado = False

    async def receive():
        nonlocal entregado
        if entregado:
            return {"type": "http.request", "body": b"", "more_body": False}
        entregado = True
        return {"type": "http.request", "body": body, "more_body": False}

    return Request(scope, receive)


class SeguridadWebhookTests(unittest.TestCase):
    def setUp(self):
        self.secreto_anterior = os.environ.get("META_APP_SECRET")
        os.environ["META_APP_SECRET"] = "secreto-de-prueba-no-real"
        self.provider = ProveedorMetaMulticanal()

    def tearDown(self):
        if self.secreto_anterior is None:
            os.environ.pop("META_APP_SECRET", None)
        else:
            os.environ["META_APP_SECRET"] = self.secreto_anterior

    def test_acepta_firma_hmac_valida(self):
        body = b'{"entry":[]}'
        digest = hmac.new(
            b"secreto-de-prueba-no-real", body, hashlib.sha256
        ).hexdigest()
        self.provider._validar_firma(request_con_firma(f"sha256={digest}"), body)

    def test_acepta_firma_de_la_app_directa_de_instagram(self):
        body = b'{"object":"instagram","entry":[]}'
        with patch.dict(os.environ, {
            "META_APP_SECRET": "secreto-app-principal",
            "META_INSTAGRAM_APP_SECRET": "secreto-app-instagram",
        }):
            provider = ProveedorMetaMulticanal()
            digest = hmac.new(
                b"secreto-app-instagram", body, hashlib.sha256
            ).hexdigest()
            provider._validar_firma(
                request_con_firma(f"sha256={digest}"), body
            )

    def test_rechaza_firma_invalida(self):
        with self.assertRaises(HTTPException) as contexto:
            self.provider._validar_firma(
                request_con_firma("sha256=" + "0" * 64), b'{"entry":[]}'
            )
        self.assertEqual(contexto.exception.status_code, 401)

    def test_rechaza_url_de_audio_fuera_de_meta(self):
        with self.assertRaises(ValueError):
            self.provider._validar_url_media("https://example.com/audio.ogg")

    def test_separa_token_whatsapp_de_token_pagina(self):
        anteriores = {
            nombre: os.environ.get(nombre)
            for nombre in ("META_ACCESS_TOKEN", "META_PAGE_ACCESS_TOKEN")
        }
        try:
            os.environ["META_ACCESS_TOKEN"] = "token-whatsapp-prueba"
            os.environ["META_PAGE_ACCESS_TOKEN"] = "token-pagina-prueba"
            provider = ProveedorMetaMulticanal()
            self.assertEqual(provider.wa_token, "token-whatsapp-prueba")
            self.assertEqual(provider.page_token, "token-pagina-prueba")
        finally:
            for nombre, valor in anteriores.items():
                if valor is None:
                    os.environ.pop(nombre, None)
                else:
                    os.environ[nombre] = valor

    def test_separa_token_directo_de_instagram(self):
        nombres = (
            "META_PAGE_ACCESS_TOKEN",
            "META_INSTAGRAM_ACCESS_TOKEN",
            "META_INSTAGRAM_ACCOUNT_ID",
        )
        anteriores = {nombre: os.environ.get(nombre) for nombre in nombres}
        try:
            os.environ["META_PAGE_ACCESS_TOKEN"] = "token-pagina-prueba"
            os.environ["META_INSTAGRAM_ACCESS_TOKEN"] = "token-instagram-prueba"
            os.environ["META_INSTAGRAM_ACCOUNT_ID"] = "cuenta-instagram-prueba"
            provider = ProveedorMetaMulticanal()
            self.assertEqual(provider.page_token, "token-pagina-prueba")
            self.assertEqual(provider.instagram_token, "token-instagram-prueba")
            self.assertEqual(provider.ig_account_id, "cuenta-instagram-prueba")
        finally:
            for nombre, valor in anteriores.items():
                if valor is None:
                    os.environ.pop(nombre, None)
                else:
                    os.environ[nombre] = valor


class EnvioInstagramTests(unittest.IsolatedAsyncioTestCase):
    async def test_instagram_usa_graph_instagram_y_token_directo(self):
        nombres = (
            "META_PAGE_ACCESS_TOKEN",
            "META_INSTAGRAM_ACCESS_TOKEN",
            "META_INSTAGRAM_ACCOUNT_ID",
        )
        anteriores = {nombre: os.environ.get(nombre) for nombre in nombres}
        os.environ["META_PAGE_ACCESS_TOKEN"] = "token-pagina-prueba"
        os.environ["META_INSTAGRAM_ACCESS_TOKEN"] = "token-instagram-prueba"
        os.environ["META_INSTAGRAM_ACCOUNT_ID"] = "cuenta-instagram-prueba"
        solicitudes = []

        class Respuesta:
            status_code = 200

            def json(self):
                return {"message_id": "mensaje-saliente-instagram-1"}

        class ClienteFalso:
            def __init__(self, *args, **kwargs):
                pass

            async def __aenter__(self):
                return self

            async def __aexit__(self, *args):
                return None

            async def post(self, url, headers, json):
                solicitudes.append((url, headers, json))
                return Respuesta()

        try:
            provider = ProveedorMetaMulticanal()
            with patch(
                "agent.providers.meta_multichannel.httpx.AsyncClient",
                ClienteFalso,
            ):
                enviado = await provider.enviar_mensaje(
                    "cliente-instagram", "Hola", "instagram"
                )
            self.assertTrue(enviado)
            self.assertEqual(len(solicitudes), 1)
            url, headers, payload = solicitudes[0]
            self.assertEqual(
                url,
                "https://graph.instagram.com/v25.0/cuenta-instagram-prueba/messages",
            )
            self.assertEqual(
                headers["Authorization"], "Bearer token-instagram-prueba"
            )
            self.assertEqual(payload["recipient"]["id"], "cliente-instagram")
            self.assertNotIn("messaging_type", payload)
        finally:
            for nombre, valor in anteriores.items():
                if valor is None:
                    os.environ.pop(nombre, None)
                else:
                    os.environ[nombre] = valor


class ParseoAudioTests(unittest.IsolatedAsyncioTestCase):
    async def test_omite_echo_directo_del_mensaje_enviado_por_el_bot(self):
        nombres = (
            "META_APP_SECRET",
            "META_INSTAGRAM_APP_SECRET",
            "META_INSTAGRAM_ACCOUNT_ID",
        )
        anteriores = {nombre: os.environ.get(nombre) for nombre in nombres}
        os.environ["META_APP_SECRET"] = "secreto-app-principal"
        os.environ["META_INSTAGRAM_APP_SECRET"] = "secreto-app-instagram"
        os.environ["META_INSTAGRAM_ACCOUNT_ID"] = "cuenta-instagram-directa"
        try:
            provider = ProveedorMetaMulticanal()
            provider._registrar_salida_bot(
                "cliente-instagram",
                "Respuesta enviada por el agente.",
                "mensaje-bot-1",
            )
            payload = {
                "object": "instagram",
                "entry": [{"messaging": [{
                    "sender": {"id": "cuenta-instagram-directa"},
                    "recipient": {"id": "cliente-instagram"},
                    "message": {
                        "mid": "mensaje-bot-1",
                        "is_echo": True,
                        "text": "Respuesta enviada por el agente.",
                    },
                }]}],
            }
            body = json.dumps(payload).encode()
            digest = hmac.new(
                b"secreto-app-instagram", body, hashlib.sha256
            ).hexdigest()
            mensajes = await provider.parsear_webhook(
                request_con_body(body, f"sha256={digest}")
            )

            self.assertEqual(mensajes, [])
        finally:
            for nombre, valor in anteriores.items():
                if valor is None:
                    os.environ.pop(nombre, None)
                else:
                    os.environ[nombre] = valor

    async def test_parsea_mensaje_del_webhook_directo_de_instagram(self):
        nombres = (
            "META_APP_SECRET",
            "META_INSTAGRAM_APP_SECRET",
            "META_INSTAGRAM_ACCOUNT_ID",
            "IG_PAGE_ID",
        )
        anteriores = {nombre: os.environ.get(nombre) for nombre in nombres}
        os.environ["META_APP_SECRET"] = "secreto-app-principal"
        os.environ["META_INSTAGRAM_APP_SECRET"] = "secreto-app-instagram"
        os.environ["META_INSTAGRAM_ACCOUNT_ID"] = "cuenta-instagram-directa"
        os.environ["IG_PAGE_ID"] = "cuenta-instagram-facebook"
        try:
            provider = ProveedorMetaMulticanal()
            payload = {
                "object": "instagram",
                "entry": [{"messaging": [{
                    "sender": {"id": "cliente-instagram"},
                    "recipient": {"id": "cuenta-instagram-directa"},
                    "referral": {
                        "source": "ADS",
                        "headline": "Cabezal de ducha con filtro",
                    },
                    "message": {
                        "mid": "mensaje-instagram-directo-1",
                        "text": "¿Dónde están ubicados?",
                    },
                }]}],
            }
            body = json.dumps(payload).encode()
            digest = hmac.new(
                b"secreto-app-instagram", body, hashlib.sha256
            ).hexdigest()
            mensajes = await provider.parsear_webhook(
                request_con_body(body, f"sha256={digest}")
            )

            self.assertEqual(len(mensajes), 1)
            self.assertEqual(mensajes[0].canal, "instagram")
            self.assertEqual(mensajes[0].telefono, "cliente-instagram")
            self.assertEqual(mensajes[0].texto, "¿Dónde están ubicados?")
            self.assertEqual(mensajes[0].contexto_producto, "Cabezal de ducha")
        finally:
            for nombre, valor in anteriores.items():
                if valor is None:
                    os.environ.pop(nombre, None)
                else:
                    os.environ[nombre] = valor

    async def test_parsea_audio_whatsapp(self):
        anterior = os.environ.get("META_APP_SECRET")
        os.environ["META_APP_SECRET"] = "secreto-de-prueba-no-real"
        try:
            provider = ProveedorMetaMulticanal()
            payload = {
                "entry": [{
                    "changes": [{
                        "field": "messages",
                        "value": {"messages": [{
                            "from": "56911111111",
                            "id": "wamid.audio-1",
                            "type": "audio",
                            "audio": {"id": "media-1", "mime_type": "audio/ogg"},
                        }]},
                    }],
                }],
            }
            body = json.dumps(payload).encode()
            digest = hmac.new(
                b"secreto-de-prueba-no-real", body, hashlib.sha256
            ).hexdigest()
            request = request_con_body(body, f"sha256={digest}")
            mensajes = await provider.parsear_webhook(request)
            self.assertEqual(len(mensajes), 1)
            self.assertEqual(mensajes[0].tipo, "audio")
            self.assertEqual(mensajes[0].media_id, "media-1")
        finally:
            if anterior is None:
                os.environ.pop("META_APP_SECRET", None)
            else:
                os.environ["META_APP_SECRET"] = anterior

    async def test_identifica_producto_desde_anuncio_click_a_whatsapp(self):
        anterior = os.environ.get("META_APP_SECRET")
        os.environ["META_APP_SECRET"] = "secreto-de-prueba-no-real"
        try:
            provider = ProveedorMetaMulticanal()
            payload = {
                "entry": [{
                    "changes": [{
                        "field": "messages",
                        "value": {"messages": [{
                            "from": "56911111111",
                            "id": "wamid.ad-1",
                            "type": "text",
                            "text": {"body": "Hello! Can I get more info on this?"},
                            "referral": {
                                "source_type": "ad",
                                "source_url": "https://fb.me/anuncio",
                                "headline": "¿Sigues pagando TV cable?",
                                "body": "Antena Digital Full HD 4K",
                            },
                        }]},
                    }],
                }],
            }
            body = json.dumps(payload).encode()
            digest = hmac.new(
                b"secreto-de-prueba-no-real", body, hashlib.sha256
            ).hexdigest()
            mensajes = await provider.parsear_webhook(
                request_con_body(body, f"sha256={digest}")
            )

            self.assertEqual(len(mensajes), 1)
            self.assertEqual(
                mensajes[0].contexto_producto,
                "Antena Digital Full HD 4K",
            )
        finally:
            if anterior is None:
                os.environ.pop("META_APP_SECRET", None)
            else:
                os.environ["META_APP_SECRET"] = anterior

    async def test_parsea_imagen_whatsapp_con_descripcion(self):
        anterior = os.environ.get("META_APP_SECRET")
        os.environ["META_APP_SECRET"] = "secreto-de-prueba-no-real"
        try:
            provider = ProveedorMetaMulticanal()
            payload = {
                "entry": [{
                    "changes": [{
                        "field": "messages",
                        "value": {"messages": [{
                            "from": "56911111111",
                            "id": "wamid.image-1",
                            "type": "image",
                            "image": {
                                "id": "media-image-1",
                                "mime_type": "image/jpeg",
                                "caption": "¿Esta conexión sirve?",
                            },
                        }]},
                    }],
                }],
            }
            body = json.dumps(payload).encode()
            digest = hmac.new(
                b"secreto-de-prueba-no-real", body, hashlib.sha256
            ).hexdigest()
            mensajes = await provider.parsear_webhook(
                request_con_body(body, f"sha256={digest}")
            )

            self.assertEqual(len(mensajes), 1)
            self.assertEqual(mensajes[0].tipo, "image")
            self.assertEqual(mensajes[0].media_id, "media-image-1")
            self.assertEqual(mensajes[0].texto, "¿Esta conexión sirve?")
        finally:
            if anterior is None:
                os.environ.pop("META_APP_SECRET", None)
            else:
                os.environ["META_APP_SECRET"] = anterior

    async def test_parsea_imagen_instagram_sin_duplicar_el_texto(self):
        nombres = (
            "META_APP_SECRET", "META_INSTAGRAM_ACCOUNT_ID", "IG_PAGE_ID"
        )
        anteriores = {nombre: os.environ.get(nombre) for nombre in nombres}
        os.environ["META_APP_SECRET"] = "secreto-de-prueba-no-real"
        os.environ["META_INSTAGRAM_ACCOUNT_ID"] = "cuenta-instagram"
        os.environ["IG_PAGE_ID"] = "pagina-instagram"
        try:
            provider = ProveedorMetaMulticanal()
            payload = {
                "entry": [{"messaging": [{
                    "sender": {"id": "cliente-instagram"},
                    "recipient": {"id": "cuenta-instagram"},
                    "message": {
                        "mid": "ig-image-1",
                        "text": "¿Me sirve esta conexión?",
                        "attachments": [{
                            "type": "image",
                            "payload": {
                                "url": "https://lookaside.fbsbx.com/imagen.jpg"
                            },
                        }],
                    },
                }]}],
            }
            body = json.dumps(payload).encode()
            digest = hmac.new(
                b"secreto-de-prueba-no-real", body, hashlib.sha256
            ).hexdigest()
            mensajes = await provider.parsear_webhook(
                request_con_body(body, f"sha256={digest}")
            )

            self.assertEqual(len(mensajes), 1)
            self.assertEqual(mensajes[0].tipo, "image")
            self.assertEqual(mensajes[0].canal, "instagram")
            self.assertEqual(mensajes[0].texto, "¿Me sirve esta conexión?")
        finally:
            for nombre, valor in anteriores.items():
                if valor is None:
                    os.environ.pop(nombre, None)
                else:
                    os.environ[nombre] = valor

    async def test_parsea_respuesta_manual_de_messenger_y_omite_echo_del_bot(self):
        nombres = (
            "META_APP_SECRET", "META_APP_ID", "META_INSTAGRAM_APP_ID", "FB_PAGE_ID"
        )
        anteriores = {nombre: os.environ.get(nombre) for nombre in nombres}
        os.environ["META_APP_SECRET"] = "secreto-de-prueba-no-real"
        os.environ["META_APP_ID"] = "app-escenciales"
        os.environ["META_INSTAGRAM_APP_ID"] = "instagram-app-escenciales"
        os.environ["FB_PAGE_ID"] = "pagina-escenciales"
        try:
            provider = ProveedorMetaMulticanal()
            payload = {
                "entry": [{"messaging": [
                    {
                        "sender": {"id": "pagina-escenciales"},
                        "recipient": {"id": "cliente-1"},
                        "message": {
                            "mid": "manual-messenger-1",
                            "is_echo": True,
                            "text": "Yo continúo atendiendo este caso.",
                        },
                    },
                    {
                        "sender": {"id": "pagina-escenciales"},
                        "recipient": {"id": "cliente-2"},
                        "message": {
                            "mid": "bot-messenger-1",
                            "is_echo": True,
                            "app_id": "app-escenciales",
                            "text": "Respuesta enviada por el bot.",
                        },
                    },
                    {
                        "sender": {"id": "pagina-escenciales"},
                        "recipient": {"id": "cliente-3"},
                        "message": {
                            "mid": "bot-instagram-1",
                            "is_echo": True,
                            "app_id": "instagram-app-escenciales",
                            "text": "Respuesta enviada por el bot de Instagram.",
                        },
                    },
                ]}],
            }
            body = json.dumps(payload).encode()
            digest = hmac.new(
                b"secreto-de-prueba-no-real", body, hashlib.sha256
            ).hexdigest()
            request = request_con_body(body, f"sha256={digest}")
            mensajes = await provider.parsear_webhook(request)

            self.assertEqual(len(mensajes), 1)
            self.assertTrue(mensajes[0].es_propio)
            self.assertEqual(mensajes[0].telefono, "cliente-1")
            self.assertEqual(mensajes[0].canal, "messenger")
            self.assertEqual(mensajes[0].tipo, "operator_echo")
        finally:
            for nombre, valor in anteriores.items():
                if valor is None:
                    os.environ.pop(nombre, None)
                else:
                    os.environ[nombre] = valor

    async def test_parsea_respuesta_manual_de_whatsapp_coexistente(self):
        anterior = os.environ.get("META_APP_SECRET")
        os.environ["META_APP_SECRET"] = "secreto-de-prueba-no-real"
        try:
            provider = ProveedorMetaMulticanal()
            payload = {
                "entry": [{
                    "changes": [{
                        "field": "smb_message_echoes",
                        "value": {"message_echoes": [{
                            "from": "56938663898",
                            "to": "56911111111",
                            "id": "wamid.manual-1",
                            "type": "text",
                            "text": {"body": "Yo sigo atendiendo este caso."},
                        }]},
                    }],
                }],
            }
            body = json.dumps(payload).encode()
            digest = hmac.new(
                b"secreto-de-prueba-no-real", body, hashlib.sha256
            ).hexdigest()
            request = request_con_body(body, f"sha256={digest}")
            mensajes = await provider.parsear_webhook(request)

            self.assertEqual(len(mensajes), 1)
            self.assertTrue(mensajes[0].es_propio)
            self.assertEqual(mensajes[0].telefono, "56911111111")
            self.assertEqual(mensajes[0].tipo, "operator_echo")
            self.assertEqual(mensajes[0].texto, "Yo sigo atendiendo este caso.")
        finally:
            if anterior is None:
                os.environ.pop("META_APP_SECRET", None)
            else:
                os.environ["META_APP_SECRET"] = anterior


class ConfiguracionTests(unittest.TestCase):
    def test_catalogo_se_inyecta_en_prompt(self):
        prompt = cargar_system_prompt("instagram")
        self.assertIn("Electroestimulador TENS", prompt)
        self.assertIn("Ducha Masajeadora Spa Pro", prompt)
        self.assertIn("Antena Digital Full HD 4K", prompt)
        self.assertIn("Instagram DM", prompt)
        self.assertIn("29990", prompt)
        self.assertIn("chilessentials.cl/products/maquina-electroestimulador", prompt)
        self.assertIn("Releasit COD", prompt)


if __name__ == "__main__":
    unittest.main()
