"""Teste: os textos aprovados em COPYS_POR_NICHO (personal_trainer, barbearia, manicure_lash) —
conteúdo real, não um dublê. Complementa test_copias_por_nicho.py (que testa o mecanismo de
seleção com conjuntos falsos). Sem rede, sem Supabase, sem Baileys.
Rodar: python -m unittest test_textos_por_nicho -v"""
import sys
import unittest
from unittest import mock

import worker_disparo as w  # também carrega "Disparador v2.py" como w.disp

for _f in (sys.stdout, sys.stderr):
    if hasattr(_f, 'reconfigure'):
        _f.reconfigure(encoding='utf-8', errors='replace')

NICHOS = ("personal_trainer", "barbearia", "manicure_lash")
FRASES_PROIBIDAS = ("prévia", "mostrar como ficaria", "demonstração")


class TestConteudoAprovado(unittest.TestCase):
    def test_cada_nicho_tem_exatamente_quatro_copias(self):
        for nicho in NICHOS:
            self.assertEqual(len(w.disp.COPYS_POR_NICHO[nicho]), 4, nicho)

    def test_ids_seguem_o_padrao_nicho_01_a_04(self):
        for nicho in NICHOS:
            ids = [c["id"] for c in w.disp.COPYS_POR_NICHO[nicho]]
            self.assertEqual(ids, [f"{nicho}_{i:02d}" for i in range(1, 5)])

    def test_formato_igual_ao_das_copias_de_clinica(self):
        chaves_clinica = set(w.disp.COPYS[0].keys())
        for nicho in NICHOS:
            for copia in w.disp.COPYS_POR_NICHO[nicho]:
                self.assertEqual(set(copia.keys()), chaves_clinica, copia["id"])
                self.assertEqual(copia["tipo"], "aberta", copia["id"])
                self.assertEqual(copia["cta"], "", copia["id"])  # mesmo valor fixo das cópias de clínica

    def test_nenhuma_mensagem_contem_as_frases_proibidas(self):
        for nicho in NICHOS:
            for copia in w.disp.COPYS_POR_NICHO[nicho]:
                texto = copia["mensagem"].lower()
                for proibida in FRASES_PROIBIDAS:
                    self.assertNotIn(proibida, texto, f"{copia['id']}: {copia['mensagem']!r}")

    def test_toda_mensagem_tem_o_placeholder_nome(self):
        for nicho in NICHOS:
            for copia in w.disp.COPYS_POR_NICHO[nicho]:
                self.assertIn("{nome}", copia["mensagem"], copia["id"])

    def test_textos_aprovados_exatos(self):
        esperado = {
            "personal_trainer": [
                "Oi {nome}, tudo bem? Vi seu trabalho com treino. Quem cuida do seu site ou da sua presença online hoje, você mesmo?",
                "{nome}, faço sites para personal trainers com entrega no mesmo dia, depois da confirmação. Quem decide sobre isso aí é você?",
                "Oi {nome}! Muitos personais recebem contato só pelo Instagram. Vocês têm um site com link de agendamento ou só a bio?",
                "{nome}, antes de qualquer proposta: você tem interesse em um site próprio para atrair alunos? Se sim, para quando?",
            ],
            "barbearia": [
                "Oi {nome}, tudo bem? Vi a barbearia no Google. Quem cuida do site e do agendamento de vocês hoje?",
                "{nome}, faço sites para barbearias com entrega no mesmo dia, depois da confirmação. Você é quem decide sobre isso?",
                "Oi {nome}! Muita gente procura barbearia no Google antes de ir. Vocês têm site ou só o Instagram?",
                "{nome}, antes de qualquer proposta: você tem interesse em um site com agendamento online? Para quando seria?",
            ],
            "manicure_lash": [
                "Oi {nome}, tudo bem? Vi seu trabalho no Instagram. Quem cuida do seu site e do agendamento hoje, você?",
                "{nome}, faço sites para manicures e lash designers com entrega no mesmo dia, depois da confirmação. Quem decide sobre isso é você?",
                "Oi {nome}! Sua agenda ainda depende só do direct? Posso deixar isso mais organizado, se fizer sentido.",
                "{nome}, você tem interesse em um site próprio para receber agendamentos? Se sim, para quando?",
            ],
        }
        for nicho, mensagens in esperado.items():
            reais = [c["mensagem"] for c in w.disp.COPYS_POR_NICHO[nicho]]
            self.assertEqual(reais, mensagens, nicho)


class TestContatoDeNichoNuncaUsaClinica(unittest.TestCase):
    def test_personal_trainer_so_usa_copias_de_personal_trainer(self):
        ids_pt = {c["id"] for c in w.disp.COPYS_POR_NICHO["personal_trainer"]}
        ids_clinica = {c["id"] for c in w.disp.COPYS}
        escolher = w.disp.novo_seletor_de_copias()
        for _ in range(10):  # mais voltas que as 4 da rotação: nunca deveria cair na clínica
            escolhida = escolher("Personal Trainer")["id"]
            self.assertIn(escolhida, ids_pt)
            self.assertNotIn(escolhida, ids_clinica)


if __name__ == "__main__":
    unittest.main()
