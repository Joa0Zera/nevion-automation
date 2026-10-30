"""Teste: o conjunto de cópias de abertura é escolhido pelo nicho do contato (worker_disparo.py e
Disparador v2.py). Sem rede, sem Supabase, sem Baileys. Rodar: python -m unittest test_copias_por_nicho -v"""
import sys
import types
import unittest
from unittest import mock

import worker_disparo as w  # também carrega "Disparador v2.py" como w.disp

for _f in (sys.stdout, sys.stderr):
    if hasattr(_f, 'reconfigure'):
        _f.reconfigure(encoding='utf-8', errors='replace')

URL, CHAVE = "https://exemplo.supabase.test", "chave-de-teste"


def conjunto(prefixo, nome):
    """Quatro cópias de teste (não são os textos aprovados)."""
    return [{"id": f"{prefixo}_{i}", "nome": f"{nome} {i}", "mensagem": f"[{prefixo}] texto {i} para {{nome}}", "cta": "", "tipo": "aberta"}
            for i in range(1, 5)]


FAKE = {
    "personal_trainer": conjunto("pt", "Personal"),
    "barbearia": conjunto("bb", "Barbearia"),
    "manicure_lash": conjunto("ml", "Manicure"),
}


class TestChaveDoNicho(unittest.TestCase):
    def test_reconhece_os_tres_nichos_sem_acento_nem_caixa(self):
        c = w.disp.chave_do_nicho
        self.assertEqual(c("personal_trainer"), "personal_trainer")
        self.assertEqual(c("Personal Trainer"), "personal_trainer")
        self.assertEqual(c("Treinador físico"), "personal_trainer")
        self.assertEqual(c("BARBEARIA do Zé"), "barbearia")
        self.assertEqual(c("Barber Shop"), "barbearia")
        self.assertEqual(c("Manicure e Pedicure"), "manicure_lash")
        self.assertEqual(c("Studio de Cílios (Lash)"), "manicure_lash")

    def test_vazio_outros_e_nao_especificado_nao_tem_chave(self):
        for n in ("", None, "   ", "Outros", "Não especificado", "Nao especificado", "Clínica de estética", "Dentista"):
            self.assertIsNone(w.disp.chave_do_nicho(n), n)


class TestSeletorDeCopias(unittest.TestCase):
    def setUp(self):
        p = mock.patch.dict(w.disp.COPYS_POR_NICHO, FAKE, clear=True)
        p.start()
        self.addCleanup(p.stop)

    def test_nicho_valido_usa_o_conjunto_do_nicho(self):
        escolher = w.disp.novo_seletor_de_copias()
        for nicho, prefixo in (("Personal Trainer", "pt"), ("barbearia", "bb"), ("manicure_lash", "ml")):
            self.assertTrue(escolher(nicho)["id"].startswith(prefixo), nicho)

    def test_nicho_vazio_outros_e_nao_especificado_usam_as_copias_de_clinica(self):
        ids_clinica = {c["id"] for c in w.disp.COPYS}
        escolher = w.disp.novo_seletor_de_copias()
        for nicho in ("", None, "Outros", "Não especificado", "Dentista"):
            self.assertIn(escolher(nicho)["id"], ids_clinica, repr(nicho))

    def test_rotacao_de_quatro_dentro_de_cada_conjunto_sem_misturar_os_outros(self):
        escolher = w.disp.novo_seletor_de_copias()
        # contatos de nichos diferentes intercalados: cada conjunto roda as suas quatro sem repetir antes da hora
        sequencia = ["barbearia", "", "Personal Trainer", "barbearia", "", "barbearia", "Personal Trainer", "barbearia", "", ""]
        usados = {"bb": [], "pt": [], "clinica": []}
        for nicho in sequencia:
            copia = escolher(nicho)
            usados[copia["id"].split("_")[0] if copia["id"][:2] in ("bb", "pt") else "clinica"].append(copia["id"])
        self.assertEqual(len(usados["bb"]), 4)
        self.assertEqual(len(set(usados["bb"])), 4, "as 4 cópias da barbearia, uma de cada")
        self.assertEqual(len(usados["pt"]), 2)
        self.assertEqual(len(set(usados["pt"])), 2)
        self.assertEqual(len(usados["clinica"]), 4)
        self.assertEqual(len(set(usados["clinica"])), 4)
        # a 5ª vez do mesmo conjunto volta ao início da rotação
        e2 = w.disp.novo_seletor_de_copias()
        primeiras = [e2("barbearia")["id"] for _ in range(4)]
        self.assertEqual(e2("barbearia")["id"], primeiras[0])

    def test_nicho_conhecido_com_conjunto_vazio_cai_na_clinica_com_aviso_uma_vez(self):
        with mock.patch.dict(w.disp.COPYS_POR_NICHO, {"barbearia": []}):
            escolher = w.disp.novo_seletor_de_copias()
            with mock.patch("builtins.print") as imprime:
                copias = [escolher("barbearia") for _ in range(3)]
        ids_clinica = {c["id"] for c in w.disp.COPYS}
        self.assertTrue(all(c["id"] in ids_clinica for c in copias))
        avisos = [c for c in imprime.call_args_list if "sem cópias aprovadas" in str(c)]
        self.assertEqual(len(avisos), 1)


