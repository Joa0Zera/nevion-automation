"""Teste: whatsapp_desconectado (503) não conta como falha e pausa o lote imediatamente,
sem avançar pros contatos seguintes (worker_disparo.py, processar_pedido()). A gravação do
contato que descobriu a desconexão continua 'falhou' como hoje — só o controle do laço muda.
Sem rede, sem Supabase, sem Baileys: `requests` é trocado por um dublê (mesmo padrão de
test_worker_status.py/test_worker_nome.py). Rodar: python -m unittest test_worker_desconexao -v"""
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
FILA = [(f"+55119999900{i:02d}", f"5511999990{i:03d}", f"Lead {i}") for i in range(6)]


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


class TestWhatsappDesconectadoPausaOLote(unittest.TestCase):
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
             mock.patch.object(w.disp, "enviar_via_baileys", side_effect=resultados_envio) as envio, \
             mock.patch.object(w.disp, "esperar"), \
             mock.patch.object(w.disp, "registrar_conversa"), \
             mock.patch.object(w, "le"):
            resultado = w.processar_pedido({"quantidade": len(fila)}, URL, CHAVE)
        return resultado, envio

    def test_whatsapp_desconectado_nao_conta_como_falha_e_usa_o_motivo_proprio(self):
        resultado, _ = self._processar([
            (w.disp.ENVIADO, "HTTP 200", ""),
            (w.disp.FALHOU, "HTTP 503 whatsapp_desconectado", "whatsapp_desconectado"),
            (w.disp.ENVIADO, "HTTP 200", ""),  # nunca chamado: o laço já pausou antes
            (w.disp.ENVIADO, "HTTP 200", ""),  # nunca chamado
        ])
        self.assertEqual(resultado["motivo_fim"], "WhatsApp desconectado — pausado; pode ser retomado depois")
        self.assertEqual(resultado["enviados"], 1)
        self.assertEqual(resultado["falhas"], 1)  # o contato que descobriu continua contado/gravado como falhou

    def test_laco_para_no_contato_que_descobriu_sem_tentar_os_seguintes(self):
        resultado, envio = self._processar([
            (w.disp.ENVIADO, "HTTP 200", ""),
            (w.disp.FALHOU, "HTTP 503 whatsapp_desconectado", "whatsapp_desconectado"),
            (w.disp.ENVIADO, "HTTP 200", ""),
            (w.disp.ENVIADO, "HTTP 200", ""),
        ])
        self.assertEqual(envio.call_count, 2)  # só os dois primeiros contatos foram tentados

    def test_nao_soma_falhas_seguidas_mesmo_antes_de_pausar(self):
        """Dois FALHOU normais (contam) seguidos de um whatsapp_desconectado (não conta):
        se desconectado contasse, já teria batido o limite de 3 e pausado com o motivo
        genérico de 'falhas seguidas' em vez do motivo próprio desta pausa."""
        resultado, envio = self._processar([
            (w.disp.FALHOU, "HTTP 502", ""),
            (w.disp.FALHOU, "HTTP 502", ""),
            (w.disp.FALHOU, "HTTP 503 whatsapp_desconectado", "whatsapp_desconectado"),
            (w.disp.ENVIADO, "HTTP 200", ""),  # nunca chamado
        ])
        self.assertEqual(resultado["motivo_fim"], "WhatsApp desconectado — pausado; pode ser retomado depois")
        self.assertEqual(envio.call_count, 3)


if __name__ == "__main__":
    unittest.main()
