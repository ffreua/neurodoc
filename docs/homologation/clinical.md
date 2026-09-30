# Homologação — Prontuário e exame neurológico (S05)

Evidência via `python manage.py shell` (services/models diretamente) e
`django.test.Client` (views reais). Dados sintéticos apenas.

## H-06 — Atendimento e exame

- [x] Todos os blocos clínicos solicitados existem com campo e origem
  claros: queixa, HMA, antecedentes pessoais/familiares, consanguinidade
  (estado + detalhes), conduta — no model `Encounter` — e um catálogo
  completo por domínio para cognição, força (por segmento/lado), tônus,
  sensibilidade superficial/profunda, reflexos miotáticos/cutâneos,
  coordenação axial/apendicular, marcha e os 12 nervos cranianos
  individualmente (`clinical/examination.py`, `clinical/cranial_nerves.py`).
- [x] **Item não avaliado nunca vira normal implicitamente**: um encontro novo
  não tem nenhum `ExaminationFinding`; cada item só existe quando
  explicitamente registrado, com estado `not_assessed/not_informed/normal/
  altered` distinto.
- [x] Item lateralizado (ex.: força do cotovelo) exige lado; item não
  lateralizado (ex.: memória) rejeita lado explícito — testado nas duas
  direções.
- [x] Alternativas incompatíveis não coexistem sem resolução: grau de força
  fracionário (3.5) é rejeitado — apenas inteiros 0–5; resposta plantar
  "alterada" exige qualificador `flexor/extensor/indifferent` (resposta
  indiferente nunca é tratada como Babinski).
- [x] Nervos cranianos mantêm identidade individual: VII e XII registrados
  como achados distintos, cada um com seu próprio lado/estado — não existe
  um campo único para "nervos cranianos".
- [x] Retorno copia **somente** conduta e hipóteses do último atendimento
  finalizado do mesmo médico/tenant (nunca exame físico realizado, nunca gera
  pedido/receita automática) — confirmado registrando achados de exame no
  primeiro atendimento e verificando que o segundo atendimento não os herda.
- [x] Autosave com conflito de versão responde 409 (testado via
  `POST /app/clinical/<id>/autosave/` com `row_version` desatualizado);
  primeiro autosave promove `draft` → `in_progress` automaticamente.
- [x] **Exame neurológico em texto livre** complementa a árvore no
  atendimento estruturado: grava pelo mesmo autosave parcial, reaparece na
  tela e no resumo, entra no contexto da IA/exportação e participa do hash
  de integridade. Evidência: `checks/check_exame_neurologico_texto.py`.

## H-07 — Finalização e retificação

- [x] Finalização exige queixa/HMA **ou** justificativa, e conduta **ou**
  justificativa — um atendimento vazio não finaliza; um atendimento com
  histórico e conduta finaliza com sucesso, gravando `content_hash`,
  `finalized_at` e `finalized_by`.
- [x] Registro finalizado é imutável (`is_editable() == False`); adendo
  (`ClinicalAmendment`) registra motivo, autor e data **sem alterar** o texto
  original — confirmado comparando o HPI antes/depois do adendo.
- [x] Carry-forward com revisão pendente **bloqueia a finalização** do
  atendimento de destino; aceitar a revisão libera a finalização
  imediatamente.

## Decisões de escopo

- `ComplementaryExam` (exames complementares) foi **deliberadamente adiado**
  para S06, pois seu campo `attachment` só faz sentido quando o model
  `Attachment` existir; criá-lo antes disso seria um FK para um model
  inexistente ou um campo enganosamente vazio.
- Concessão clínica por paciente (`PatientAccessGrant`) ainda não existe no
  sistema; o isolamento desta sprint é por tenant + papel médico
  (`_doctor_membership`), documentado como limitação até esse model ser
  criado.
- A UI de exame é um formulário genérico (domínio + item + lado + estado),
  não um widget dedicado por item — o catálogo Python já impõe a
  granularidade mínima exigida; a apresentação visual fica para S14.
