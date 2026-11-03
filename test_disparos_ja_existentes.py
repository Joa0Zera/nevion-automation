"""Teste: o Disparador v2 não reenvia pra ninguém que já tenha QUALQUER linha em
public.disparos (qualquer status, inclusive 'falhou') — mesmo que esse contato não esteja no
disparados.json local (os dois arquivos podem ficar fora de sincronia). Cobre:
  - montar_fila() exclui quem está só na tabela (qualquer status, inclusive 'falhou').
  - A regra antiga (disparados.json) continua valendo pra quem só está lá.
  - Contato novo, sem registro em lugar nenhum, entra normalmente.
  - Falha na consulta à tabela disparos aborta a execução (ensaio e real), sem enviar nada.
  - executar_real() refaz a checagem antes de CADA envio (não só na montagem da fila): uma
    falha no meio da execução impede o envio seguinte.
Sem rede de verdade: a consulta a disparos (_contatos_ja_em_disparos_ou_falha) é mockada em
todo teste. Rodar: python -m unittest test_disparos_ja_existentes -v"""
import importlib.util
import os
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from unittest import mock

for _f in (sys.stdout, sys.stderr):
    if hasattr(_f, 'reconfigure'):
        _f.reconfigure(encoding='utf-8', errors='replace')

PASTA = os.path.dirname(os.path.abspath(__file__))
_spec = importlib.util.spec_from_file_location("disparador_v2_teste_ja_existentes", os.path.join(PASTA, "Disparador v2.py"))
disp = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(disp)

URL, CHAVE = "https://exemplo.supabase.test", "chave-de-teste"
AGORA_UTC = datetime(2026, 11, 3, 15, 0, 0, tzinfo=timezone.utc)
AGORA_BRASILIA = AGORA_UTC.astimezone(disp.BRASILIA)
FILA = [(f"+55119999900{i:02d}", f"5511999990{i:03d}", f"Lead {i}", "") for i in range(3)]


