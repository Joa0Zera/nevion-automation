# Dra. Luiza Alves — Harmonização Facial | Landing Page

Landing page institucional para o consultório de Harmonização Facial da Dra. Luiza Alves, em Salvador - BA. Especialidades: Preenchimento Labial, Botox, Full Face e Perfiloplastia.

## Stack utilizada

Projeto **HTML5 + CSS3 + JavaScript puro (vanilla)** — sem frameworks e sem etapa de build. Ideal para deploy direto como site estático (ex: Vercel).

- `index.html` — estrutura e conteúdo da página
- `assets/css/style.css` — identidade visual, layout responsivo e animações
- `assets/js/main.js` — menu mobile, header dinâmico, barra de progresso de scroll, scroll reveal, carousel de depoimentos, contadores animados e efeito ripple nos botões
- `assets/imagens/` — fotos reais fornecidas no briefing
- Fontes: Google Fonts (`Cormorant Garamond` para títulos, `Poppins` para textos)

## Paleta de cores

- Primária: `#4a9eff`
- Secundária: `#2d5a7a`
- Destaque: `#ffa500`

## Estrutura do projeto

```
empresa-teste/
├── index.html
├── vercel.json
├── README.md
└── assets/
    ├── css/
    │   └── style.css
    ├── js/
    │   └── main.js
    └── imagens/
        ├── Doutora.png
        ├── Espaço 1.png
        ├── Espaço 2.png
        ├── Espaço 3.png
        ├── Resultado 1.png
        ├── Resultado 2.png
        └── Resultado 3.png
```

## Seções da página

1. **Header fixo** com navegação e CTA de agendamento (menu responsivo com hambúrguer no mobile)
2. **Hero** — chamada principal, foto real da Dra. Luiza, CTAs (WhatsApp e telefone) e contador animado de avaliações no Google
3. **Sobre** — descrição real da clínica (extraída do Google Meu Negócio), com foto real do espaço
4. **Serviços** — Preenchimento Labial, Botox, Full Face e Perfiloplastia
5. **Diferenciais** — 5 pontos extraídos do perfil do Google Meu Negócio
6. **Galeria** — fotos reais de resultados e do espaço da clínica
7. **Depoimentos** — carousel automático (a cada 5s) com 3 avaliações reais de pacientes (Google), navegação por setas e dots
8. **CTA final** — chamada para agendamento
9. **Contato** — endereço, telefone, horário de funcionamento e mapa incorporado (Google Maps)
10. **Footer** e botão flutuante de WhatsApp

## Como executar localmente

Por ser um projeto 100% estático, não é necessário instalar dependências nem rodar build. Basta abrir o arquivo `index.html` diretamente no navegador, ou servir a pasta com um servidor local, por exemplo:

```bash
# Opção 1: abrir direto
# apenas dê duplo clique em index.html

# Opção 2: usando Python
python -m http.server 5500

# Opção 3: usando Node (npx serve)
npx serve .
```

Depois acesse `http://localhost:5500` (ou a porta indicada pelo servidor escolhido).

## Deploy

O arquivo `vercel.json` já está configurado para deploy como site estático (sem build):

```json
{
  "buildCommand": "",
  "outputDirectory": "."
}
```

> Nenhum deploy foi realizado — o projeto está pronto apenas para publicação futura.

## Observações

- Todas as informações de contato, endereço, horário de funcionamento e depoimentos foram extraídas exclusivamente do briefing e do perfil do Google Meu Negócio fornecidos — nenhum dado foi inventado.
- As 7 imagens fornecidas no briefing estão salvas em `assets/imagens/` e são usadas na página (Hero, Sobre, Galeria de Resultados e Galeria do Espaço) — nenhuma imagem genérica ou gerada por IA foi utilizada.
