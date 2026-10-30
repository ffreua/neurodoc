# SNCR — estado de execução

Registro de continuidade da integração NeuroDoc × SNCR (Anvisa). Leia
antes de retomar o trabalho, **e confira contra o código atual**: este
arquivo resume, não substitui a inspeção.

| Campo | Valor |
| --- | --- |
| Sprint / gate | **EM PRODUÇÃO desde 2026-10-29** (1.29). Teste real (D8) bem-sucedido |
| Branch | `main` |
| Produção | **ligada, ambiente Produção**, CNPJ 69.887.146/0001-05 (ProntDoc). Primeiro bloco real: RCE `2610.6-35.049779001` a `2610.6-35.049780000`, pedido em 2026-10-29 às 23:26 pelo Gov.br do Dr. Fernando; primeira RCE eletrônica assinada com o número `2610.6-35.049779001`, **AUTORIZADA** no portal da Anvisa |
| Bloqueio para ativar | nenhum — CNPJ resolvido ([PENDENCIA-CNPJ.md](PENDENCIA-CNPJ.md)) |
| Decisões | [DECISOES.md](DECISOES.md) — D1 a D8 do proprietário, I1 a I16 de implementação |
| Ativação e reversão | [ATIVACAO.md](ATIVACAO.md) — o passo a passo de publicar desligada, ligar, o teste real e voltar atrás |
| Ajuda | publicada na 1.29: `base/help_content.py`, artigo `receita-sncr` (o rascunho em [AJUDA.md](AJUDA.md) fica como histórico) |
| Relatório da Sprint 0 | [SPRINT-0-RELATORIO.md](SPRINT-0-RELATORIO.md) |

## Onde está cada coisa

| O quê | Onde |
| --- | --- |
| A RCE impressa não é assinada digitalmente (D1, permanente desde a 1.29; os avisos transitórios saíram) | `documents/rce_impressa.py`, `documents/templatetags/rce_impressa.py`, roteiro `check_rce_impressa` |
| Receita no atendimento (1.29) | botão em `templates/clinical/detail.html` e `detail_livre.html`, `documents/views.py::_receita_pedida`, saldo em `sncr/templatetags/sncr_receita.py::saldos_sncr`, roteiro `check_sncr_prontuario` |
| Lista oficial das substâncias controladas (D7) | `catalogs/portaria344.py` (parser estrito do ato), `catalogs/controlados.py` (importação e classificação), comando `import_portaria344` (roda no **worker**), migração `catalogs/0009`, cópia do ato em `catalogs/data/portaria344-rdc1036-2026.html`, roteiro `check_portaria344` |
| App `sncr`: configuração, pedido, bloco, número | `sncr/models.py` (`Configuracao` **desligada** por padrão), migração `sncr/0001` |
| Cliente da API (o único lugar que conhece o formato da Anvisa) | `sncr/cliente.py` — desfechos classificados; o que é suposição até o teste real (D8) está aqui |
| Login Gov.br e pedido de bloco | `sncr/fluxo.py`, `sncr/views.py` (o POST responde com `templates/sncr/entrar.html`, que abre o Gov.br por link — a CSP `form-action 'self'` recusaria o redirecionamento), `sncr/urls.py` (`/app/sncr/`), tarefa `sncr/tasks.py` (pedido parado vira incerto; login abandonado vira expirado) |
| Reserva e consumo de números | `sncr/numeracao.py` — `reservar` (um), `reservar_varios` (um por folha, I12), `consumir`, `marcar_perdido`, `numeros_do_documento` |
| Regra da receita eletrônica | `sncr/receita.py` — itens, quantidade por extenso, classificação, limites (3 medicamentos por emissão; art. 57 por folha) |
| PDF no modelo da Anvisa | `sncr/pdf_oficial.py` + `sncr/modelos/rce_eletronica_anvisa.pdf` (SHA-256 conferido) — uma folha por medicamento |
| Emissão e assinatura | `documents/issuance.py` (`_conteudo_da_receita`, `_reservar_numeros_sncr`, consumo depois de assinado), despacho do PDF em `documents/pdf/prescription.py` |
| Telas | `documents/forms.py` e `templates/documents/medical_form.html` (os 3 medicamentos estruturados, só com o SNCR ligado), `templates/documents/medical_detail.html` + `sncr/templatetags/sncr_receita.py` (números e classificação), link "Numeração SNCR" no menu (`templates/partials/sidebar.html`, `base/context_processors.py`) |
| Console da instalação (ligar, ambiente, CNPJ) | `ops/superadmin.py::SncrInstallationView` e `sncr_resumo`, rota `/instalacao/operacao/sncr/`, cartão em `templates/ops/superadmin/operations.html` |
| Conferência do pedido incerto | `sncr/fluxo.py::resolver_incerto`, `sncr/views.py::ConferirPedidoView`, rota `/app/sncr/pedido/<id>/conferir/`, formulário no `templates/sncr/painel.html` |
| Contingência: refazer como impressa | `documents/issuance.py::converter_para_impressa`, `documents/views.py::MedicalDocumentToPaperView`, rota `medical/<id>/refazer-impressa/`, parcial `templates/documents/_refazer_impressa.html` |
| Aviso de 31/10 com a integração ligada | `documents/sncr_transicao.py::aviso` (`_integracao_ligada`) |
| Roteiros | `check_sncr_numeracao` (Sprint 1, Anvisa simulada), `check_sncr_receita` (Sprint 2, **assinatura PAdES real** com certificado de teste), `check_sncr_contingencia` (Sprint 3) |

## Sprint 1 — numeração (concluída)

