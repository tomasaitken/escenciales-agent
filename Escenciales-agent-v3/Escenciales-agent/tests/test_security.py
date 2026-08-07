import hashlib
import hmac
import json
import os
import unittest

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


class ParseoAudioTests(unittest.IsolatedAsyncioTestCase):
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

    async def test_parsea_respuesta_manual_de_messenger_y_omite_echo_del_bot(self):
        nombres = ("META_APP_SECRET", "META_APP_ID", "FB_PAGE_ID")
        anteriores = {nombre: os.environ.get(nombre) for nombre in nombres}
        os.environ["META_APP_SECRET"] = "secreto-de-prueba-no-real"
        os.environ["META_APP_ID"] = "app-escenciales"
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
