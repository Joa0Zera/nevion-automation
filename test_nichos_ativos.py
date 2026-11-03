"""Teste: envio pausado pra clínica — lista de permissão de nichos (NICHOS_ATIVOS). Cobre:
  - montar_fila() (Disparador v2.py) só deixa entrar quem normaliza (via chave_do_nicho) pra
    uma chave em NICHOS_ATIVOS; nicho vazio/nulo/desconhecido (inclusive clínica) fica fora,
    sem fallback de clínica.
  - A regra antiga (quem já tem linha em disparos continua fora) vale por igual, independente
    do nicho.
  - sync_leadengine.py: só escreve no contatos.txt quem passa pela mesma lista de permissão.
  - A intercalação por nicho (commit anterior) continua funcionando, só com os nichos ativos.
Sem rede: _contatos_ja_em_disparos_ou_falha / buscar_contatos_ja_em_disparos são mockados em
todo teste. Rodar: python -m unittest test_nichos_ativos -v"""
import importlib.util
import os
import sys
import tempfile
import unittest
from unittest import mock

for _f in (sys.stdout, sys.stderr):
    if hasattr(_f, 'reconfigure'):
        _f.reconfigure(encoding='utf-8', errors='replace')

PASTA = os.path.dirname(os.path.abspath(__file__))
_spec = importlib.util.spec_from_file_location("disparador_v2_teste_nichos_ativos", os.path.join(PASTA, "Disparador v2.py"))
disp = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(disp)

import sync_leadengine as sync


class TestMontarFilaRespeitaNichosAtivos(unittest.TestCase):
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

    def test_contato_de_clinica_nao_entra_na_fila(self):
        """Nicho vazio (formato antigo, 2 campos) = clínica — pausada."""
        self._escrever(["+5511999990000;Clínica Bella Pele"])
        plano = self._montar()
        self.assertIsNone(plano)

    def test_contato_de_personal_trainer_entra_normalmente(self):
        self._escrever(["+5511999990000;Academia Tal;Personal Trainer"])
        plano = self._montar()
        self.assertEqual(len(plano["fila"]), 1)
        self.assertEqual(plano["fila"][0][1], "5511999990000")

    def test_nicho_desconhecido_nao_entra(self):
        self._escrever(["+5511999990000;Dra. Fulana;Dentista"])
        plano = self._montar()
        self.assertIsNone(plano)

    def test_nicho_outros_nao_entra(self):
        self._escrever(["+5511999990000;Alguma Empresa;Outros"])
        plano = self._montar()
        self.assertIsNone(plano)

    def test_contato_de_clinica_que_ja_tinha_disparo_continua_fora_pela_regra_antiga(self):
        """Mesmo se clínica fosse reativada em NICHOS_ATIVOS, quem já tem linha em disparos
        (commit 8561337) continuaria fora — as duas regras são independentes."""
        self._escrever(["+5511999990000;Clínica Bella Pele"])
        plano = self._montar(ja_em_disparos_tabela={"5511999990000"})
        self.assertIsNone(plano)  # já estaria fora pelo nicho; aqui confirma que também está pela tabela

    def test_tres_nichos_ativos_entram_clinica_e_desconhecido_nao(self):
        self._escrever([
            "+5511999990001;Studio A;Barbearia",
            "+5511999990002;Clínica B",  # nicho vazio -> clínica, fora
            "+5511999990003;Treino C;Personal Trainer",
            "+5511999990004;Studio D;Manicure e Lash",
            "+5511999990005;Dentista E;Dentista",  # desconhecido, fora
        ])
        plano = self._montar()
        normalizados = {item[1] for item in plano["fila"]}
        self.assertEqual(normalizados, {"5511999990001", "5511999990003", "5511999990004"})

    def test_intercalacao_funciona_so_com_os_nichos_ativos(self):
        self._escrever(
            [f"+551100000{i:03d};Barbearia {i};Barbearia" for i in range(1, 4)]
            + [f"+551100001{i:03d};Academia {i};Personal Trainer" for i in range(1, 4)]
            + [f"+551100002{i:03d};Clínica {i}" for i in range(1, 4)]  # nicho vazio: nunca entra
        )
        plano = self._montar()
        nichos = [disp.chave_do_nicho(item[3]) for item in plano["fila"]]
        self.assertEqual(len(nichos), 6)  # as 3 de clínica ficaram de fora
        self.assertEqual(nichos, ["barbearia", "personal_trainer"] * 3)  # intercalado 1 a 1


class TestSyncRespeitaNichosAtivos(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.arquivo = os.path.join(tmp.name, "contatos.txt")
        p = mock.patch.object(sync, "ARQUIVO_CONTATOS", self.arquivo)
        p.start()
        self.addCleanup(p.stop)

    def _ler_linhas(self):
        with open(self.arquivo, encoding="utf-8") as f:
            return [l.strip() for l in f if l.strip()]

    def _ciclo(self, leads_novo):
        with mock.patch.object(sync.disp, "_config_supabase", return_value=("http://x", "tok")), \
             mock.patch.object(sync, "le") as le_falso, \
             mock.patch.object(sync, "buscar_contatos_ja_em_disparos", return_value=set()):
            le_falso.buscar_leads_novo.return_value = leads_novo
            le_falso.contar_leads_por_status.return_value = {}
            sync.ciclo_unico()
        return self._ler_linhas()

    def test_lead_de_clinica_nao_e_gravado(self):
        linhas = self._ciclo([{
            "normalizedPhone": "5511999990000", "phone": "",
            "name": "Clínica Bella Pele", "category": "Não especificado", "collectedAt": None,
        }])
        self.assertEqual(linhas, [])

    def test_lead_de_personal_trainer_e_gravado_normalmente(self):
        linhas = self._ciclo([{
            "normalizedPhone": "5511999990000", "phone": "",
            "name": "Academia Tal", "category": "Personal Trainer", "collectedAt": None,
        }])
        self.assertEqual(linhas, ["+5511999990000;Academia Tal;Personal Trainer"])

    def test_lead_de_nicho_desconhecido_nao_e_gravado(self):
        linhas = self._ciclo([{
            "normalizedPhone": "5511999990000", "phone": "",
            "name": "Dra. Fulana", "category": "Dentista", "collectedAt": None,
        }])
        self.assertEqual(linhas, [])


if __name__ == "__main__":
    unittest.main()
