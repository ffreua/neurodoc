# PENDÊNCIA — CNPJ da mantenedora do NeuroDoc

**Estado: RESOLVIDA em 2026-10-29.** ProntDoc Prontuários Médicos Ltda.,
CNPJ **69.887.146/0001-05**, Avenida Paulista, nº 2073, sala 2220, São
Paulo/SP (decisão D2, [DECISOES.md](DECISOES.md)). Aberta desde 2026-10-21.

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

- [x] Gravar o CNPJ na configuração da instalação de produção: console
      `/instalacao/operacao/`, cartão "Receita eletrônica com numeração do
      SNCR", campo **CNPJ da mantenedora** (pronto desde a Sprint 3; valida
      os dígitos e vai à trilha). Ele aparece também no rodapé de cada
      folha da receita eletrônica ("Identificação da plataforma").
- [x] **Contrato de adesão** (`tenancy/contract.py::CONTRATADO`): versão
      **1.2**, de 2026-10-29, com a ProntDoc. Até a 1.1 o contratado era
      pessoa física. Passar a empresa a mantenedora exige
      **versão nova** do contrato (cláusula 17.6), redigida pela Dra.
      Karina Albuquerque Freua.
- [x] **Relação de suboperadores e LGPD** (`docs/governance/suboperadores.md`,
      `docs/governance/lgpd.md`): o controlador/operador passa a ser a
      empresa — `lgpd.md` §1, §6 e §9 (a relação de suboperadores lista
      prestadores, e não o operador, e não muda).
- [x] **Página de vendas e rodapé** (`base/content.py`,
      `templates/onboarding/landing.html`): identificação da empresa.
- [x] **JSON-LD** (`base/seo.py`): a organização que publica o produto.
- [x] **README** (seção de licença e do serviço hospedado).
- [x] O teste real (D8, que substituiu a prova em homologação da D3): o
      primeiro bloco de RCE pedido pelo proprietário **em produção**,
      seguindo [ATIVACAO.md](ATIVACAO.md).
- [x] Atualizar `docs/sncr/ESTADO_EXECUCAO.md` e este arquivo.

## Onde procurar

- Decisão: [DECISOES.md](DECISOES.md), D2.
- Fundamento: [SPRINT-0-RELATORIO.md](SPRINT-0-RELATORIO.md), seções 1 e 9.
- Estado da integração: [ESTADO_EXECUCAO.md](ESTADO_EXECUCAO.md).
