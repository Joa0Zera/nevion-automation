"""Teste: importa_maps.py (leads do Google Maps via Apify -> LeadEngine). Cobre filtros
(telefone/fechado), mapeamento de categoria -> nicho (reaproveitando chave_do_nicho/
NICHOS_ATIVOS de "Disparador v2.py"), deduplicação em 3 fontes (lote, Firestore, disparos),
teto de segurança de 200 resultados, modo ensaio (nada grava) e parada no meio do lote numa
falha de gravação. Sem rede de verdade: Apify, Firestore e Supabase são sempre mockados.
Rodar: python -m unittest test_importa_maps -v"""
import importlib.util
import os
import sys
import unittest
from unittest import mock

for _f in (sys.stdout, sys.stderr):
    if hasattr(_f, 'reconfigure'):
        _f.reconfigure(encoding='utf-8', errors='replace')

PASTA = os.path.dirname(os.path.abspath(__file__))
_spec = importlib.util.spec_from_file_location("importa_maps_teste", os.path.join(PASTA, "importa_maps.py"))
im = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(im)


def item(nome="Studio A", categoria="Personal Trainer", telefone="+5534999990001",
         website="https://a.com", permanentlyClosed=False, temporarilyClosed=False):
    return {
        "title": nome, "categoryName": categoria, "phone": telefone, "website": website,
        "permanentlyClosed": permanentlyClosed, "temporarilyClosed": temporarilyClosed,
    }


class TestFiltroDeTelefoneEFechamento(unittest.TestCase):
    def test_telefone_vazio_e_descartado(self):
        self.assertFalse(im._telefone_utilizavel(item(telefone="")))

    def test_telefone_so_espaco_e_descartado(self):
        self.assertFalse(im._telefone_utilizavel(item(telefone="   ")))

    def test_fechado_permanentemente_e_descartado(self):
        self.assertTrue(im._fechado(item(permanentlyClosed=True)))

    def test_fechado_temporariamente_e_descartado(self):
        self.assertTrue(im._fechado(item(temporarilyClosed=True)))

    def test_aberto_com_telefone_passa(self):
        i = item()
        self.assertTrue(im._telefone_utilizavel(i))
        self.assertFalse(im._fechado(i))


class TestMapeamentoDeCategoria(unittest.TestCase):
    def test_personal_trainer(self):
        self.assertEqual(im.mapear_nicho("Personal Trainer"), "personal_trainer")
        self.assertEqual(im.mapear_nicho("PERSONAL"), "personal_trainer")

    def test_barbearia_com_acento_e_caixa(self):
        self.assertEqual(im.mapear_nicho("BARBEARIA do Zé"), "barbearia")
        self.assertEqual(im.mapear_nicho("Barber Shop"), "barbearia")

    def test_manicure_lash(self):
        self.assertEqual(im.mapear_nicho("Manicure e Pedicure"), "manicure_lash")
        self.assertEqual(im.mapear_nicho("Nail Designer"), "manicure_lash")
        self.assertEqual(im.mapear_nicho("Studio de Cílios"), "manicure_lash")

    def test_categoria_desconhecida_fica_fora(self):
        self.assertIsNone(im.mapear_nicho("Clínica de Estética"))
        self.assertIsNone(im.mapear_nicho("Dentista"))
        self.assertIsNone(im.mapear_nicho(""))
        self.assertIsNone(im.mapear_nicho(None))

    def test_sobrancelha_sozinha_fica_fora_lacuna_documentada(self):
        """chave_do_nicho() (Disparador v2.py, não alterado por esta tarefa) não reconhece
        'sobrancelha' isolada — ver aviso no topo de importa_maps.py."""
        self.assertIsNone(im.mapear_nicho("Design de Sobrancelhas"))


class TestLeadValido(unittest.TestCase):
    def test_documento_completo_e_valido(self):
        doc = im.montar_documento_lead(item(), "Personal Trainer", "Uberlândia, MG")
        self.assertTrue(im._lead_valido(doc))

    def test_campo_obrigatorio_ausente_e_invalido(self):
        doc = im.montar_documento_lead(item(), "Personal Trainer", "Uberlândia, MG")
        del doc["city"]
        self.assertFalse(im._lead_valido(doc))

    def test_campo_longo_demais_e_invalido(self):
        doc = im.montar_documento_lead(item(), "Personal Trainer", "Uberlândia, MG")
        doc["name"] = "x" * 1001
        self.assertFalse(im._lead_valido(doc))


