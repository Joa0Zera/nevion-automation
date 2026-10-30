"""Teste: um INCERTO isolado não deve encerrar processar_pedido() inteiro (worker_disparo.py)
— só uma sequência (contando junto com FALHOU no mesmo MAX_FALHAS_SEGUIDAS) para o lote.
Sem rede, sem Supabase, sem Baileys: `requests` é trocado por um dublê (mesmo padrão de
test_worker_status.py/test_worker_nome.py). Rodar: python -m unittest test_worker_incerto -v"""
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
FILA = [(f"+55119999900{i:02d}", f"5511999990{i:03d}", f"Lead {i}", "") for i in range(6)]


class RequestsFaloPost(types.ModuleType):
    """Dublê de `requests` só com POST (registrar_disparo_no_supabase/salvar_disparado usam
    POST com upsert) — suficiente pra testar o laço de envio."""
    def __init__(self):
        super().__init__("requests")
        self.chamadas = []

    def post(self, url, **kw):
        self.chamadas.append((url, kw))
        r = mock.Mock()
        r.status_code = 201
        r.raise_for_status.return_value = None
        return r


class TestIncertoNaoEncerraSozinho(unittest.TestCase):
    """processar_pedido(): INCERTO isolado não quebra o laço; conta no mesmo contador de
    falhas_seguidas que FALHOU usa, então uma sequência (mesmo misturando os dois) ainda para."""

    def _processar(self, resultados_envio):
        fila = FILA[:len(resultados_envio)]
        req = RequestsFaloPost()
        with mock.patch.dict(sys.modules, {"requests": req}), \
             mock.patch.object(w.disp, "_config_supabase", return_value=(URL, CHAVE)), \
             mock.patch.object(w.disp, "_config_baileys", return_value=("http://x", "tok")), \
             mock.patch.object(w.disp, "_teto_maximo", return_value=30), \
             mock.patch.object(w.disp, "montar_fila", return_value={"fila": fila}), \
             mock.patch.object(w.disp, "agora_brasilia", return_value="AGORA"), \
             mock.patch.object(w.disp, "envios_na_janela", return_value=(0, None)), \
             mock.patch.object(w.disp, "pre_teste_baileys", return_value=(True, "ok")), \
             mock.patch.object(w.disp, "dentro_da_janela", return_value=True), \
             mock.patch.object(w.disp, "enviar_via_baileys", side_effect=resultados_envio), \
             mock.patch.object(w.disp, "esperar"), \
             mock.patch.object(w.disp, "registrar_conversa"), \
             mock.patch.object(w, "le"):
            return w.processar_pedido({"quantidade": len(fila)}, URL, CHAVE)

    def test_incerto_isolado_nao_encerra_o_pedido(self):
        resultado = self._processar([
            (w.disp.ENVIADO, "HTTP 200", ""),
            (w.disp.INCERTO, "HTTP 504", ""),
            (w.disp.ENVIADO, "HTTP 200", ""),
        ])
        self.assertEqual(resultado["motivo_fim"], "fila concluída")
        self.assertEqual(resultado["enviados"], 2)
        self.assertEqual(resultado["incertos"], 1)

    def test_tres_seguidos_misturando_falhou_e_incerto_encerram(self):
        resultado = self._processar([
            (w.disp.FALHOU, "HTTP 502", ""),
            (w.disp.INCERTO, "HTTP 504", ""),
            (w.disp.FALHOU, "HTTP 502", ""),
            (w.disp.ENVIADO, "HTTP 200", ""),  # nunca chamado: o laço já parou antes
        ])
        self.assertIn("3 falhas seguidas", resultado["motivo_fim"])
        self.assertEqual(resultado["enviados"], 0)
        self.assertEqual(resultado["falhas"], 2)
        self.assertEqual(resultado["incertos"], 1)

    def test_tres_incertas_seguidas_tambem_param(self):
        resultado = self._processar([
            (w.disp.INCERTO, "HTTP 504", ""),
            (w.disp.INCERTO, "HTTP 504", ""),
            (w.disp.INCERTO, "HTTP 504", ""),
            (w.disp.ENVIADO, "HTTP 200", ""),  # nunca chamado
        ])
        self.assertIn("3 falhas seguidas", resultado["motivo_fim"])
        self.assertEqual(resultado["incertos"], 3)
        self.assertEqual(resultado["enviados"], 0)


if __name__ == "__main__":
    unittest.main()
