"""Teste do formato de leadengine_resumo.json (sync_leadengine.py). Sem rede, sem Firestore,
sem Supabase: dados falsos direto nas funções. Rodar: python -m unittest test_sync_leadengine -v"""
import json
import os
import sys
import tempfile
import unittest
from unittest import mock

import sync_leadengine as sync

# mesmo ajuste do main() do sync_leadengine.py: sem isso, o aviso com ⚠️ quebra no console
# cp1252 padrão do Windows (TestCicloUnicoNaoDerrubaComResumoFalhando imprime um desses).
for _f in (sys.stdout, sys.stderr):
    if hasattr(_f, 'reconfigure'):
        _f.reconfigure(encoding='utf-8', errors='replace')

POR_STATUS_FALSO = {
    "CONTATADO": 10, "NAO_RESPONDEU": 3, "NOVO": 5,
    "DEMONSTROU_INTERESSE": 2, "PERDIDO": 1, "FECHADO": 4,
}


class TestGravarResumo(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.arquivo = os.path.join(tmp.name, "leadengine_resumo.json")
        p = mock.patch.object(sync, "ARQUIVO_RESUMO", self.arquivo)
        p.start()
        self.addCleanup(p.stop)

    def _ler(self):
        with open(self.arquivo, encoding="utf-8") as f:
            return json.load(f)

    def test_grava_total_por_status_e_sem_telefone_valido(self):
        sync._gravar_resumo(POR_STATUS_FALSO, 7)
        resumo = self._ler()
        self.assertEqual(resumo["total"], sum(POR_STATUS_FALSO.values()))
        self.assertEqual(resumo["por_status"], POR_STATUS_FALSO)
        self.assertEqual(resumo["novo_sem_telefone_valido"], 7)
        self.assertIn("atualizado_em", resumo)

    def test_atualizado_em_tem_fuso(self):
        sync._gravar_resumo(POR_STATUS_FALSO, 0)
        resumo = self._ler()
        # ISO com offset de fuso (ex.: "...-03:00"), não um timestamp "naive"
        self.assertRegex(resumo["atualizado_em"], r"[+-]\d{2}:\d{2}$")

    def test_grava_de_forma_atomica_sem_deixar_tmp(self):
        sync._gravar_resumo(POR_STATUS_FALSO, 0)
        self.assertTrue(os.path.exists(self.arquivo))
        self.assertFalse(os.path.exists(self.arquivo + ".tmp"))

    def test_sobrescreve_resumo_anterior(self):
        sync._gravar_resumo(POR_STATUS_FALSO, 7)
        outro = dict(POR_STATUS_FALSO, NOVO=99)
        sync._gravar_resumo(outro, 0)
        resumo = self._ler()
        self.assertEqual(resumo["por_status"]["NOVO"], 99)
        self.assertEqual(resumo["novo_sem_telefone_valido"], 0)


class TestCicloUnicoNaoDerrubaComResumoFalhando(unittest.TestCase):
    """Se a gravação do resumo falhar (Firestore fora do ar, disco cheio etc.), o ciclo
    continua: só um aviso no console, o contatos.txt já escrito não é afetado."""

    def test_falha_ao_contar_por_status_so_avisa_e_segue(self):
        with mock.patch.object(sync.disp, "_config_supabase", return_value=("http://x", "tok")), \
             mock.patch.object(sync, "le") as le_falso, \
             mock.patch.object(sync, "buscar_contatos_ja_em_disparos", return_value=set()), \
             mock.patch.object(sync, "ARQUIVO_CONTATOS", os.path.join(tempfile.mkdtemp(), "contatos.txt")):
            le_falso.buscar_leads_novo.return_value = []
            le_falso.contar_leads_por_status.side_effect = RuntimeError("Firestore fora do ar")
            sync.ciclo_unico()  # não deve levantar


if __name__ == "__main__":
    unittest.main()
