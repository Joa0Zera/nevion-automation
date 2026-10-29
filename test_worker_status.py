"""Testes do sinal de vida do worker (worker_status). Sem rede, sem Supabase, sem Baileys, sem WhatsApp:
`requests` e todas as chamadas ao banco/Baileys são trocadas por dublês. Rodar: python -m unittest test_worker_status -v"""
import sys
import types
import unittest
from unittest import mock

import worker_disparo as w

# o worker imprime emojis; no Windows o console padrão (cp1252) não consegue
for _f in (sys.stdout, sys.stderr):
    if hasattr(_f, 'reconfigure'):
        _f.reconfigure(encoding='utf-8', errors='replace')

URL, CHAVE = "https://exemplo.supabase.test", "chave-de-teste"


class RequestsFalso(types.ModuleType):
    def __init__(self, falhar=False):
        super().__init__("requests")
        self.chamadas, self.falhar = [], falhar

    def post(self, url, **kw):
        self.chamadas.append((url, kw))
        if self.falhar:
            raise ConnectionError("supabase fora do ar")
        r = mock.Mock()
        r.raise_for_status.return_value = None
        return r


def fases(req):
    return [kw["json"]["fase"] for _, kw in req.chamadas]


class Base(unittest.TestCase):
    def setUp(self):
        w._estado_sinal.update(fase=w.FASE_AGUARDANDO, detalhe=None, erro_em=None, processando=False)
        self.req = RequestsFalso()
        p = mock.patch.dict(sys.modules, {"requests": self.req})
        p.start()
        self.addCleanup(p.stop)


class TestGravarStatus(Base):
    def test_upsert_com_fase_e_sinal(self):
        self.assertTrue(w.gravar_status(URL, CHAVE, w.FASE_ENVIANDO, "pedido #7"))
        url, kw = self.req.chamadas[0]
        self.assertEqual(url, f"{URL}/rest/v1/worker_status")
        self.assertEqual(kw["params"], {"on_conflict": "nome"})
        self.assertIn("merge-duplicates", kw["headers"]["Prefer"])
        corpo = kw["json"]
        self.assertEqual((corpo["nome"], corpo["fase"], corpo["detalhe"]), ("disparo", "enviando", "pedido #7"))
        self.assertTrue(corpo["ultimo_sinal"] and corpo["atualizado_em"])

    def test_falha_do_supabase_nao_levanta(self):
        self.req.falhar = True
        self.assertFalse(w.gravar_status(URL, CHAVE, w.FASE_AGUARDANDO))


class TestFases(Base):
    def ciclo(self, dentro=True, pedido=None, processar=None):
        pegos = []
        with mock.patch.object(w.disp, "dentro_da_janela", return_value=dentro), \
             mock.patch.object(w, "buscar_pedido_pendente", return_value=pedido), \
             mock.patch.object(w, "marcar_executando", return_value=True), \
             mock.patch.object(w, "marcar_concluido"), mock.patch.object(w, "marcar_erro") as erro, \
             mock.patch.object(w, "processar_pedido", side_effect=processar or (lambda *a: {"enviados": 1})):
            w.ciclo_unico(URL, CHAVE, 72)
            pegos.append(erro)
        return pegos[0]

    def test_fora_da_janela(self):
        self.ciclo(dentro=False)
        self.assertEqual(fases(self.req), ["fora_da_janela"])

    def test_aguardando_pedido(self):
        self.ciclo()
        self.assertEqual(fases(self.req), ["aguardando_pedido"])

    def test_enviando_quando_ha_pedido(self):
        self.ciclo(pedido={"id": 7, "quantidade": 3})
        self.assertEqual(fases(self.req), ["aguardando_pedido", "enviando"])
        self.assertEqual(self.req.chamadas[1][1]["json"]["detalhe"], "pedido #7")
        self.assertFalse(w._estado_sinal["processando"])

    def test_erro_do_pre_teste_do_baileys_com_motivo_e_persiste(self):
        def falha(*a):
            raise w.disp.ErroDeConfiguracao("pré-teste do Baileys falhou: conexão recusada — o Baileys está parado")
        self.ciclo(pedido={"id": 8, "quantidade": 3}, processar=falha)
        ultimo = self.req.chamadas[-1][1]["json"]
        self.assertEqual(ultimo["fase"], "erro")
        self.assertIn("conexão recusada", ultimo["detalhe"])
        self.ciclo()  # ciclo seguinte, sem pedido: o erro recente ainda vale
        self.assertEqual(fases(self.req)[-1], "erro")
        w._estado_sinal["erro_em"] -= w.ERRO_PERSISTE_SEGUNDOS + 1
        self.ciclo()
        self.assertEqual(fases(self.req)[-1], "aguardando_pedido")

    def test_outro_erro_nao_vira_fase_erro_do_baileys(self):
        def falha(*a):
            raise RuntimeError("outra coisa")
        self.ciclo(pedido={"id": 9, "quantidade": 3}, processar=falha)
        self.assertNotIn("erro", fases(self.req))


class TestLacoSemSupabase(Base):
    def test_laco_continua_quando_a_gravacao_falha(self):
        self.req.falhar = True
        consultas = []
        with mock.patch.object(w.disp, "_config_supabase", return_value=(URL, CHAVE)), \
             mock.patch.object(w.disp, "dentro_da_janela", return_value=True), \
             mock.patch.object(w.disp, "esperar"), \
             mock.patch.object(w, "buscar_pedido_pendente", side_effect=lambda *a: consultas.append(1)):
            codigo = w.rodar_loop(20, 72, max_ciclos=3)
        self.assertEqual(codigo, 0)
        self.assertEqual(len(consultas), 3, "o laço rodou todos os ciclos")
        self.assertEqual(len(self.req.chamadas), 3, "tentou gravar o sinal em cada ciclo")


if __name__ == "__main__":
    unittest.main()