class RequestsFalso(types.ModuleType):
    def __init__(self):
        super().__init__("requests")
        self.corpos = []

    def post(self, url, **kw):
        self.corpos.append(kw.get("json"))
        r = mock.Mock()
        r.status_code = 201
        r.text = ""
        r.raise_for_status.return_value = None
        return r


class TestWorkerEscolhePeloNicho(unittest.TestCase):
    def test_processar_pedido_envia_o_texto_do_conjunto_do_nicho_e_o_de_clinica_para_o_resto(self):
        fila = [
            ("+5511999990001", "5511999990001", "Studio A", "Barbearia"),
            ("+5511999990002", "5511999990002", "Clínica B", ""),            # nicho vazio: clínica
            ("+5511999990003", "5511999990003", "Treino C", "Personal Trainer"),
            ("+5511999990004", "5511999990004", "Linha antiga D", ""),         # linha de 2 campos no contatos.txt: nicho "" -> clínica
        ]
        enviados = []

        def envio(numero, mensagem, cta=None):
            enviados.append(mensagem)
            return (w.disp.ENVIADO, "HTTP 200", "")

        req = RequestsFalso()
        with mock.patch.dict(sys.modules, {"requests": req}), \
             mock.patch.dict(w.disp.COPYS_POR_NICHO, FAKE, clear=True), \
             mock.patch.object(w.disp, "_config_supabase", return_value=(URL, CHAVE)), \
             mock.patch.object(w.disp, "_config_baileys", return_value=("http://x", "tok")), \
             mock.patch.object(w.disp, "_teto_maximo", return_value=40), \
             mock.patch.object(w.disp, "envios_na_janela", return_value=(0, None)), \
             mock.patch.object(w.disp, "montar_fila", return_value={"fila": fila}), \
             mock.patch.object(w.disp, "pre_teste_baileys", return_value=(True, "ok")), \
             mock.patch.object(w.disp, "dentro_da_janela", return_value=True), \
             mock.patch.object(w.disp, "enviar_via_baileys", side_effect=envio), \
             mock.patch.object(w.disp, "esperar"), \
             mock.patch.object(w.disp, "salvar_disparado", return_value=True), \
             mock.patch.object(w.disp, "registrar_conversa"), \
             mock.patch.object(w, "le"):
            resultado = w.processar_pedido({"quantidade": len(fila)}, URL, CHAVE)

        self.assertEqual(resultado["enviados"], 4)
        self.assertTrue(enviados[0].startswith("[bb]"), enviados[0])
        self.assertIn("Studio A", enviados[0])
        self.assertFalse(enviados[1].startswith("["), "nicho vazio usa o texto de clínica")
        self.assertTrue(enviados[2].startswith("[pt]"), enviados[2])
        self.assertFalse(enviados[3].startswith("["), "linha de formato antigo usa o texto de clínica")


if __name__ == "__main__":
    unittest.main()
