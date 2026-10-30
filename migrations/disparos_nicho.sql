-- Nicho do contato (personal_trainer, barbearia, manicure_lash, ou vazio/"Não especificado"
-- pra quem cai nas cópias de clínica) — rodar manualmente no SQL Editor do Supabase. Idempotente.
-- Gravado em worker_disparo.py/"Disparador v2.py" a cada envio, igual a disparos.nome.

alter table disparos add column if not exists nicho text;
