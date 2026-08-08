import json
import os
import unittest
from unittest.mock import patch

import httpx
from openai import AsyncOpenAI

from agent.brain import cargar_system_prompt, generar_respuesta, sanitizar_respuesta


class OpenAIResponsesTests(unittest.IsolatedAsyncioTestCase):
    def test_prompt_exige_un_tono_humano_y_no_burocratico(self):
        prompt = cargar_system_prompt("whatsapp")

        self.assertIn("CONVERSACIÓN HUMANA — REGLA CENTRAL", prompt)
        self.assertIn('Nunca digas "según la ficha"', prompt)
        self.assertIn("no como un manual, catálogo o call center", prompt)
        self.assertIn("responde con honestidad", prompt)
        self.assertIn("Canal activo: WhatsApp", prompt)
        self.assertIn("lugar sin obstáculos", prompt)
        self.assertIn("El envío es gratis", prompt)
        self.assertIn("al momento de recibir el producto", prompt)
        self.assertIn("emoji cálido", prompt)
        self.assertIn("Máximo uno por mensaje", prompt)

    def test_prompt_no_expone_direccion_y_fija_ubicacion_aprobada(self):
        prompt = cargar_system_prompt("instagram")

        self.assertNotIn("Juan XXIII", prompt)
        self.assertNotIn("5560", prompt)
        self.assertIn('responde únicamente: "Estamos ubicados', prompt)
        self.assertIn('en Santiago de Chile"', prompt)
        self.assertIn("envíos a todo Chile y también al extranjero", prompt)

    def test_prompt_mantiene_foco_en_el_producto_consultado(self):
        prompt = cargar_system_prompt("messenger")

        self.assertIn("FOCO EN EL PRODUCTO — REGLA OBLIGATORIA", prompt)
        self.assertIn("responde exclusivamente", prompt)
        self.assertIn("No menciones, enumeres, recomiendes, compares ni ofrezcas", prompt)
        self.assertIn("Solo puedes hablar de otros productos si el cliente pide", prompt)
        self.assertIn("No hagas venta cruzada", prompt)
        self.assertIn("Producto identificado desde el anuncio", prompt)
        self.assertIn("nunca preguntes cuál le interesa", prompt)
        self.assertIn("No menciones la marca interna", prompt)
        self.assertIn("ENLACE DE COMPRA EN SEGUNDO MENSAJE", prompt)
        self.assertIn("no incluyas ninguna URL", prompt)

    def test_prompt_incorpora_respuestas_probadas_sin_volverse_guion(self):
        prompt = cargar_system_prompt("whatsapp")

        self.assertIn("PATRONES COMERCIALES VALIDADOS POR EL EQUIPO", prompt)
        self.assertIn("nunca como respuestas predeterminadas", prompt)
        self.assertIn("3 a 5 días", prompt)
        self.assertIn("url_compra", prompt)
        self.assertIn("TVN", prompt)
        self.assertIn("zonas rurales", prompt)
        self.assertIn("conexión estándar", prompt)
        self.assertIn("NO CONFIRMADO", prompt)
        self.assertIn("No envíes seguimientos proactivos", prompt)
        self.assertIn("no prometer una comprobación", prompt)

    def test_bloquea_direccion_exacta_en_la_salida(self):
        respuesta = sanitizar_respuesta(
            "Estamos en calle Juan XXIII 5560, Santiago."
        )

        self.assertNotIn("Juan XXIII", respuesta)
        self.assertNotIn("5560", respuesta)
        self.assertIn("Santiago de Chile", respuesta)
        self.assertIn("todo Chile", respuesta)
        self.assertIn("extranjero", respuesta)

    def test_prompt_adapta_respuesta_a_baja_alfabetizacion(self):
        prompt = cargar_system_prompt("whatsapp")

        self.assertIn("CLIENTES QUE NECESITAN MÁXIMA SIMPLICIDAD", prompt)
        self.assertIn("Nunca corrijas, ridiculices", prompt)
        self.assertIn("una sola acción por vez", prompt)
        self.assertIn("Escribe solamente en español", prompt)

    def test_elimina_escritura_no_latina_accidental(self):
        respuesta = sanitizar_respuesta("Aprieta el botón; հետո completas tus datos.")

        self.assertNotIn("հետո", respuesta)
        self.assertIn("completas tus datos", respuesta)

    async def test_usa_responses_api_y_modelo_configurado(self):
        async def handler(request: httpx.Request) -> httpx.Response:
            self.assertEqual(request.url.path, "/v1/responses")
            body = json.loads(request.content)
            self.assertEqual(body["model"], "gpt-5.6-terra")
            self.assertEqual(body["reasoning"]["effort"], "low")
            self.assertEqual(body["safety_identifier"], "esc_prueba")
            self.assertFalse(body["store"])
            return httpx.Response(
                200,
                request=request,
                json={
                    "id": "resp_test",
                    "object": "response",
                    "created_at": 1,
                    "status": "completed",
                    "model": "gpt-5.6-terra",
                    "output": [{
                        "id": "msg_test",
                        "type": "message",
                        "status": "completed",
                        "role": "assistant",
                        "content": [{
                            "type": "output_text",
                            "text": "El TENS cuesta $29.990.",
                            "annotations": [],
                        }],
                    }],
                    "usage": {
                        "input_tokens": 10,
                        "output_tokens": 6,
                        "total_tokens": 16,
                    },
                    "error": None,
                    "incomplete_details": None,
                    "metadata": {},
                },
            )

        http_client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        client = AsyncOpenAI(api_key="test", http_client=http_client)
        try:
            with patch.dict(os.environ, {
                "OPENAI_API_KEY": "test",
                "OPENAI_MODEL": "gpt-5.6-terra",
                "OPENAI_REASONING_EFFORT": "low",
            }), patch("agent.brain.AsyncOpenAI", return_value=client):
                respuesta = await generar_respuesta(
                    "¿Cuánto cuesta el TENS?",
                    [],
                    safety_identifier="esc_prueba",
                )
            self.assertEqual(respuesta, "El TENS cuesta $29.990.")
        finally:
            await client.close()


if __name__ == "__main__":
    unittest.main()