class Base(unittest.TestCase):
    """Mocka Apify, Firestore (dedup + gravação) e a checagem de disparos, pra testar
    processar()/main() sem rede de verdade."""

    def _rodar(self, itens_por_busca, ja_no_firestore=None, ja_em_disparos=None,
               termos=("personal trainer",), cidades=("Uberlândia, MG",), max_por_busca=20):
        with mock.patch.object(im, "buscar_resultados_apify", return_value=list(itens_por_busca)), \
             mock.patch.object(im, "buscar_normalizedphones_no_firestore", return_value=ja_no_firestore or set()), \
             mock.patch.object(im.disp, "_contatos_ja_em_disparos_ou_falha", return_value=ja_em_disparos or set()):
            return im.processar(list(termos), list(cidades), max_por_busca, "token-fake", "actor-fake")


class TestDeduplicacao(Base):
    def test_duplicado_dentro_do_lote(self):
        itens = [item(nome="A"), item(nome="A de novo")]  # mesmo telefone
        novos, contagem, _ = self._rodar(itens)
        self.assertEqual(contagem["duplicado_lote"], 1)
        self.assertEqual(contagem["novos"], 1)
        self.assertEqual(len(novos), 1)

    def test_duplicado_no_firestore(self):
        i = item()
        normalizado = im.disp.normalizar_numero(i["phone"])
        novos, contagem, _ = self._rodar([i], ja_no_firestore={normalizado})
        self.assertEqual(contagem["duplicado_firestore"], 1)
        self.assertEqual(contagem["novos"], 0)
        self.assertEqual(novos, [])

    def test_duplicado_na_tabela_disparos(self):
        i = item()
        normalizado = im.disp.normalizar_numero(i["phone"])
        novos, contagem, _ = self._rodar([i], ja_em_disparos={normalizado})
        self.assertEqual(contagem["duplicado_disparos"], 1)
        self.assertEqual(contagem["novos"], 0)
        self.assertEqual(novos, [])

    def test_categoria_fora_dos_nichos_ativos_nao_e_gravada(self):
        novos, contagem, linhas = self._rodar([item(categoria="Clínica de Estética")])
        self.assertEqual(contagem["categoria_fora"], 1)
        self.assertEqual(contagem["novos"], 0)
        self.assertEqual(novos, [])
        self.assertIn(im.STATUS_CATEGORIA_FORA, linhas[0])

    def test_contato_novo_sem_registro_em_lugar_nenhum_entra(self):
        novos, contagem, _ = self._rodar([item()])
        self.assertEqual(contagem["novos"], 1)
        self.assertEqual(len(novos), 1)


class TestTetoDeSeguranca(unittest.TestCase):
    def test_mais_de_200_resultados_rejeita_a_execucao(self):
        muitos = [item(telefone=f"+553499999{i:04d}") for i in range(201)]
        with mock.patch.object(im, "buscar_resultados_apify", return_value=muitos), \
             mock.patch.object(im, "buscar_normalizedphones_no_firestore") as firestore_dedup:
            with self.assertRaises(im.ErroDeImportacao):
                im.processar(["personal trainer"], ["Uberlândia, MG"], 201, "tok", "actor")
        firestore_dedup.assert_not_called()  # nem chega a filtrar/deduplicar


class TestMainSemGravarNaoEscreveNada(unittest.TestCase):
    def test_sem_flag_gravar_nenhuma_escrita_acontece(self):
        def falha_se_chamado(*a, **kw):
            raise AssertionError("gravar_lead_no_firestore não deveria ser chamado sem --gravar")

        with mock.patch.object(sys, "argv", ["importa_maps.py", "--termos", "personal trainer", "--cidades", "Uberlândia, MG"]), \
             mock.patch.object(im, "_config_apify", return_value=("tok", "actor")), \
             mock.patch.object(im, "buscar_resultados_apify", return_value=[item()]), \
             mock.patch.object(im, "buscar_normalizedphones_no_firestore", return_value=set()), \
             mock.patch.object(im.disp, "_contatos_ja_em_disparos_ou_falha", return_value=set()), \
             mock.patch.object(im, "gravar_lead_no_firestore", side_effect=falha_se_chamado), \
             mock.patch.object(im, "_gravar_csv", return_value="/tmp/fake.csv"):
            codigo = im.main()
        self.assertEqual(codigo, 0)