Cliente, login Gov.br com a troca **na requisição** (I5), pedido preso à
sessão do navegador e de uso único, desfecho incerto **sem repetição**
(I6), números com `UNIQUE` e reserva com `skip_locked` só na linha do
número (I7), faixa irreconhecível não utilizável (I8). Anvisa
**simulada** — o teste real é o primeiro pedido em produção (D8).

## Sprint 2 — a receita eletrônica (concluída na branch)

- **Formatos novos** na receita: "Controle especial — eletrônica com
  numeração do SNCR" e "Sujeita à retenção — eletrônica". Só aparecem com
  `Configuracao.ativo`; a receita simples e a RCE impressa não mudaram.
- **Até 3 medicamentos estruturados** (nome, concentração, forma,
  quantidade, posologia); a quantidade ganha o extenso sozinha, com o
  gênero certo.
- **Classificação pela lista oficial** (D7, I11): marca resolvida pela
  CMED; Notificação (A/B fora do adendo) e proscrita recusadas; adendo e
  nome desconhecido exigem a confirmação do médico; controlado na RET
  recusado (FAQ P48).
- **Uma folha por medicamento, cada uma com o seu número SNCR** (I12),
  numa assinatura PAdES só. Faltando número para alguma folha, nenhuma sai
  e nenhum é gasto. Os números são consumidos só depois de assinado e
  ficam em `signature_metadata['sncr']['numeros']`, na ordem das folhas.
- **PDF da RCE escrito sobre o modelo oficial** (I13); a RET, sem modelo
  oficial, com a mesma estrutura desenhada. Sem timbre da clínica (D6).
  Rascunho com "RASCUNHO — SEM VALIDADE" e sem número; número de
  homologação com "HOMOLOGAÇÃO — SEM VALIDADE".
- **A eletrônica não sai em papel nem é retificada** (I10). QR para a
  verificação do NeuroDoc (I9).
- **Evidência:** `check_sncr_receita` verde (inclui assinatura válida e as
  duas folhas conferidas uma a uma); as duas folhas de uma receita de dois
  medicamentos inspecionadas em imagem em 2026-10-21; **bateria completa:
  120 roteiros, nenhuma falha** (2026-10-21, imagem reconstruída).

## Sprint 3 — contingência e preparação (concluída na branch)

- **Console da instalação** (I16): CNPJ da mantenedora, ambiente e a
  chave, com desligar em um clique e ligar com CNPJ válido, `LIGAR` e
  motivo na trilha; números, médicos com bloco e pedidos incertos à vista.
- **Pedido incerto conferido pelo médico** (I14), no painel: "nenhum bloco
  foi gerado" ou a faixa de exatamente 1.000 números vista no portal.
- **Contingência** (I15): "Refazer como receita impressa" no rascunho
  eletrônico, com confirmação; as recusas da assinatura apontam o botão.
- **Aviso de 31/10** apontando a eletrônica quando ligada; a trava da RCE
  impressa assinada digitalmente continua.
- **Documentos:** [ATIVACAO.md](ATIVACAO.md) (publicar, ligar, teste real,
  reverter, monitorar) e [AJUDA.md](AJUDA.md) (artigo pronto, publicado só
  na ativação).
- **Evidência:** `check_sncr_contingencia` verde (41 itens); **bateria
  completa: 121 roteiros, nenhuma falha** (2026-10-21, imagem reconstruída).

## Em produção (2026-10-29)

- **Teste real (D8):** o pedido pelo Gov.br funcionou na primeira tentativa
  em produção, com a troca do `session_id` pelo servidor e o `Origin` do
  `PUBLIC_BASE_URL` — as suposições da lacuna L7 se confirmaram. O número
  real tem a forma `AAMM.T-UF.NNNNNNNNN` (`2610.6-35.049779001`: outubro de
  2026, tipo 6, UF 35 = SP) e foi enumerado sem ajuste.
- **A homologação não foi usada:** o login Gov.br de treinamento seguia
  falhando do lado da Anvisa (o "staging" do Gov.br). Os quatro pedidos em
  homologação/abandonados do dia ficaram "aguardando login" e passaram a
  expirar sozinhos.
- **Prorrogação:** em 2026-10-29 a Diretoria Colegiada da Anvisa aprovou
  estender até 03/03/2027 a transição da RCE/RET eletrônicas sem numeração.
  A trava da RCE impressa assinada digitalmente foi **mantida** (decisão do
  proprietário, mesma data).

## Próxima ação

1. Acompanhar os primeiros blocos dos outros médicos (console: pedidos
   incertos em vermelho).
2. Notificações de Receita (A, B, B2) continuam fora do escopo (D5).
3. Catálogo de antimicrobianos e GLP-1 para a RET (hoje ela aceita o que não
   é controlado da Portaria 344 e confia no médico para o resto).

## Pendências

- **CNPJ da mantenedora** — [PENDENCIA-CNPJ.md](PENDENCIA-CNPJ.md).
- Prova de login no SNCR de **treinamento**: bloqueada há dias pela
  própria Anvisa ("Erro ao buscar inscrições de conselhos"); substituída
  pela D8.
- A lista de **antimicrobianos e GLP-1** (RET) é outra norma, sem
  catálogo ainda: hoje a RET aceita o que **não** é controlado da
  Portaria 344 e confia no médico para o resto.
- Notificações de Receita (A, B, B2): fora do escopo (D5).

## Riscos registrados

Ver relatório da Sprint 0, seção 8. Acrescentados na Sprint 2:

- **Formato real da resposta da Anvisa** só se conhece no teste real (D8);
  o ajuste fica em `sncr/cliente.py`.
- **Número vira texto no PDF antes de a assinatura terminar.** Se a
  assinatura falhar, a transação devolve os números a livre — seguro
  porque aquele PDF nunca saiu do servidor (`_reservar_numeros_sncr`).
