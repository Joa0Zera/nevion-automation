"""Teste: teto deslizante de DISPARO_TETO_MAX (padrão 40) envios em qualquer janela de 24 horas.
Sem rede, sem Supabase, sem Baileys: `requests` é trocado por um dublê (mesmo padrão de
test_worker_incerto.py). Rodar: python -m unittest test_worker_limite_24h -v"""
import sys
import types
import unittest
from datetime import datetime, timedelta, timezone
from unittest import mock

import worker_disparo as w

for _f in (sys.stdout, sys.stderr):
    if hasattr(_f, 'reconfigure'):
        _f.reconfigure(encoding='utf-8', errors='replace')

URL, CHAVE = "https://exemplo.supabase.test", "chave-de-teste"
FILA = [(f"+55119999900{i:02d}", f"5511999990{i:03d}", f"Lead {i}", "") for i in range(5)]
AGORA = datetime(2026, 10, 30, 15, 0, 0, tzinfo=timezone.utc)


class RequestsFalso(types.ModuleType):
    """Dublê de `requests`: GET responde as linhas de `disparos` (já filtradas pelo teste) ou
    levanta; POST aceita tudo (pré-escrita/registro do envio)."""
    def __init__(self, linhas=(), falha=None):
        super().__init__("requests")
        self.linhas, self.falha, self.gets = list(linhas), falha, []

    def get(self, url, **kw):
        self.gets.append((url, kw))
        if self.falha:
            raise self.falha
        # o teste de "mais antigo que 24 h não conta" confere o filtro enviado ao PostgREST
        desde = kw["params"]["disparado_em"][len("gte."):]
        corte = datetime.strptime(desde, "%Y-%m-%dT%H:%M:%SZ")
        validas = [l for l in self.linhas if datetime.fromisoformat(l["disparado_em"]) >= corte]
        r = mock.Mock()
        r.status_code = 200
        r.json.return_value = sorted(validas, key=lambda l: l["disparado_em"])
        return r

    def post(self, url, **kw):
        r = mock.Mock()
        r.status_code = 201
        r.raise_for_status.return_value = None
        return r


def envio(horas_atras, minutos=0, status="disparado"):
    momento = AGORA - timedelta(hours=horas_atras, minutes=minutos)
    return {"status": status, "disparado_em": momento.strftime("%Y-%m-%dT%H:%M:%S")}


def dentro(n):
    """n envios espalhados nas últimas ~19 h (todos dentro da janela)."""
    return [envio(0, 10 + 30 * i) for i in range(n)]


class Base(unittest.TestCase):
    def _processar(self, req, quantidade=5, limite=40, enviar_side_effect=None):
        fila = FILA[:quantidade]
        with mock.patch.dict(sys.modules, {"requests": req}), \
             mock.patch.object(w.disp, "_config_supabase", return_value=(URL, CHAVE)), \
             mock.patch.object(w.disp, "_config_baileys", return_value=("http://x", "tok")), \
             mock.patch.object(w.disp, "_teto_maximo", return_value=limite), \
             mock.patch.object(w.disp, "montar_fila", return_value={"fila": fila}), \
             mock.patch.object(w.disp, "agora_utc", return_value=AGORA), \
             mock.patch.object(w.disp, "pre_teste_baileys", return_value=(True, "ok")), \
             mock.patch.object(w.disp, "dentro_da_janela", return_value=True), \
             mock.patch.object(w.disp, "enviar_via_baileys", side_effect=enviar_side_effect or (lambda *a, **kw: (w.disp.ENVIADO, "HTTP 200", ""))) as enviar, \
             mock.patch.object(w.disp, "esperar"), \
             mock.patch.object(w.disp, "registrar_conversa"), \
             mock.patch.object(w, "le"):
            resultado = w.processar_pedido({"quantidade": quantidade}, URL, CHAVE)
        return resultado, enviar


