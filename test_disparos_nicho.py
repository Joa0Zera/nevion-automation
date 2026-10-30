"""Testes do nicho do contato gravado em disparos.nicho (worker_disparo.py / Disparador v2.py).
Sem rede, sem Supabase, sem Baileys: `requests` é trocado por um dublê (mesmo padrão de
test_worker_nome.py). Rodar: python -m unittest test_disparos_nicho -v"""
import sys
import types
import unittest
from unittest import mock

import worker_disparo as w  # também carrega "Disparador v2.py" como w.disp

for _f in (sys.stdout, sys.stderr):
    if hasattr(_f, 'reconfigure'):
        _f.reconfigure(encoding='utf-8', errors='replace')

URL, CHAVE = "https://exemplo.supabase.test", "chave-de-teste"
NUMERO = "+5511999999999"


class RequestsFalso(types.ModuleType):
    """Mesmo dublê de test_worker_nome.py: grava as chamadas, nunca fala com a rede."""
    def __init__(self):
        super().__init__("requests")
        self.chamadas = []

    def post(self, url, **kw):
        self.chamadas.append((url, kw))
        r = mock.Mock()
        r.status_code = 201
        r.raise_for_status.return_value = None
        return r


class Base(unittest.TestCase):
    def setUp(self):
        self.req = RequestsFalso()
        p = mock.patch.dict(sys.modules, {"requests": self.req})
        p.start()
        self.addCleanup(p.stop)
        p2 = mock.patch.object(w.disp, "_config_supabase", return_value=(URL, CHAVE))
        p2.start()
        self.addCleanup(p2.stop)

    def corpo(self, indice=-1):
        return self.req.chamadas[indice][1]["json"]


class TestNormalizarNicho(unittest.TestCase):
    """_normalizar_nicho_disparo() isolada — sem rede, sem mock."""

    def test_nicho_normal_passa_direto(self):
        self.assertEqual(w.disp._normalizar_nicho_disparo("personal_trainer"), "personal_trainer")

    def test_vazio_ou_nulo_vira_nulo(self):
        self.assertIsNone(w.disp._normalizar_nicho_disparo(""))
        self.assertIsNone(w.disp._normalizar_nicho_disparo(None))
        self.assertIsNone(w.disp._normalizar_nicho_disparo("   "))

    def test_tira_espaco_das_pontas_e_limita_a_60(self):
        bruto = "  " + ("nicho_muito_longo_demais_" * 5) + "  "  # bem acima de 60
        resultado = w.disp._normalizar_nicho_disparo(bruto)
        self.assertEqual(resultado, bruto.strip()[:60])


class TestRegistrarDisparoGravaNicho(Base):
    def test_nicho_valido_entra_no_corpo(self):
        w.disp.registrar_disparo_no_supabase(NUMERO, "copy_01", "QUER VER", "disparado", nicho="barbearia")
        self.assertEqual(self.corpo()["nicho"], "barbearia")

    def test_nicho_vazio_nao_entra_no_corpo(self):
        w.disp.registrar_disparo_no_supabase(NUMERO, "copy_01", "QUER VER", "disparado", nicho="")
        self.assertNotIn("nicho", self.corpo())

    def test_salvar_disparado_repassa_nicho(self):
        import os
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            with mock.patch.object(w.disp, "ARQUIVO_DISPARADOS", os.path.join(tmp, "disparados.json")):
                w.disp.salvar_disparado(NUMERO, "copy_01", "QUER VER", "disparado", nicho="manicure_lash")
        self.assertEqual(self.corpo()["nicho"], "manicure_lash")


