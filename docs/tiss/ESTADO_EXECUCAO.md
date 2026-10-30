# TISS — estado da execução

Onde retomar o módulo de faturamento TISS. A revisão que precedeu o código,
com as fontes oficiais e os hashes, está em `REVISAO_SPRINT1.md`.

Classificação usada abaixo, a do prompt do módulo: **implementado**,
**validado por XSD**, **validado por regras**, **aceito em homologação da
operadora** e **liberado em produção** são coisas diferentes.

## Sprint 1 — fundação (versão 1.30, 30/10/2026)

| Entrega | Situação | Onde | Roteiro |
| --- | --- | --- | --- |
| Espelho TUSS que não esvazia a busca e guarda a vigência por código | implementado | `integrations/tuss.py`, `catalogs/migrations/0010` | `check_tuss_vigencia` |
| Três chaves: plano (`tiss` em `plans.py`), clínica (`Tenant.tiss_liberado`) e instalação (`tiss.Configuracao`) | implementado | `tenancy/plans.py`, `tenancy/context.py`, `ops/superadmin.py` | `check_tiss_liberacao` |
| Capacidades `TISS_VIEW/PREPARE/CLOSE/EXPORT/CONFIGURE`, sem `READ_CLINICAL` | implementado | `tenancy/permissions.py` | `check_tiss_liberacao` |
| Segundo fator de novo após 10 min sem uso, **só na área TISS** (A9, req. 83) | implementado | `tiss/views.py::TissView` | `check_tiss_liberacao` |
| Forma de cobrança por atendimento (particular / convênio + cobertura), até o check-in | implementado | `scheduling` (modelo, serviço, painel do modal), `finance/receivables.py::_price_for` | `check_forma_de_cobranca` |
| Prestador (PJ/PF, CNPJ alfanumérico), credenciamento por operadora, profissional (interno ou externo) | implementado | `tiss/models.py`, `tiss/forms.py`, `templates/tiss/` | `check_tiss_liberacao`, `check_tiss_versoes` |
| Sete pacotes XSD oficiais (3.04.00 a 4.03.00) com manifesto SHA-256, parser sem rede e sem DTD | implementado | `tiss/versoes.py`, `tiss/xsd/` | `check_tiss_versoes` |
| Anexo do pedido como caso negativo | validado por XSD (reprovado, como deve) | `tiss/exemplos/anexo_reprovado_4_01_00.xml` | `check_tiss_versoes` |
| Catálogo das operadoras ativas da ANS no cadastro de convênio | implementado | `catalogs.OperadoraAns`, `import_operadoras_ans`, tarefa semanal | `check_operadoras_ans` |

**Verificação:** bateria completa na imagem da 1.30, 142 roteiros, nenhuma
falha (30/10/2026). **Não publicada**: vai para produção junto da Sprint 2,
por decisão do responsável.

**O que ainda não existe:** guia, item, lote, XML gerado, hash TISS,
impressão, agenda de recurso (EEG/ENMG/PSG) e o vínculo guia ↔ recebível.
São as Sprints 2 a 4.

### Para ligar numa clínica (quando houver guia para emitir)

1. `python manage.py import_operadoras_ans` **no worker** (ou esperar a
   tarefa de segunda-feira, 05h).
2. Console → *Operação* → Faturamento TISS → digitar `LIGAR` e o motivo.
3. Console → *Organizações* → a clínica (Completo ou Personalizado) →
   *TISS* → motivo → *Liberar TISS*.
4. Na clínica, quem tem o papel de dono ou gestor: *Faturamento TISS* →
   prestador → credenciamento por operadora → profissionais.

Desligar: o mesmo cartão, um clique. Nada é apagado.

### Decisões tomadas nesta sprint

- **Chave da instalação fora do contexto de permissões.** Ler a linha da
  configuração em toda requisição custaria uma consulta a toda tela de
  `/app/`; ela é conferida nas telas e tarefas do TISS e no menu, só para
  quem tem a capacidade.
