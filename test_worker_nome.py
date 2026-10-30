"""Testes do nome do lead gravado em disparos.nome (worker_disparo.py / Disparador v2.py).
Sem rede, sem Supabase, sem Baileys: `requests` é trocado por um dublê (mesmo padrão de
test_worker_status.py). Rodar: python -m unittest test_worker_nome -v"""
import json
import os
import sys
import tempfile
import types
import unittest
from unittest import mock

import worker_disparo as w  # também carrega "Disparador v2.py" como w.disp

# o worker imprime emojis; no Windows o console padrão (cp1252) não consegue
for _f in (sys.stdout, sys.stderr):
    if hasattr(_f, 'reconfigure'):
        _f.reconfigure(encoding='utf-8', errors='replace')

URL, CHAVE = "https://exemplo.supabase.test", "chave-de-teste"
NUMERO = "+5511999999999"


class RequestsFalso(types.ModuleType):
    """Mesmo dublê de test_worker_status.py: grava as chamadas, nunca fala com a rede."""
    def __init__(self, falhar=False):
        super().__init__("requests")
        self.chamadas, self.falhar = [], falhar

    def post(self, url, **kw):
        self.chamadas.append((url, kw))
        if self.falhar:
            raise ConnectionError("supabase fora do ar")
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


class TestNormalizarNome(unittest.TestCase):
    """_normalizar_nome_disparo() isolada — sem rede, sem mock."""

    def test_nome_normal_passa_direto(self):
        self.assertEqual(w.disp._normalizar_nome_disparo("Clínica Bella Pele"), "Clínica Bella Pele")

    def test_placeholder_lead_vira_nulo(self):
        self.assertIsNone(w.disp._normalizar_nome_disparo("Lead"))

    def test_vazio_nulo_ou_so_espaco_vira_nulo(self):
        self.assertIsNone(w.disp._normalizar_nome_disparo(""))
        self.assertIsNone(w.disp._normalizar_nome_disparo(None))
        self.assertIsNone(w.disp._normalizar_nome_disparo("   "))

    def test_tira_espaco_das_pontas_e_limita_a_120(self):
        bruto = "  " + ("Clínica Muito Longa Demais " * 10) + "  "  # bem acima de 120
        resultado = w.disp._normalizar_nome_disparo(bruto)
        self.assertEqual(resultado, bruto.strip()[:120])
        self.assertLessEqual(len(resultado), 120)
        self.assertEqual(resultado, resultado.strip())


class TestRegistrarComNome(Base):
    """registrar_disparo_no_supabase(..., nome) — o corpo que de fato sai pro Supabase."""

    def test_grava_nome_quando_presente(self):
        w.disp.registrar_disparo_no_supabase(NUMERO, "copy_01", "QUER VER", "disparado", "Clínica Bella Pele")
        self.assertEqual(self.corpo()["nome"], "Clínica Bella Pele")

    def test_nao_inclui_chave_nome_quando_e_o_placeholder_lead(self):
        w.disp.registrar_disparo_no_supabase(NUMERO, "copy_01", "QUER VER", "disparado", "Lead")
        self.assertNotIn("nome", self.corpo())

    def test_nao_inclui_chave_nome_quando_vazio_ou_ausente(self):
        w.disp.registrar_disparo_no_supabase(NUMERO, "copy_01", "QUER VER", "disparado", "")
        self.assertNotIn("nome", self.corpo())
        w.disp.registrar_disparo_no_supabase(NUMERO, "copy_01", "QUER VER", "disparado")  # nome nem passado
        self.assertNotIn("nome", self.corpo())

    def test_corpo_enviado_ja_vem_normalizado(self):
        bruto = "  " + ("X" * 200) + "  "
        w.disp.registrar_disparo_no_supabase(NUMERO, "copy_01", "QUER VER", "disparado", bruto)
        self.assertEqual(self.corpo()["nome"], ("X" * 200)[:120])

    def test_ausencia_da_chave_e_o_mecanismo_que_protege_o_upsert(self):
        """Como 'nome' simplesmente não aparece no corpo quando é nulo, o upsert
        (merge-duplicates) nunca apaga um nome já gravado -- mesmo mecanismo que já protege
        disparado_em num reenvio (ver comentário em registrar_disparo_no_supabase)."""
        w.disp.registrar_disparo_no_supabase(NUMERO, "copy_01", "QUER VER", "disparado", None)
        self.assertNotIn("nome", self.corpo())
        self.assertIn("merge-duplicates", self.req.chamadas[-1][1]["headers"]["Prefer"])

    def test_falha_do_supabase_nao_levanta_mesmo_com_nome(self):
        self.req.falhar = True
        resultado = w.disp.registrar_disparo_no_supabase(NUMERO, "copy_01", "QUER VER", "disparado", "Clínica X")
        self.assertFalse(resultado)  # nunca levanta, só devolve False


