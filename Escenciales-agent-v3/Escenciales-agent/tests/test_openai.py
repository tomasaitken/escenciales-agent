import json
import os
import unittest
from unittest.mock import patch

import httpx
from openai import AsyncOpenAI

from agent.brain import generar_respuesta


class OpenAIResponsesTests(unittest.IsolatedAsyncioTestCase):
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
