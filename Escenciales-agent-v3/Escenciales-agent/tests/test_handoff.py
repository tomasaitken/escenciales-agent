import unittest

from agent.handoff import detectar_handoff, mensaje_handoff, respuesta_promete_handoff


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

    def test_detecta_pedido_asistido_con_ortografia_muy_basica(self):
        self.assertEqual(
            detectar_handoff("no c comprar aseme el pedido de la antena xfa"),
            "pedido_asistido",
        )

    def test_detecta_casos_criticos_aunque_estan_mal_escritos(self):
        ejemplos = {
            "tengo marcapaso puedo usar el aparato?": "seguridad_tens",
            "estoi enbarasa me sirve el tens pal dolor": "seguridad_tens",
            "mi pedido no yega y no se ke aser": "pedido_existente",
            "borren mis datos y mi numero": "privacidad",
            "soy de peru me la mandan?": "destino_especial",
            "tiene garantia?": "condicion_no_confirmada",
            "me quiero morir": "emergencia",
        }
        for texto, motivo in ejemplos.items():
            with self.subTest(texto=texto):
                self.assertEqual(detectar_handoff(texto), motivo)

    def test_detecta_promesa_de_apoyo_humano_en_respuesta_modelo(self):
        ejemplos = [
            "Una persona del equipo seguirá contigo por este chat.",
            "Voy a dejar tu consulta marcada para revisión.",
            "Esto lo revisamos con el equipo.",
        ]
        for texto in ejemplos:
            with self.subTest(texto=texto):
                self.assertTrue(respuesta_promete_handoff(texto))

        self.assertFalse(
            respuesta_promete_handoff("La antena cuesta $22.990 y el envío es gratis.")
        )


if __name__ == "__main__":
    unittest.main()