class TestSalvarDisparadoComNome(Base):
    """salvar_disparado(..., nome): nome NUNCA entra no disparados.json local, só no Supabase."""

    def setUp(self):
        super().setUp()
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        arquivo = os.path.join(tmp.name, "disparados.json")
        p = mock.patch.object(w.disp, "ARQUIVO_DISPARADOS", arquivo)
        p.start()
        self.addCleanup(p.stop)
        self.arquivo = arquivo

    def _ler(self):
        with open(self.arquivo, encoding="utf-8") as f:
            return json.load(f)

    def test_disparados_json_nao_ganha_campo_nome(self):
        w.disp.salvar_disparado(NUMERO, "copy_01", "QUER VER", "disparado", "Clínica Bella Pele")
        entrada = self._ler()[NUMERO]
        self.assertNotIn("nome", entrada)
        self.assertEqual(set(entrada), {"copy_id", "cta", "status", "data", "respondeu"})

    def test_nome_chega_no_supabase_via_salvar_disparado(self):
        w.disp.salvar_disparado(NUMERO, "copy_01", "QUER VER", "disparado", "Clínica Bella Pele")
        self.assertEqual(self.corpo()["nome"], "Clínica Bella Pele")

    def test_upsert_com_nome_nulo_nao_apaga_nome_existente(self):
        """Simula o reenvio: primeira chamada grava o nome; a segunda (sem nome) não manda a
        chave 'nome' no corpo -- então, no upsert de verdade, a coluna existente fica intacta."""
        w.disp.salvar_disparado(NUMERO, "copy_01", "QUER VER", "disparado", "Clínica Bella Pele")
        self.assertEqual(self.corpo()["nome"], "Clínica Bella Pele")
        w.disp.salvar_disparado(NUMERO, "copy_02", "PÁGINA", "sem_whatsapp", None)
        self.assertNotIn("nome", self.corpo())  # segunda chamada não ameaça o nome já gravado

    def test_envio_e_registro_continuam_se_a_gravacao_do_nome_falhar(self):
        """Mesmo com a chamada ao Supabase falhando (nome incluso), disparados.json ainda é
        gravado e salvar_disparado ainda devolve True -- a falha nunca derruba o resto."""
        self.req.falhar = True
        gravou_json = w.disp.salvar_disparado(NUMERO, "copy_01", "QUER VER", "disparado", "Clínica Bella Pele")
        self.assertTrue(gravou_json)
        self.assertEqual(self._ler()[NUMERO]["status"], "disparado")


class TestProcessarPedidoPassaNome(Base):
    """Integração: processar_pedido() de fato repassa o nome que vem de montar_fila() (sem
    nova consulta ao LeadEngine) pros dois pontos que tocam o Supabase."""

    def test_nome_da_fila_chega_na_pre_escrita_e_no_registro_final(self):
        fila = [(NUMERO, "5511999999999", "Clínica Bella Pele", "")]
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
        # 1ª chamada ao Supabase = a pré-escrita 'enviando', já com o nome
        self.assertEqual(self.corpo(0)["nome"], "Clínica Bella Pele")
        # 2ª chamada = o registro final (via salvar_disparado), também com o nome
        self.assertEqual(self.corpo(1)["nome"], "Clínica Bella Pele")
        self.assertEqual(len(self.req.chamadas), 2)


if __name__ == "__main__":
    unittest.main()