- **Forma de cobrança é ação do horário, não campo obrigatório ao marcar.**
  O formulário rápido de marcação é desenhado para não pedir forma de
  pagamento ao telefone (`scheduling/forms.py::QuickBookingForm`). Vazio é
  "não informado", e nele vale a regra antiga — só que agora
  determinística (a cobertura ativa da ficha primeiro).
- **`row_version` não muda na troca de forma de cobrança**, para não
  invalidar os lembretes já agendados.
- **Reconfirmação pelo segundo fator.** Quem não tem TOTP configurado é
  levado a configurar ao entrar na área TISS — é o comportamento da tela
  de reconfirmação existente, e o A9 recomenda o segundo fator.

## Sprint 2 — guias (30/10/2026, ainda na versão 1.30)

| Entrega | Situação | Onde | Roteiro |
| --- | --- | --- | --- |
| Guia de Consulta e de SP/SADT, com numeração da clínica sob trava | implementado | `tiss/models.py` (`Guia`, `ItemGuia`, `Sequencia`), `tiss/migrations/0002` | `check_tiss_guias` |
| Preenchimento a partir do que existe: convênio do horário, carteira, credenciamento único da operadora, médico do horário como executante/solicitante, tipo de consulta | implementado | `tiss/guias.py::criar_guia` | `check_tiss_guias` |
| **Vínculo com a cobrança do check-in** — nenhum recebível novo; um recebível em no máximo um item (serviço e banco); cancelar solta | implementado | `ItemGuia.recebivel`, `tiss_item_recebivel_uniq` | `check_tiss_guias` |
| Procedimentos com busca TUSS e **vigência na data do serviço**; preço do contrato com a origem; valor diferente só com motivo; fator e arredondamento uma vez | implementado | `tiss/guias.py` (`conferir_codigo`, `preco_contratado`, `gravar_item`) | `check_tiss_guias` |
| Pendências legíveis, por quem resolve (recepção, médico, gestor), e domínios conferidos contra o XSD da versão do credenciamento | implementado | `tiss/guias.py::pendencias`, `tiss/forms_guia.py` | `check_tiss_guias` |
| Fechar congela (snapshot); revisão substitui sem reescrever; cancelar com motivo | implementado | `guias.fechar`, `abrir_revisao`, `cancelar` | `check_tiss_guias` |
| Indicação clínica só pelo médico, com autoria; a tela da guia sem prontuário | implementado | `guias.registrar_indicacao`, `views_guia.IndicacaoView` | `check_tiss_guias` |
| Impressão nos modelos oficiais (Consulta p.469, SP/SADT p.520), numeração dos campos, continuação em folhas, tarja no rascunho | implementado | `tiss/impressao.py` | `check_tiss_guias` |
| Atalhos: ficha do paciente (Gerar guia, Guias), modal da agenda, atendimento (os dois tipos) | implementado | templates | `check_tiss_guias` |
| Matriz de campos por versão | documentado | `docs/tiss/CAMPOS.md` | — |

**Verificação:** bateria completa na imagem com a Sprint 2, 143 roteiros,
nenhuma falha (30/10/2026). Não publicada.

**Decisões desta sprint:**

- **Sem campo de CID**: nenhuma versão das duas guias o tem.
- **Item só do que foi realizado**: guia sem horário nasce sem item; a de
  Consulta de um horário **com check-in** nasce com a consulta cobrada.
- **Procedimentos solicitados (campos 24–28 do papel) = os realizados**:
  o NeuroDoc não guarda pedido de exame como lista estruturada para a
  guia, e a clínica que solicita e executa lista os mesmos; a quantidade
  autorizada fica em branco.
- **Exame sem cobrança no financeiro ainda**: a SP/SADT de um exame não
  cria recebível; a origem do recebível de exame é a reserva de recurso
  (Sprint 4).

## Sprint 3 — lotes e XML (30/10/2026, ainda na versão 1.30)

