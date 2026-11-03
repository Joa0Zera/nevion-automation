"""Teste: contatos.txt passa a aceitar/gravar um 3º campo opcional (nicho), sem quebrar o
formato antigo. Cobre:
  - carregar_contatos()/montar_fila() (Disparador v2.py) aceitando telefone / telefone;nome /
    telefone;nome;nicho na mesma leitura.
  - sync_leadengine.py gravando o nicho (lead['category']) como 3º campo quando presente.
Sem rede, sem Supabase, sem Firestore. Rodar: python -m unittest test_contatos_nicho -v"""
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
_spec = importlib.util.spec_from_file_location("disparador_v2_teste_nicho", os.path.join(PASTA, "Disparador v2.py"))
disp = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(disp)

import sync_leadengine as sync


class TestCarregarContatosAceitaDoisETresCampos(unittest.TestCase):
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

    def test_formato_antigo_so_telefone(self):
        self._escrever(["+5511999990000"])
        self.assertEqual(disp.carregar_contatos(), [("+5511999990000", "", "")])

    def test_formato_com_nome_sem_nicho(self):
        self._escrever(["+5511999990000;Clínica Bella Pele"])
        self.assertEqual(disp.carregar_contatos(), [("+5511999990000", "Clínica Bella Pele", "")])

    def test_formato_novo_com_nicho(self):
        self._escrever(["+5511999990000;Academia Tal;personal_trainer"])
        self.assertEqual(disp.carregar_contatos(), [("+5511999990000", "Academia Tal", "personal_trainer")])

    def test_linhas_mistas_no_mesmo_arquivo(self):
        self._escrever([
            "+5511999990000",
            "+5511999990001;Barbearia do Zé",
            "+5511999990002;Studio de Unhas;manicure_lash",
        ])
        self.assertEqual(disp.carregar_contatos(), [
            ("+5511999990000", "", ""),
            ("+5511999990001", "Barbearia do Zé", ""),
            ("+5511999990002", "Studio de Unhas", "manicure_lash"),
        ])

    def test_montar_fila_repassa_nicho_na_tupla(self):
        self._escrever(["+5511999990000;Academia Tal;personal_trainer"])
        with mock.patch.object(disp, "carregar_disparados", return_value={}), \
             mock.patch.object(disp, "_contatos_ja_em_disparos_ou_falha", return_value=set()), \
             mock.patch("optout.carregar_optout", return_value=set()):
            plano = disp.montar_fila(None)
        self.assertEqual(plano["fila"], [("+5511999990000", "5511999990000", "Academia Tal", "personal_trainer")])


class TestMontarFilaIntercalaNichos(unittest.TestCase):
    """montar_fila() agrupa por nicho e intercala um de cada por vez, em rodízio (mantendo
    a ordem interna de cada grupo), em vez de seguir a ordem crua do contatos.txt."""

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

    def _montar(self, quantidade=None, disparados=None, optouts=None, ja_em_disparos_tabela=None):
        with mock.patch.object(disp, "carregar_disparados", return_value=disparados or {}), \
             mock.patch.object(disp, "_contatos_ja_em_disparos_ou_falha", return_value=ja_em_disparos_tabela or set()), \
             mock.patch("optout.carregar_optout", return_value=optouts or set()):
            return disp.montar_fila(quantidade)

    def test_dois_nichos_quatro_cada_pedido_de_quatro_pega_dois_de_cada(self):
        self._escrever([
            f"+551100000{i:03d};Barbearia {i};barbearia" for i in range(1, 5)
        ] + [
            f"+551100001{i:03d};Academia {i};personal_trainer" for i in range(1, 5)
        ])
        plano = self._montar(quantidade=4)
        nichos = [item[3] for item in plano["fila"]]
        self.assertEqual(len(plano["fila"]), 4)
        self.assertEqual(nichos.count("barbearia"), 2)
        self.assertEqual(nichos.count("personal_trainer"), 2)
        self.assertEqual(nichos, ["barbearia", "personal_trainer", "barbearia", "personal_trainer"])

    def test_um_nicho_so_a_ordem_nao_muda(self):
        linhas = [f"+551100000{i:03d};Academia {i};personal_trainer" for i in range(1, 5)]
        self._escrever(linhas)
        plano = self._montar(quantidade=None)
        esperado = [disp.normalizar_numero(l.split(";")[0]) for l in linhas]
        self.assertEqual([item[1] for item in plano["fila"]], esperado)

    def test_intercalacao_nao_perde_nem_duplica_contato(self):
        self._escrever(
            [f"+551100000{i:03d};Barbearia {i};barbearia" for i in range(1, 4)]
            + [f"+551100001{i:03d};Academia {i};personal_trainer" for i in range(1, 6)]
            + [f"+551100002{i:03d};Studio {i};manicure_lash" for i in range(1, 3)]
        )
        plano = self._montar(quantidade=None)
        normalizados = [item[1] for item in plano["fila"]]
        self.assertEqual(len(normalizados), 10)
        self.assertEqual(len(set(normalizados)), 10)

    def test_filtros_continuam_valendo_com_a_intercalacao(self):
        self._escrever([
            "+5511999990001;Barbearia 1;barbearia",
            "+5511999990002;Academia 1;personal_trainer",
            "+5511999990002;Academia 1 Repetido;personal_trainer",  # duplicado
            "+5511999990003;Barbearia 2;barbearia",  # já disparado
            "+5511999990004;Academia 2;personal_trainer",  # optout
            "abc;Invalido;barbearia",  # inválido
        ])
        plano = self._montar(
            quantidade=None,
            disparados={"5511999990003": "disparado"},
            optouts={"5511999990004"},
        )
        normalizados = {item[1] for item in plano["fila"]}
        self.assertEqual(normalizados, {"5511999990001", "5511999990002"})
        self.assertEqual(plano["invalidos"], 1)
        self.assertEqual(plano["repetidos"], 1)
        self.assertEqual(plano["bloqueados_optout"], 1)


class TestSyncGravaNichoComoTerceiroCampo(unittest.TestCase):
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

    def test_grava_telefone_nome_e_nicho(self):
        linhas = self._ciclo([{
            "normalizedPhone": "5511999990000", "phone": "",
            "name": "Academia Tal", "category": "personal_trainer", "collectedAt": None,
        }])
        self.assertEqual(linhas, ["+5511999990000;Academia Tal;personal_trainer"])

    def test_sem_category_grava_so_telefone_e_nome(self):
        linhas = self._ciclo([{
            "normalizedPhone": "5511999990000", "phone": "",
            "name": "Academia Tal", "category": "", "collectedAt": None,
        }])
        self.assertEqual(linhas, ["+5511999990000;Academia Tal"])

    def test_sem_nome_nem_category_grava_so_telefone(self):
        linhas = self._ciclo([{
            "normalizedPhone": "5511999990000", "phone": "",
            "name": "", "category": "", "collectedAt": None,
        }])
        self.assertEqual(linhas, ["+5511999990000"])


if __name__ == "__main__":
    unittest.main()
