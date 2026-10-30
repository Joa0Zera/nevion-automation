"""Teste: executar_real() (modo --real do terminal) segue o mesmo teto deslizante de
DISPARO_TETO_MAX (padrão 40) envios em qualquer janela de 24 horas que o worker usa — em vez do
antigo teto diário com aquecimento (calcular_teto, agora obsoleto nesse caminho).
Sem rede, sem Supabase, sem Baileys: `requests` é trocado por um dublê (mesmo padrão de
test_worker_limite_24h.py). Rodar: python -m unittest test_disparador_real -v"""
import importlib.util
import os
import sys
import types
import unittest
from datetime import datetime, timedelta, timezone
from unittest import mock

for _f in (sys.stdout, sys.stderr):
    if hasattr(_f, 'reconfigure'):
        _f.reconfigure(encoding='utf-8', errors='replace')

PASTA = os.path.dirname(os.path.abspath(__file__))
_spec = importlib.util.spec_from_file_location("disparador_v2_teste", os.path.join(PASTA, "Disparador v2.py"))
disp = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(disp)

URL, CHAVE = "https://exemplo.supabase.test", "chave-de-teste"
FILA = [(f"+55119999900{i:02d}", f"5511999990{i:03d}", f"Lead {i}") for i in range(3)]
AGORA_UTC = datetime(2026, 10, 30, 15, 0, 0, tzinfo=timezone.utc)
AGORA_BRASILIA = AGORA_UTC.astimezone(disp.BRASILIA)


class RequestsFalso(types.ModuleType):
    """GET responde as linhas de `disparos` fixas pelo teste; POST aceita tudo
    (pré-escrita/registro do envio, que não deveria nem ser chamada se o teto já está atingido)."""
    def __init__(self, linhas=()):
        super().__init__("requests")
        self.linhas = list(linhas)

    def get(self, url, **kw):
        r = mock.Mock()
        r.status_code = 200
        r.json.return_value = sorted(self.linhas, key=lambda l: l["disparado_em"])
        return r

    def post(self, url, **kw):
        r = mock.Mock()
        r.status_code = 201
        r.raise_for_status.return_value = None
        return r


def linhas_40_na_janela():
    """40 envios 'disparado' espalhados na última hora (todos dentro das 24h)."""
    return [
        {"status": "disparado", "disparado_em": (AGORA_UTC - timedelta(hours=1, minutes=i)).strftime("%Y-%m-%dT%H:%M:%S")}
        for i in range(40)
    ]


class TestExecutarRealSegueOTetoDeslizante(unittest.TestCase):
    def _executar(self, linhas):
        req = RequestsFalso(linhas)
        with mock.patch.dict(sys.modules, {"requests": req}), \
             mock.patch.object(disp, "_config_supabase", return_value=(URL, CHAVE)), \
             mock.patch.object(disp, "_config_baileys", return_value=("http://x", "tok")), \
             mock.patch.object(disp, "_teto_maximo", return_value=40), \
             mock.patch.object(disp, "montar_fila", return_value={"fila": FILA}), \
             mock.patch.object(disp, "agora_brasilia", return_value=AGORA_BRASILIA), \
             mock.patch.object(disp, "agora_utc", return_value=AGORA_UTC), \
             mock.patch.object(disp, "dentro_da_janela", return_value=True), \
             mock.patch.object(disp, "pre_teste_baileys", return_value=(True, "ok")), \
             mock.patch.object(disp, "enviar_via_baileys", return_value=(disp.ENVIADO, "HTTP 200", "")) as enviar, \
             mock.patch.object(disp, "esperar"), \
             mock.patch.object(disp, "registrar_conversa"), \
             mock.patch("builtins.input", return_value="ENVIAR") as entrada, \
             mock.patch("builtins.print"):
            codigo = disp.executar_real(len(FILA))
        return codigo, enviar, entrada

    def test_com_40_na_janela_nao_envia_nada_e_informa_quando_libera(self):
        codigo, enviar, entrada = self._executar(linhas_40_na_janela())
        enviar.assert_not_called()
        entrada.assert_not_called()  # nem chega a pedir confirmação: já parou antes
        self.assertEqual(codigo, 0)

    def test_com_a_janela_livre_segue_normal_e_chega_a_pedir_confirmacao(self):
        # sem nenhum envio na janela (requests.get devolve lista vazia): não deve parar no teto
        codigo, enviar, entrada = self._executar([])
        entrada.assert_called_once()
        self.assertEqual(enviar.call_count, len(FILA))

    def test_falha_na_verificacao_no_meio_do_laco_nao_mostra_concluido(self):
        """Quando _motivo_limite_24h falha (SupabaseIndisponivel) DENTRO do laço (depois de já
        ter enviado pro menos um contato), o resumo não pode dizer 'DISPAROS CONCLUÍDOS!' nem
        devolver 0 — isso é uma falha de execução, diferente de atingir o teto de verdade."""
        chamadas = {"n": 0}

        def instavel(limite):
            chamadas["n"] += 1
            # 1ª: antes de pedir confirmação; 2ª: antes do 1º contato (ok); 3ª: antes do 2º (falha)
            if chamadas["n"] >= 3:
                return "não foi possível verificar o limite de 24h"
            return None

        req = RequestsFalso([])
        with mock.patch.dict(sys.modules, {"requests": req}), \
             mock.patch.object(disp, "_config_supabase", return_value=(URL, CHAVE)), \
             mock.patch.object(disp, "_config_baileys", return_value=("http://x", "tok")), \
             mock.patch.object(disp, "_teto_maximo", return_value=40), \
             mock.patch.object(disp, "montar_fila", return_value={"fila": FILA}), \
             mock.patch.object(disp, "agora_brasilia", return_value=AGORA_BRASILIA), \
             mock.patch.object(disp, "envios_na_janela", return_value=(0, None)), \
             mock.patch.object(disp, "dentro_da_janela", return_value=True), \
             mock.patch.object(disp, "pre_teste_baileys", return_value=(True, "ok")), \
             mock.patch.object(disp, "_motivo_limite_24h", side_effect=instavel), \
             mock.patch.object(disp, "enviar_via_baileys", return_value=(disp.ENVIADO, "HTTP 200", "")) as enviar, \
             mock.patch.object(disp, "esperar"), \
             mock.patch.object(disp, "registrar_conversa"), \
             mock.patch("builtins.input", return_value="ENVIAR"), \
             mock.patch("builtins.print") as impressao:
            codigo = disp.executar_real(len(FILA))

        textos = " ".join(str(a) for chamada in impressao.call_args_list for a in chamada.args)
        self.assertNotIn("DISPAROS CONCLUÍDOS", textos)
        self.assertIn("EXECUÇÃO INTERROMPIDA", textos)
        self.assertIn("não foi possível verificar o limite de 24h", textos)
        self.assertEqual(enviar.call_count, 1)  # só o 1º contato foi tentado
        self.assertEqual(codigo, 1)


if __name__ == "__main__":
    unittest.main()