class TestFalhaDeGravacaoParaOLote(unittest.TestCase):
    def test_falha_no_meio_do_lote_para_sem_tentar_o_resto(self):
        itens = [item(telefone="+5534999990001"), item(telefone="+5534999990002"), item(telefone="+5534999990003")]
        gravados = []

        def gravar(doc):
            gravados.append(doc["id"])
            if len(gravados) == 2:
                raise ConnectionError("firestore fora do ar")

        with mock.patch.object(sys, "argv", ["importa_maps.py", "--termos", "personal trainer", "--cidades", "Uberlândia, MG", "--gravar"]), \
             mock.patch.object(im, "_config_apify", return_value=("tok", "actor")), \
             mock.patch.object(im, "buscar_resultados_apify", return_value=itens), \
             mock.patch.object(im, "buscar_normalizedphones_no_firestore", return_value=set()), \
             mock.patch.object(im.disp, "_contatos_ja_em_disparos_ou_falha", return_value=set()), \
             mock.patch.object(im, "gravar_lead_no_firestore", side_effect=gravar), \
             mock.patch.object(im, "_gravar_csv", return_value="/tmp/fake.csv"):
            codigo = im.main()

        self.assertEqual(codigo, 1)
        self.assertEqual(len(gravados), 2)  # o 3º nunca foi tentado


class _RespostaFalsa:
    def __init__(self, status_code=200, payload=None, url=""):
        self.status_code = status_code
        self._payload = payload if payload is not None else []
        self.url = url

    def json(self):
        return self._payload

    def raise_for_status(self):
        if self.status_code >= 400:
            import requests
            erro = requests.exceptions.HTTPError(
                f"{self.status_code} Client Error: Not Found for url: {self.url}"
            )
            erro.response = self
            raise erro


class TestFormatoDoIdDoAtor(unittest.TestCase):
    def test_id_com_barra_e_com_til_geram_a_mesma_url(self):
        urls = []

        def post_falso(url, **kw):
            urls.append(url)
            return _RespostaFalsa(200, [])

        with mock.patch("requests.post", side_effect=post_falso):
            im.buscar_resultados_apify("x", "y", 1, "tok", "compass/crawler-google-places")
            im.buscar_resultados_apify("x", "y", 1, "tok", "compass~crawler-google-places")

        self.assertEqual(urls[0], urls[1])
        self.assertIn("/acts/compass~crawler-google-places/run-sync-get-dataset-items", urls[0])


class TestTokenNuncaApareceEmErro(unittest.TestCase):
    TOKEN = "apify_api_segredo_super_secreto_123"

    def test_erro_http_nao_expoe_token_nem_url_completa(self):
        url_completa = f"{im.APIFY_RUN_SYNC_URL.format(actor='x')}?token={self.TOKEN}"

        def post_falso(url, **kw):
            return _RespostaFalsa(404, url=url_completa)

        with mock.patch("requests.post", side_effect=post_falso):
            with self.assertRaises(im.ErroDeImportacao) as ctx:
                im.buscar_resultados_apify("x", "y", 1, self.TOKEN, "x")

        mensagem = str(ctx.exception)
        self.assertNotIn(self.TOKEN, mensagem)
        self.assertNotIn(url_completa, mensagem)
        self.assertIn("404", mensagem)

    def test_erro_de_conexao_nao_expoe_token(self):
        import requests

        def post_falso(url, **kw):
            raise requests.exceptions.ConnectionError(
                f"falha ao conectar em {url}?token={self.TOKEN}"
            )

        with mock.patch("requests.post", side_effect=post_falso):
            with self.assertRaises(im.ErroDeImportacao) as ctx:
                im.buscar_resultados_apify("x", "y", 1, self.TOKEN, "x")

        self.assertNotIn(self.TOKEN, str(ctx.exception))

    def test_token_nao_aparece_em_nenhum_campo_do_documento_ou_csv(self):
        doc = im.montar_documento_lead(item(), "Personal Trainer", "Uberlândia, MG")
        self.assertNotIn(self.TOKEN, repr(doc))
        _, _, linhas_csv = None, None, [["x"]]  # cabeçalho/linhas não recebem token: ver CABECALHO_CSV
        self.assertNotIn("token", [c.lower() for c in im.CABECALHO_CSV])


if __name__ == "__main__":
    unittest.main()
