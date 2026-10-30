"""Teste: marcar_concluido() não pode sobrescrever um pedido alterado por fora (ex.: cancelado
pelo dashboard) enquanto processava (worker_disparo.py). Sem rede, sem Supabase, sem Baileys:
`requests` é trocado por um dublê (mesmo padrão de test_worker_status.py/test_worker_nome.py).
Rodar: python -m unittest test_worker_cancelamento -v"""
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


class RequestsFaloPatch(types.ModuleType):
    """Dublê de `requests` só com PATCH, pra testar marcar_concluido isoladamente."""
    def __init__(self, linhas_devolvidas):
        super().__init__("requests")
        self.chamadas = []
        self._linhas = linhas_devolvidas

    def patch(self, url, **kw):
        self.chamadas.append((url, kw))
        r = mock.Mock()
        r.raise_for_status.return_value = None
        r.json.return_value = self._linhas
        return r


class TestMarcarConcluidoNaoSobrescreveCancelamento(unittest.TestCase):
    def test_patch_e_condicional_a_executando(self):
        req = RequestsFaloPatch(linhas_devolvidas=[{"id": 42, "status": "concluido"}])
        with mock.patch.dict(sys.modules, {"requests": req}):
            concluiu = w.marcar_concluido(URL, CHAVE, 42, {"enviados": 1})
        self.assertTrue(concluiu)
        self.assertEqual(req.chamadas[0][1]["params"]["status"], "eq.executando")

    def test_pedido_cancelado_por_fora_nao_e_sobrescrito(self):
        """Simula o pedido tendo sido cancelado (status virou algo != 'executando', ex.: 'erro'
        — o que o cancelamento manual do dashboard grava) enquanto processava: o PATCH
        condicional não acha a linha (0 devolvidas), e marcar_concluido devolve False em vez
        de levantar ou fingir que concluiu."""
        req = RequestsFaloPatch(linhas_devolvidas=[])
        with mock.patch.dict(sys.modules, {"requests": req}):
            concluiu = w.marcar_concluido(URL, CHAVE, 42, {"enviados": 1})
        self.assertFalse(concluiu)

    def test_ciclo_unico_so_loga_quando_marcar_concluido_devolve_false(self):
        """Integração com ciclo_unico: quando marcar_concluido devolve False (pedido cancelado
        por fora), o ciclo não levanta, não chama marcar_erro, e segue em frente normalmente."""
        with mock.patch.object(w.disp, "dentro_da_janela", return_value=True), \
             mock.patch.object(w, "gravar_status"), \
             mock.patch.object(w, "buscar_pedido_pendente", return_value={"id": 7, "quantidade": 3, "criado_em": "2026-01-01T00:00:00Z"}), \
             mock.patch.object(w, "marcar_executando", return_value=True), \
             mock.patch.object(w, "processar_pedido", return_value={"enviados": 1}), \
             mock.patch.object(w, "marcar_concluido", return_value=False) as concluido_falso, \
             mock.patch.object(w, "marcar_erro") as erro_falso:
            w.ciclo_unico(URL, CHAVE, 72)
        concluido_falso.assert_called_once()
        erro_falso.assert_not_called()

    def test_ciclo_unico_segue_normal_quando_marcar_concluido_devolve_true(self):
        """Regressão: o caminho feliz (pedido terminou 'executando' de verdade) continua
        funcionando igual, sem o aviso de 'alterado por fora'."""
        with mock.patch.object(w.disp, "dentro_da_janela", return_value=True), \
             mock.patch.object(w, "gravar_status"), \
             mock.patch.object(w, "buscar_pedido_pendente", return_value={"id": 7, "quantidade": 3, "criado_em": "2026-01-01T00:00:00Z"}), \
             mock.patch.object(w, "marcar_executando", return_value=True), \
             mock.patch.object(w, "processar_pedido", return_value={"enviados": 1}), \
             mock.patch.object(w, "marcar_concluido", return_value=True) as concluido_verdadeiro, \
             mock.patch.object(w, "marcar_erro") as erro_falso:
            w.ciclo_unico(URL, CHAVE, 72)
        concluido_verdadeiro.assert_called_once()
        erro_falso.assert_not_called()


if __name__ == "__main__":
    unittest.main()