class TestMontarFilaExcluiQuemJaEstaEmDisparos(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.arquivo = os.path.join(tmp.name, "contatos.txt")
        p = mock.patch.object(disp, "ARQUIVO_CONTATOS", self.arquivo)
        p.start()
        self.addCleanup(p.stop)

    def _escrever(self, linhas):
        with open(self.arquivo, "w", encoding="utf-8") as f:
            f.write("\n".join(linhas) + "\n")

    def _montar(self, quantidade=None, disparados=None, ja_em_disparos_tabela=None):
        with mock.patch.object(disp, "carregar_disparados", return_value=disparados or {}), \
             mock.patch.object(disp, "_contatos_ja_em_disparos_ou_falha", return_value=ja_em_disparos_tabela or set()), \
             mock.patch("optout.carregar_optout", return_value=set()):
            return disp.montar_fila(quantidade)

    def test_disparado_so_na_tabela_nao_entra_na_fila(self):
        """Número com linha em disparos status 'disparado', sem estar no disparados.json."""
        self._escrever(["+5511999990000;Academia Tal;personal_trainer"])
        plano = self._montar(ja_em_disparos_tabela={"5511999990000"})
        self.assertIsNone(plano)

    def test_falhou_so_na_tabela_tambem_nao_entra_na_fila(self):
        """Status não importa pra montar_fila: _contatos_ja_em_disparos_ou_falha() já devolve
        todo contato de QUALQUER status (ver disparos_compartilhado.py) — inclusive 'falhou'."""
        self._escrever(["+5511999990000;Academia Tal;personal_trainer"])
        plano = self._montar(ja_em_disparos_tabela={"5511999990000"})
        self.assertIsNone(plano)

    def test_numero_so_no_disparados_json_continua_fora(self):
        """Regra antiga mantida: quem só está no arquivo local continua de fora."""
        self._escrever(["+5511999990000;Academia Tal;personal_trainer"])
        plano = self._montar(disparados={"+5511999990000": {"status": "disparado"}})
        self.assertIsNone(plano)

    def test_numero_novo_sem_registro_em_lugar_nenhum_entra_normalmente(self):
        self._escrever(["+5511999990000;Academia Tal;personal_trainer"])
        plano = self._montar()
        self.assertEqual(len(plano["fila"]), 1)
        self.assertEqual(plano["fila"][0][1], "5511999990000")

    def test_falha_na_consulta_a_disparos_levanta_supabase_indisponivel(self):
        self._escrever(["+5511999990000;Academia Tal;personal_trainer"])
        with mock.patch.object(disp, "carregar_disparados", return_value={}), \
             mock.patch.object(disp, "_contatos_ja_em_disparos_ou_falha",
                                side_effect=disp.SupabaseIndisponivel("não consegui consultar disparos: ConnectionError")), \
             mock.patch("optout.carregar_optout", return_value=set()):
            with self.assertRaises(disp.SupabaseIndisponivel):
                disp.montar_fila(None)


class TestContatosJaEmDisparosOuFalha(unittest.TestCase):
    """_contatos_ja_em_disparos_ou_falha(): a função usada por montar_fila() e por
    executar_real() a cada envio."""

    def test_sem_config_levanta_supabase_indisponivel(self):
        with mock.patch.object(disp, "_config_supabase", return_value=None):
            with self.assertRaises(disp.SupabaseIndisponivel):
                disp._contatos_ja_em_disparos_ou_falha()

    def test_falha_na_consulta_vira_supabase_indisponivel(self):
        with mock.patch.object(disp, "_config_supabase", return_value=(URL, CHAVE)), \
             mock.patch.object(disp.disparos_compartilhado, "buscar_contatos_ja_em_disparos",
                                side_effect=ConnectionError("supabase fora do ar")):
            with self.assertRaises(disp.SupabaseIndisponivel):
                disp._contatos_ja_em_disparos_ou_falha()

    def test_sucesso_repassa_o_conjunto(self):
        with mock.patch.object(disp, "_config_supabase", return_value=(URL, CHAVE)), \
             mock.patch.object(disp.disparos_compartilhado, "buscar_contatos_ja_em_disparos",
                                return_value={"5511999990000"}):
            self.assertEqual(disp._contatos_ja_em_disparos_ou_falha(), {"5511999990000"})


class TestEnsaioPassaPelaMesmaChecagem(unittest.TestCase):
    """Modo ensaio (sem envio): a exclusão é a mesma do modo real, pra contagem ser fiel."""

    def test_ensaio_repassa_a_fila_ja_filtrada_por_montar_fila(self):
        with mock.patch.object(disp, "_teto_maximo", return_value=40), \
             mock.patch.object(disp, "montar_fila", return_value=None) as montar, \
             mock.patch("builtins.print"):
            codigo = disp.executar_ensaio(10)
        montar.assert_called_once_with(10)
        self.assertEqual(codigo, 0)

    def test_ensaio_aborta_sem_enviar_se_a_consulta_a_disparos_falhar(self):
        with mock.patch.object(disp, "_teto_maximo", return_value=40), \
             mock.patch.object(disp, "montar_fila",
                                side_effect=disp.SupabaseIndisponivel("não consegui consultar disparos: ConnectionError")), \
             mock.patch("builtins.print") as impressao:
            codigo = disp.executar_ensaio(10)
        self.assertEqual(codigo, 1)
        textos = " ".join(str(a) for chamada in impressao.call_args_list for a in chamada.args)
        self.assertIn("Não consegui confirmar quem já está em disparos", textos)


class TestExecutarRealRefazAChecagemAntesDeCadaEnvio(unittest.TestCase):
    """executar_real(): a checagem vale pra fila inteira (montar_fila) E é refeita antes de
    CADA envio — uma falha a meio da execução impede o envio seguinte."""

    def _mocks_base(self):
        return (
            mock.patch.object(disp, "_config_baileys", return_value=("http://x", "tok")),
            mock.patch.object(disp, "_teto_maximo", return_value=40),
            mock.patch.object(disp, "agora_brasilia", return_value=AGORA_BRASILIA),
            mock.patch.object(disp, "dentro_da_janela", return_value=True),
            mock.patch.object(disp, "envios_na_janela", return_value=(0, None)),
            mock.patch.object(disp, "_motivo_limite_24h", return_value=None),
            mock.patch.object(disp, "pre_teste_baileys", return_value=(True, "ok")),
            mock.patch.object(disp, "registrar_disparo_no_supabase", return_value=True),
            mock.patch.object(disp, "salvar_disparado", return_value=True),
            mock.patch.object(disp, "registrar_conversa"),
            mock.patch.object(disp, "esperar"),
            mock.patch("builtins.input", return_value="ENVIAR"),
        )

    def test_falha_no_inicio_aborta_sem_enviar_nada(self):
        with mock.patch.object(disp, "montar_fila",
                                side_effect=disp.SupabaseIndisponivel("não consegui consultar disparos: ConnectionError")), \
             mock.patch.object(disp, "_config_baileys", return_value=("http://x", "tok")), \
             mock.patch.object(disp, "_teto_maximo", return_value=40), \
             mock.patch.object(disp, "agora_brasilia", return_value=AGORA_BRASILIA), \
             mock.patch.object(disp, "dentro_da_janela", return_value=True), \
             mock.patch.object(disp, "enviar_via_baileys") as enviar, \
             mock.patch("builtins.print") as impressao:
            codigo = disp.executar_real(len(FILA))
        enviar.assert_not_called()
        self.assertEqual(codigo, 1)
        textos = " ".join(str(a) for chamada in impressao.call_args_list for a in chamada.args)
        self.assertIn("Não consegui confirmar quem já está em disparos", textos)

    def test_falha_no_meio_da_execucao_impede_o_envio_seguinte(self):
        chamadas = {"n": 0}

        def instavel():
            chamadas["n"] += 1
            if chamadas["n"] >= 2:  # 1ª checagem (1º contato): ok; 2ª (2º contato): falha
                raise disp.SupabaseIndisponivel("não consegui consultar disparos: ConnectionError")
            return set()

        mocks = self._mocks_base()
        with mocks[0], mocks[1], mocks[2], mocks[3], mocks[4], mocks[5], mocks[6], mocks[7], \
             mocks[8], mocks[9], mocks[10], mocks[11], \
             mock.patch.object(disp, "montar_fila", return_value={"fila": FILA}), \
             mock.patch.object(disp, "_contatos_ja_em_disparos_ou_falha", side_effect=instavel), \
             mock.patch.object(disp, "enviar_via_baileys", return_value=(disp.ENVIADO, "HTTP 200", "")) as enviar, \
             mock.patch("builtins.print") as impressao:
            codigo = disp.executar_real(len(FILA))

        self.assertEqual(enviar.call_count, 1)  # só o 1º contato foi enviado; o 2º não aconteceu
        textos = " ".join(str(a) for chamada in impressao.call_args_list for a in chamada.args)
        self.assertIn("não consegui confirmar quem já está em disparos", textos.lower())
        self.assertNotIn("DISPAROS CONCLUÍDOS", textos)
        self.assertEqual(codigo, 1)

    def test_numero_marcado_durante_a_execucao_e_pulado_sem_abortar(self):
        """Um dos contatos da fila ganha registro em disparos NO MEIO da execução (outro
        processo): é pulado, com o motivo no log, e a execução continua pros demais."""
        _, normalizado_pulado, _, _ = FILA[1]

        def checagem(chamadas={"n": 0}):
            chamadas["n"] += 1
            return {normalizado_pulado} if chamadas["n"] >= 2 else set()

        mocks = self._mocks_base()
        with mocks[0], mocks[1], mocks[2], mocks[3], mocks[4], mocks[5], mocks[6], mocks[7], \
             mocks[8], mocks[9], mocks[10], mocks[11], \
             mock.patch.object(disp, "montar_fila", return_value={"fila": FILA}), \
             mock.patch.object(disp, "_contatos_ja_em_disparos_ou_falha", side_effect=checagem), \
             mock.patch.object(disp, "enviar_via_baileys", return_value=(disp.ENVIADO, "HTTP 200", "")) as enviar, \
             mock.patch("builtins.print") as impressao:
            codigo = disp.executar_real(len(FILA))

        self.assertEqual(enviar.call_count, 2)  # o 1º e o 3º; o 2º (pulado) não foi enviado
        textos = " ".join(str(a) for chamada in impressao.call_args_list for a in chamada.args)
        self.assertIn("já tem registro em disparos", textos)
        self.assertIn("DISPAROS CONCLUÍDOS", textos)
        self.assertEqual(codigo, 0)


if __name__ == "__main__":
    unittest.main()
