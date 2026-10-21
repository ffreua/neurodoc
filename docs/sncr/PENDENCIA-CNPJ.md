# PENDÊNCIA — CNPJ da mantenedora do NeuroDoc

**Estado: ABERTA desde 2026-10-21.** O proprietário (Dr. Fernando Freua)
está constituindo a empresa e informa o CNPJ em alguns dias (decisão D2,
[DECISOES.md](DECISOES.md)).

> **Para quem retoma o trabalho:** enquanto este arquivo disser
> "ABERTA", **não existe CNPJ** para pôr no pedido de numeração do SNCR.
> Não use o CNPJ de nenhuma clínica cliente (FAQ Integração P34), nem
> invente um. Pergunte ao proprietário se ele já chegou.

## Por que é preciso

O pedido de numeração de RCE e RET (`POST
numeracoes/receita-especial-retencao`) leva o campo `cnpj`, obrigatório,
com o CNPJ da **empresa mantenedora do serviço de prescrição** — não o da
clínica onde o médico atende (Manual da API SNCR v5, §2.3.2.3; Perguntas
e Respostas — Integração, P34). Sem ele, o pedido de bloco não é feito.

## O que está pronto para recebê-lo

- O CNPJ é **configuração da instalação**, nunca código: cada instalação
  (a de neurodoc.app.br e qualquer autohospedada) informa o seu.
- Enquanto vazio, a numeração **recusa pedir bloco**, com a mensagem de
  que falta o CNPJ da mantenedora; nada mais no NeuroDoc depende dele.

## Quando o CNPJ chegar — lista de mudanças

Marcar cada item ao concluir, e trocar o estado lá em cima para
**RESOLVIDA**, com a data.

- [ ] Gravar o CNPJ na configuração da instalação de produção (console
      `/instalacao/operacao/`, campo do SNCR) e no `.env.example` como
      exemplo vazio.
- [ ] **Contrato de adesão** (`tenancy/contract.py::CONTRATADO`): hoje o
      contratado é pessoa física. Passar a empresa a mantenedora exige
      **versão nova** do contrato (cláusula 17.6), redigida pela Dra.
      Karina Albuquerque Freua.
- [ ] **Relação de suboperadores e LGPD** (`docs/governance/suboperadores.md`,
      `docs/governance/lgpd.md`): o controlador/operador passa a ser a
      empresa.
- [ ] **Página de vendas e rodapé** (`base/content.py`,
      `templates/onboarding/landing.html`): identificação da empresa.
- [ ] **JSON-LD** (`base/seo.py`): a organização que publica o produto.
- [ ] **README** (seção de licença e do serviço hospedado).
- [ ] Prova de comunicação: o **bloco de RCE em homologação** autorizado
      na D3 (um só, no ambiente de treinamento).
- [ ] Atualizar `docs/sncr/ESTADO_EXECUCAO.md` e este arquivo.

## Onde procurar

- Decisão: [DECISOES.md](DECISOES.md), D2.
- Fundamento: [SPRINT-0-RELATORIO.md](SPRINT-0-RELATORIO.md), seções 1 e 9.
- Estado da integração: [ESTADO_EXECUCAO.md](ESTADO_EXECUCAO.md).
