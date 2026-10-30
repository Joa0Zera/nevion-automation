"""Teste: trava contra duas instâncias do worker_disparo.py rodando ao mesmo tempo
(worker_disparo.lock, via msvcrt.locking — Windows). Usa a trava REAL (sem mock de msvcrt,
que esconderia a lógica de verdade): se msvcrt não existir no ambiente de teste, os testes
são pulados (a trava é específica de Windows; não há como validar a lógica real sem ela, e
um fallback simulado não provaria que a trava de verdade funciona). Rodar:
python -m unittest test_worker_trava -v"""
import os
import sys
import tempfile
import unittest
from unittest import mock

import worker_disparo as w

for _f in (sys.stdout, sys.stderr):
    if hasattr(_f, 'reconfigure'):
        _f.reconfigure(encoding='utf-8', errors='replace')

try:
    import msvcrt  # noqa: F401
    _MSVCRT_DISPONIVEL = True
except ImportError:
    _MSVCRT_DISPONIVEL = False


@unittest.skipUnless(
    _MSVCRT_DISPONIVEL,
    "msvcrt só existe no Windows — a trava é específica da plataforma (LK_NBLCK); sem ele "
    "não dá pra testar a lógica real sem substituir a própria implementação do lock.",
)
class TestTravaUnica(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self._pasta_original = w.PASTA
        w.PASTA = tmp.name
        self.addCleanup(lambda: setattr(w, "PASTA", self._pasta_original))
        self._tmp = tmp.name

    def test_trava_ocupada_impede_segunda_instancia(self):
        primeira = w.adquirir_trava_unica()
        self.assertIsNotNone(primeira, "a primeira chamada, com a trava livre, deveria conseguir")
        try:
            segunda = w.adquirir_trava_unica()
            self.assertIsNone(segunda, "uma segunda instância não deveria conseguir a trava")
        finally:
            primeira.close()

    def test_trava_livre_segue_normalmente(self):
        arquivo = w.adquirir_trava_unica()
        self.assertIsNotNone(arquivo)
        arquivo.close()
        # liberada (handle fechado): uma nova tentativa consegue de novo
        outra = w.adquirir_trava_unica()
        self.assertIsNotNone(outra)
        outra.close()

    def test_arquivo_de_lock_nao_e_apagado_ao_liberar(self):
        caminho = os.path.join(self._tmp, w.ARQUIVO_LOCK)
        arquivo = w.adquirir_trava_unica()
        arquivo.close()
        self.assertTrue(os.path.exists(caminho), "o arquivo de lock deve continuar existindo depois de liberado")

    def test_main_nao_inicia_o_loop_quando_a_trava_esta_ocupada(self):
        """Integração: com a trava ocupada por 'outra instância', main() nem chega a ler
        config nem a chamar rodar_loop() — sai direto com código != 0."""
        primeira = w.adquirir_trava_unica()
        try:
            with mock.patch.object(w, "rodar_loop") as loop_falso:
                codigo = w.main()
        finally:
            primeira.close()
        self.assertNotEqual(codigo, 0)
        loop_falso.assert_not_called()


if __name__ == "__main__":
    unittest.main()