class TestLimite24h(Base):
    def test_com_39_na_janela_envia_1_e_para_antes_do_41o(self):
        # a contagem do banco cresce a cada envio (o registro 'enviando'/'disparado' entra na janela)
        enviados_neste_pedido = {"n": 0}

        def contagem(*a, **kw):
            return 39 + enviados_neste_pedido["n"], AGORA - timedelta(hours=20)

        def enviar_e_conta(*a, **kw):
            enviados_neste_pedido["n"] += 1
            return (w.disp.ENVIADO, "HTTP 200", "")

        with mock.patch.object(w.disp, "envios_na_janela", side_effect=contagem):
            resultado, enviar = self._processar(RequestsFalso(), enviar_side_effect=enviar_e_conta)
        self.assertEqual(enviar.call_count, 1)
        self.assertEqual(resultado["enviados"], 1)
        self.assertEqual(resultado["motivo_fim"], "limite de 40 envios em 24h atingido; libera em 30/10 16:00")

    def test_com_40_na_janela_nao_envia_nada_e_informa_quando_libera(self):
        mais_antigo = envio(23, 30)                                  # 23h30 atrás
        req = RequestsFalso([mais_antigo] + dentro(39))
        resultado, enviar = self._processar(req)
        enviar.assert_not_called()
        self.assertEqual(resultado["enviados"], 0)
        # libera = mais antigo + 24 h = agora + 30 min = 15:30 UTC = 12:30 em Brasília
        self.assertEqual(resultado["motivo_fim"], "limite de 40 envios em 24h atingido; libera em 30/10 12:30")

    def test_envios_com_mais_de_24h_nao_contam(self):
        req = RequestsFalso([envio(25), envio(30), envio(48)] + dentro(39))   # 39 válidos + 3 antigos
        enviados, mais_antigo = None, None
        with mock.patch.dict(sys.modules, {"requests": req}), \
             mock.patch.object(w.disp, "_config_supabase", return_value=(URL, CHAVE)):
            enviados, mais_antigo = w.disp.envios_na_janela(AGORA)
        self.assertEqual(enviados, 39)
        self.assertEqual(mais_antigo, AGORA - timedelta(minutes=10 + 30 * 38))  # o mais antigo DENTRO da janela
        # o filtro mandado ao banco: só disparado/enviando/incerto, desde 24 h atrás
        params = req.gets[0][1]["params"]
        self.assertEqual(params["status"], "in.(disparado,enviando,incerto)")
        self.assertEqual(params["disparado_em"], "gte.2026-10-29T15:00:00Z")

    def test_so_disparado_enviando_e_incerto_entram_no_filtro_sem_contar_os_outros(self):
        # o filtro de status vai pro banco; aqui garantimos que o código pede exatamente esses três
        self.assertEqual(w.disp.STATUS_NA_JANELA, ("disparado", "enviando", "incerto"))

    def test_se_a_contagem_falhar_nada_e_enviado(self):
        req = RequestsFalso(falha=ConnectionError("supabase fora do ar"))
        resultado, enviar = self._processar(req)
        enviar.assert_not_called()
        self.assertEqual(resultado["enviados"], 0)
        self.assertEqual(resultado["motivo_fim"], "não foi possível verificar o limite de 24h")

    def test_falha_no_meio_do_pedido_para_sem_enviar_o_proximo(self):
        req = RequestsFalso([])
        original = w.disp.envios_na_janela
        chamadas = {"n": 0}

        def instavel(*a, **kw):
            chamadas["n"] += 1
            if chamadas["n"] >= 3:      # 1ª: antes do pré-teste; 2ª: 1º contato; 3ª: 2º contato falha
                raise w.disp.SupabaseIndisponivel("fora do ar")
            return original(*a, **kw)

        with mock.patch.object(w.disp, "envios_na_janela", side_effect=instavel):
            resultado, enviar = self._processar(req)
        self.assertEqual(enviar.call_count, 1)
        self.assertEqual(resultado["motivo_fim"], "não foi possível verificar o limite de 24h")

    def test_padrao_de_DISPARO_TETO_MAX_e_40(self):
        self.assertEqual(w.disp.TETO_MAX_PADRAO, 40)
        with mock.patch.object(w.disp, "_ler_config", return_value={"DISPARO_TETO_MAX": ""}):
            self.assertEqual(w.disp._teto_maximo(), 40)
        with mock.patch.object(w.disp, "_ler_config", return_value={"DISPARO_TETO_MAX": "25"}):
            self.assertEqual(w.disp._teto_maximo(), 25)


if __name__ == "__main__":
    unittest.main()
