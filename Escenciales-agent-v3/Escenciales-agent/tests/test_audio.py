import os
import unittest
from unittest.mock import patch

import httpx
from openai import AsyncOpenAI

from agent.audio import transcribir_audio


class TranscripcionTests(unittest.IsolatedAsyncioTestCase):
    async def test_envia_audio_a_openai_sin_guardarlo(self):
        async def handler(request: httpx.Request) -> httpx.Response:
            self.assertEqual(request.url.path, "/v1/audio/transcriptions")
            self.assertIn(b'gpt-transcribe', request.content)
            self.assertIn(b'name="language"', request.content)
            self.assertIn(b'es', request.content)
            return httpx.Response(200, request=request, json={"text": "Quiero la antena."})

        http_client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        client = AsyncOpenAI(api_key="test", http_client=http_client)
        try:
            with patch.dict(os.environ, {
                "OPENAI_API_KEY": "test",
                "OPENAI_TRANSCRIBE_MODEL": "gpt-transcribe",
            }), patch("agent.audio.AsyncOpenAI", return_value=client):
                texto = await transcribir_audio(b"RIFF-audio-de-prueba", "audio/wav")
            self.assertEqual(texto, "Quiero la antena.")
        finally:
            await client.close()

    async def test_rechaza_formato_desconocido(self):
        with self.assertRaises(ValueError):
            await transcribir_audio(b"datos", "application/octet-stream")


if __name__ == "__main__":
    unittest.main()
