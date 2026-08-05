import unittest

from agent.handoff import detectar_handoff, mensaje_handoff


class HandoffTests(unittest.TestCase):
    def test_detecta_pedido_asistido(self):
        ejemplos = [
            "No sé comprar por la página, ¿me pueden hacer el pedido?",
            "Ayúdame a comprar por favor",
            "¿Me llenan el formulario?",
            "Quiero comprar por WhatsApp",
        ]
        for texto in ejemplos:
            with self.subTest(texto=texto):
                self.assertEqual(detectar_handoff(texto), "pedido_asistido")

    def test_no_deriva_consulta_comercial_normal(self):
        ejemplos = [
            "¿Dónde se compra?",
            "¿Cuánto cuesta la antena?",
            "¿Cómo funciona la ducha?",
            "¿Hacen envíos a Coquimbo?",
        ]
        for texto in ejemplos:
            with self.subTest(texto=texto):
                self.assertIsNone(detectar_handoff(texto))

    def test_detecta_seguridad_tens(self):
        self.assertEqual(
            detectar_handoff("Tengo marcapasos, ¿puedo usar el TENS?"),
            "seguridad_tens",
        )

    def test_mensaje_pedido_protege_credenciales(self):
        mensaje = mensaje_handoff("pedido_asistido")
        self.assertIn("persona del equipo", mensaje)
        self.assertIn("contraseñas", mensaje)


if __name__ == "__main__":
    unittest.main()
