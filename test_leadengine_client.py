"""Teste: leadengine_client.buscar_leads_novo() devolve o campo `category` de cada lead, com
CATEGORIA_PADRAO ("Não especificado") quando o documento não tem esse campo (ou vem vazio).
Sem rede, sem Firestore, sem credencial de verdade: `requests` e `_token_bearer` são trocados
por dublês. Rodar: python -m unittest test_leadengine_client -v"""
import sys
import types
import unittest
from unittest import mock

import leadengine_client as le

for _f in (sys.stdout, sys.stderr):
    if hasattr(_f, 'reconfigure'):
        _f.reconfigure(encoding='utf-8', errors='replace')


def _doc(nome, campos):
    return {"document": {"name": f"projects/x/databases/(default)/documents/leads/{nome}", "fields": campos}}


class RequestsFalso(types.ModuleType):
    def __init__(self, documentos):
        super().__init__("requests")
        self.documentos = documentos

    def post(self, url, **kw):
        r = mock.Mock()
        r.raise_for_status.return_value = None
        r.json.return_value = self.documentos
        return r


class TestBuscarLeadsNovoCategoria(unittest.TestCase):
    def _buscar(self, documentos):
        req = RequestsFalso(documentos)
        with mock.patch.dict(sys.modules, {"requests": req}), \
             mock.patch.object(le, "_token_bearer", return_value={"Authorization": "Bearer x"}):
            return le.buscar_leads_novo()

    def test_category_presente_vem_no_lead(self):
        leads = self._buscar([_doc("abc", {
            "phone": {"stringValue": "+5511999990000"},
            "normalizedPhone": {"stringValue": "5511999990000"},
            "name": {"stringValue": "Academia Tal"},
            "category": {"stringValue": "personal_trainer"},
        })])
        self.assertEqual(leads[0]["category"], "personal_trainer")

    def test_category_ausente_cai_no_padrao(self):
        leads = self._buscar([_doc("abc", {
            "phone": {"stringValue": "+5511999990000"},
            "normalizedPhone": {"stringValue": "5511999990000"},
            "name": {"stringValue": "Academia Tal"},
        })])
        self.assertEqual(leads[0]["category"], le.CATEGORIA_PADRAO)
        self.assertEqual(le.CATEGORIA_PADRAO, "Não especificado")

    def test_category_vazia_cai_no_padrao(self):
        leads = self._buscar([_doc("abc", {"category": {"stringValue": ""}})])
        self.assertEqual(leads[0]["category"], le.CATEGORIA_PADRAO)


if __name__ == "__main__":
    unittest.main()
