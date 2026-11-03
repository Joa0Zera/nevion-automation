"""Consulta compartilhada ao Supabase: todo contato_normalizado já presente em
public.disparos, de qualquer status. Usada por sync_leadengine.py (pra não reimportar leads
já tentados) e por "Disparador v2.py" (pra não reenviar pra quem já tem qualquer linha lá,
mesmo sem estar no disparados.json local).

Fica num módulo neutro, sem depender de nenhum dos dois, porque cada um carrega o outro via
importlib em algum ponto da cadeia (sync_leadengine.py carrega "Disparador v2.py"; um import
de volta no nível de módulo criaria um ciclo)."""
import requests


def buscar_contatos_ja_em_disparos(url_base, chave):
    """Todo contato_normalizado já presente em public.disparos, qualquer status. Pagina de
    1000 em 1000 (o padrão do PostgREST) pra não depender de um limite implícito.

    Levanta em qualquer falha (rede, autenticação, resposta em formato inesperado) — quem
    chama decide o que fazer; aqui a regra é falhar fechado, nunca aberto."""
    existentes, offset, pagina_tam = set(), 0, 1000
    while True:
        resposta = requests.get(
            f"{url_base}/rest/v1/disparos",
            params={"select": "contato_normalizado", "offset": str(offset), "limit": str(pagina_tam)},
            headers={"apikey": chave, "Authorization": f"Bearer {chave}"},
            timeout=15,
        )
        resposta.raise_for_status()
        pagina = resposta.json()
        if not isinstance(pagina, list):
            raise ValueError("resposta inesperada de public.disparos (não é uma lista)")
        existentes.update(r["contato_normalizado"] for r in pagina if r.get("contato_normalizado"))
        if len(pagina) < pagina_tam:
            return existentes
        offset += pagina_tam