class TestProcessarPedidoPassaNicho(Base):
    """Integração: processar_pedido() repassa o nicho que vem de montar_fila() pros dois
    pontos que tocam o Supabase (pré-escrita 'enviando' e registro final)."""

    def test_nicho_da_fila_chega_na_pre_escrita_e_no_registro_final(self):
        fila = [(NUMERO, "5511999999999", "Academia Tal", "personal_trainer")]
        with mock.patch.object(w.disp, "_config_baileys", return_value=("http://x", "tok")), \
             mock.patch.object(w.disp, "_teto_maximo", return_value=30), \
             mock.patch.object(w.disp, "montar_fila", return_value={"fila": fila}), \
             mock.patch.object(w.disp, "agora_brasilia", return_value="AGORA"), \
             mock.patch.object(w.disp, "envios_na_janela", return_value=(0, None)), \
             mock.patch.object(w.disp, "pre_teste_baileys", return_value=(True, "ok")), \
             mock.patch.object(w.disp, "dentro_da_janela", return_value=True), \
             mock.patch.object(w.disp, "enviar_via_baileys", return_value=(w.disp.ENVIADO, "HTTP 200", "")), \
             mock.patch.object(w.disp, "registrar_conversa"), \
             mock.patch.object(w, "le"):
            resultado = w.processar_pedido({"quantidade": 1}, URL, CHAVE)

        self.assertEqual(resultado["enviados"], 1)
        self.assertEqual(self.corpo(0)["nicho"], "personal_trainer")  # pré-escrita 'enviando'
        self.assertEqual(self.corpo(1)["nicho"], "personal_trainer")  # registro final
        self.assertEqual(len(self.req.chamadas), 2)


class RequestsSemColunaNicho(RequestsFalso):
    """Postgres/PostgREST sem a coluna: 400 quando o corpo traz 'nicho'; aceita sem ele."""
    def post(self, url, **kw):
        self.chamadas.append((url, kw))
        r = mock.Mock()
        if "nicho" in kw["json"]:
            r.status_code = 400
            r.text = '{"code":"42703","message":"column disparos.nicho does not exist"}'
        else:
            r.status_code = 201
            r.text = ""
        r.raise_for_status.return_value = None
        return r


class TestColunaNichoAindaNaoCriada(unittest.TestCase):
    """Antes da migração o registro do disparo não pode ser perdido: o limite de 24h conta linhas de disparos."""

    def test_sem_a_coluna_regrava_sem_nicho_e_devolve_true(self):
        req = RequestsSemColunaNicho()
        with mock.patch.dict(sys.modules, {"requests": req}), \
             mock.patch.object(w.disp, "_config_supabase", return_value=(URL, CHAVE)):
            ok = w.disp.registrar_disparo_no_supabase(NUMERO, "copy_01", "", "disparado", "Clínica Bella Pele", "barbearia")
        self.assertTrue(ok)
        self.assertEqual(len(req.chamadas), 2)
        self.assertIn("nicho", req.chamadas[0][1]["json"])
        regravado = req.chamadas[1][1]["json"]
        self.assertNotIn("nicho", regravado)
        self.assertEqual(regravado["nome"], "Clínica Bella Pele")
        self.assertEqual(regravado["status"], "disparado")

    def test_com_a_coluna_grava_uma_vez_so_com_o_nicho(self):
        req = RequestsFalso()
        with mock.patch.dict(sys.modules, {"requests": req}), \
             mock.patch.object(w.disp, "_config_supabase", return_value=(URL, CHAVE)):
            self.assertTrue(w.disp.registrar_disparo_no_supabase(NUMERO, "copy_01", "", "disparado", None, "barbearia"))
        self.assertEqual(len(req.chamadas), 1)
        self.assertEqual(req.chamadas[0][1]["json"]["nicho"], "barbearia")

    def test_outro_erro_400_nao_e_regravado(self):
        class Recusa(RequestsFalso):
            def post(self, url, **kw):
                self.chamadas.append((url, kw))
                r = mock.Mock()
                r.status_code = 400
                r.text = '{"message":"valor invalido para status"}'
                return r
        req = Recusa()
        with mock.patch.dict(sys.modules, {"requests": req}), \
             mock.patch.object(w.disp, "_config_supabase", return_value=(URL, CHAVE)):
            self.assertFalse(w.disp.registrar_disparo_no_supabase(NUMERO, "copy_01", "", "disparado", None, "barbearia"))
        self.assertEqual(len(req.chamadas), 1)


if __name__ == "__main__":
    unittest.main()