| Entrega | Situação | Onde | Roteiro |
| --- | --- | --- | --- |
| Mensagem `ENVIO_LOTE_GUIAS` de Consulta e SP/SADT nas **sete versões**, a partir do snapshot da guia fechada, com as diferenças medidas nos XSDs (nome do beneficiário e `nomeContratado` só na 3.x; regime, saúde ocupacional e cobertura especial só na 4.x; 8,2 até a 4.01.00) | **validado por XSD** (as 14 combinações) | `tiss/xml.py` | `check_tiss_lotes` |
| Hash do epílogo: MD5 do conteúdo em ISO-8859-1, sem o epílogo, minúsculas, arquivo sem indentação | implementado; **não confirmado por operadora** (o texto da ANS não decide três detalhes; ver o topo de `tiss/xml.py`) | `tiss/xml.py::hash_tiss` | `check_tiss_lotes` |
| Fila do que faturar, com filtros, ciclo do credenciamento e paginação | implementado | `tiss/views_lote.py::FilaView` | `check_tiss_lotes` |
| Plano antes de criar: credenciamento × tipo × versão, até 100 (ou o limite), as recusadas com o motivo; a seleção que mudou não cria nada | implementado | `tiss/lotes.py::planejar`, `criar_lotes` | `check_tiss_lotes` |
| Guia em no máximo um lote ativo (serviço e banco), lote de 1 a 100 (banco), numeração sob trava | implementado | `LoteGuia`, `tiss_lote_guia_ativa_uniq`, `tiss_lote_quantidade` | `check_tiss_lotes` (com duas conexões simultâneas) |
| Arquivo gerado no worker, relendo as três chaves e quem pediu; 0600; SHA-256; mesmos bytes ao repetir; retomada do lote parado | implementado | `tiss/lotes.py::gerar_arquivo`, `tiss/tasks.py` | `check_tiss_lotes`; ponta a ponta com o worker real em 30/10/2026 |
| Envio, protocolo, retorno, cancelamento e reapresentação registrados à mão; nada toca no financeiro | implementado | `tiss/lotes.py`, `templates/tiss/lote.html` | `check_tiss_lotes` |
| Guia em lote ativo não se cancela por fora | implementado | `tiss/guias.py::cancelar` | `check_tiss_lotes` |

**Verificação:** bateria completa com a Sprint 3, 144 roteiros, nenhuma
falha (30/10/2026); e um lote de ponta a ponta pelo RabbitMQ e o worker
real, pronto em ~1 s e válido no XSD. Não publicada.

**Classificação, como o prompt pede:** as sete versões estão
**implementadas e validadas por XSD** e **validadas por regras** (as
pendências da guia e as recusas do XML). **Nenhuma está aceita em
homologação de operadora**: isso depende de enviar um arquivo a um portal
real, com autorização e dado apropriado. Nenhuma está **liberada em
produção**.

**Decisões desta sprint:**

- **O ciclo da guia é o do último procedimento** (`Guia.data_referencia`,
  gravada no fechamento). A guia nunca é partida entre dois períodos; a
  fila avisa quando ela tem procedimento antes do período filtrado.
- **Guia fechada numa versão e credenciamento trocado depois** não entra
  em lote: precisa de revisão, para os campos serem conferidos de novo na
  versão nova. Guia fechada antes da Sprint 3 (sem os campos no snapshot)
  também; nenhuma existe em produção, porque a 1.30 não foi publicada.
- **A equipe da SP/SADT** (`equipeSadt`) só sai quando o executante tem CPF
  no cadastro; sem CPF, ela fica de fora (é opcional no XSD) e o executante
  segue identificado pelo contratado.
- **Lote enviado só é cancelado depois da recusa registrada.** Guia
  glosada num lote aceito em parte é **liberada** com o motivo
  (reapresentação), e o lote enviado fica como foi.
