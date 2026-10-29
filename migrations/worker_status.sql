-- Sinal de vida do worker de disparo — rodar manualmente no SQL Editor do Supabase. Idempotente.
-- O worker (worker_disparo.py) faz upsert da linha 'disparo' a cada ciclo (~20s); o Hub considera
-- o worker ligado se ultimo_sinal tiver menos de 60s.

create table if not exists worker_status (
  nome          text primary key,
  ultimo_sinal  timestamptz not null default now(),
  fase          text not null default 'aguardando_pedido'
                check (fase in ('aguardando_pedido', 'enviando', 'fora_da_janela', 'erro')),
  detalhe       text,
  atualizado_em timestamptz not null default now()
);
