import os
import unittest

from agent.legal import eliminacion_datos, politica_privacidad, terminos_servicio


class PaginasLegalesTests(unittest.TestCase):
    def test_privacidad_declara_ia_retencion_y_contacto(self):
        anterior = os.environ.get("DATA_RETENTION_DAYS")
        os.environ["DATA_RETENTION_DAYS"] = "45"
        try:
            response = politica_privacidad()
            contenido = response.body.decode("utf-8")
            self.assertEqual(response.status_code, 200)
            self.assertIn("inteligencia artificial", contenido)
            self.assertIn("45", contenido)
            self.assertIn("contacto@chilessentials.cl", contenido)
            self.assertIn("OpenAI", contenido)
        finally:
            if anterior is None:
                os.environ.pop("DATA_RETENTION_DAYS", None)
            else:
                os.environ["DATA_RETENTION_DAYS"] = anterior

    def test_terminos_incluyen_condiciones_comerciales_y_seguridad_tens(self):
        contenido = terminos_servicio().body.decode("utf-8")
        self.assertIn("despacho gratuito", contenido)
        self.assertIn("pago contra", contenido)
        self.assertIn("marcapasos", contenido)
        self.assertIn("legislación chilena", contenido)

    def test_eliminacion_entrega_procedimiento_claro(self):
        contenido = eliminacion_datos().body.decode("utf-8")
        self.assertIn("Solicitud de eliminación de datos", contenido)
        self.assertIn("WhatsApp, Messenger o Instagram", contenido)
        self.assertIn("contacto@chilessentials.cl", contenido)


if __name__ == "__main__":
    unittest.main()