- **Outras despesas não são suportadas**: os totais saem só com
  procedimentos e total geral, que é o que o XSD exige.

## Sprint 4 — agendas de exame e fechamento (30/10/2026, ainda na versão 1.30)

| Entrega | Situação | Onde | Roteiro |
| --- | --- | --- | --- |
| Agendas por recurso (EEG, ENMG, PSG) como **entidades novas** — nenhum médico fictício, nenhuma vaga de médico consumida | implementado | app `agenda_exames` | `check_agenda_exames` |
| Janela semanal que atravessa a meia-noite; reserva como intervalo de instantes, nos dois dias da tela; teto de 24 h | implementado | `agenda_exames/services.py` | `check_agenda_exames` |
| Sobreposição no mesmo equipamento recusada pelo banco (exclusão por recurso), inclusive com duas conexões simultâneas | implementado | `agenda_exames_reserva_sem_sobreposicao` | `check_agenda_exames` |
| Encaixe com motivo, bloqueios, remarcação, confirmação, chegada, falta, cancelamento | implementado | `agenda_exames/services.py` | `check_agenda_exames` |
| **Terceira origem da cobrança**: o exame realizado cria **uma** cobrança (serviço e banco), pelo honorário do procedimento; sem honorário, nenhuma é inventada | implementado | `finance/receivables.py::create_receivable_for_exam`, `finance/0008` | `check_agenda_exames` |
| Lembrete do exame, 24 h antes, pela mesma entrega da consulta (um envio por endereço, versão velha calada) | implementado | `agenda_exames/lembretes.py`, `communications/services.py::deliver_exam_reminder`, `communications/0010` | `check_agenda_exames` |
| Guia SP/SADT do exame realizado, com a cobrança vinculada e as horas da PSG (21:00 → 07:00), até o lote válido no XSD | implementado | `tiss/guias.py::criar_guia_do_exame`, `tiss/0004` | `check_agenda_exames` |
| Manual da recepção e do gestor: dois artigos | publicado no manual | `base/help_content.py` (`faturamento-tiss`, `agenda-exames`) | `check_ajuda`, `check_seo` |
| Ativação, reversão, vigilância e o roteiro de homologação com a clínica-piloto | documentado | `docs/tiss/OPERACAO.md` | — |

**Verificação:** bateria completa com a Sprint 4, 145 roteiros, nenhuma
falha (30/10/2026). Não publicada.

**Decisões desta sprint:**

- **A agenda de exames vem no contrato do TISS, sem a chave da
  instalação.** Plano Completo ou Personalizado e clínica liberada dão
  `EXAMES_AGENDAR` (os quatro papéis) e `EXAMES_CONFIGURAR` (dono e
  gestor). Desligar o faturamento na instalação **não** esconde os exames
  marcados; recolher o TISS de uma clínica recolhe também a agenda.
- **A agenda de exames não pede o segundo fator a cada dez minutos**: o
  requisito 83 do A9 é da área de faturamento, e a agenda é da recepção o
  dia inteiro.
- **O executante não bloqueia a agenda médica.** Quem acompanha a
  polissonografia é técnico; o médico lauda depois. Reservar o médico por
  suposição tiraria consultas que ninguém pediu para tirar.
- **Um lembrete só, na véspera** — o preparo do exame é explicado ao
  marcar, e duas horas antes é tarde para ele.
- **A data de execução da PSG é a do início**, e a hora final a do fim (o
  XSD tem uma data só por procedimento).

## O que ainda não foi feito

- **Nenhuma operadora homologada.** O primeiro arquivo num portal real é o
  passo 3 do roteiro em `OPERACAO.md`; até lá, o hash do epílogo segue a
  leitura literal do manual, com três detalhes em aberto.
- **Outras despesas** (taxas, materiais, medicamentos) na SP/SADT.
- **Transmissão automática** a operadoras (webservice): fora do escopo do
  pedido; o envio é pelo portal, registrado à mão.
- **A 1.30 não foi publicada.**
