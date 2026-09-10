# Nevion Automation

Pipeline que transforma uma resposta de WhatsApp em um site publicado — do "sim" do lead ao deploy em produção, em menos de 10 minutos, sem gate manual antes da publicação.

> **EN**: End-to-end automation that turns a WhatsApp lead reply into a production-deployed website, with no manual gate before publish — from trigger to live in under 10 minutes.

## Como funciona

```
WhatsApp (Baileys)  →  n8n (webhook)  →  ponte.py  →  Claude Code  →  GitHub CLI  →  Vercel
   detecta gatilho      orquestra         prepara         gera o        cria o        publica
                                            os dados        site         repositório
```

1. **Baileys** monitora a conversa e detecta a palavra-gatilho na resposta do lead
2. **n8n** recebe o webhook e dispara o pipeline
3. **`ponte.py`** busca o lead pelo telefone, converte as cores informadas (PT → hex) e enriquece com dados do Google Meu Negócio
4. **Claude Code** gera o site com um prompt versionado e restrito: cores exatas do cliente, imagens reais fornecidas, estrutura baseada em referências de alta conversão já validadas em sites anteriores
5. **GitHub CLI** cria o repositório automaticamente
6. **Vercel** publica — o site já é enviado pronto para o cliente, sem revisão humana antes do ar

## Qualidade do output e onde o humano entra

O pipeline já gerou e publicou entre 10 e 30 sites de ponta a ponta sem gate manual. Não existe etapa de aprovação antes do deploy — o site vai ao ar sozinho.

Onde eu entro: depois da publicação, o cliente normalmente pede pequenos ajustes de texto, cor ou seção — o mesmo tipo de rodada de revisão que existe em qualquer entrega de site, feita por IA ou não. Não é a IA "errando" e eu corrigindo; é o ciclo comercial normal de pegar feedback do cliente.

Isso funciona porque o prompt é restrito o suficiente (cores, imagens e estrutura vêm de dados reais do lead, não de geração livre) para o resultado já sair em nível de produção na primeira tentativa, e generoso o bastante pra cada site não parecer um template repetido.

## O que ainda não está instrumentado (próximos passos)

- Custo por site gerado (tokens da API) — hoje não é medido; é o próximo ponto de instrumentação antes de escalar o volume de leads simultâneos
- Taxa de revisão pós-entrega por categoria (cor, texto, seção) — ajudaria a apertar ainda mais o prompt
- Validação automática de acessibilidade/performance antes do deploy (hoje é confiança no prompt, não checagem automatizada)

## Stack

- Python (orquestração)
- Baileys (WhatsApp Web API)
- n8n (automação/webhooks)
- Claude Code (geração do site, prompt versionado)
- GitHub CLI + Vercel (versionamento e deploy)

## Por que existe

Construído para a Nevion, agência de landing pages para clínicas de estética. Reduz o tempo entre "lead interessado" e "site no ar" de horas de trabalho manual para minutos, sem abrir mão de fidelidade à identidade visual do cliente.

## Status

Em produção. Próximo passo é instrumentar custo e taxa de revisão antes de escalar para lotes maiores de leads simultâneos.
