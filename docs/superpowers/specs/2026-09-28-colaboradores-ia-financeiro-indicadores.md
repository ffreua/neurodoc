# Colaboradores, IA, contatos, indicadores e financeiro

## Requisitos observados

- O convite de colaborador deve mostrar URL HTTPS absoluta, permitir cópia manual e ser enviado automaticamente ao e-mail informado.
- A conta criada pelo convite deve pedir senha e confirmação idênticas e receber e-mail de verificação.
- O reenvio da verificação não pode cair em HTTP 405.
- Convites distintos e ainda válidos não podem ser confundidos com convite consumido ou expirado.
- O responsável da clínica deve poder enviar redefinição de senha e resetar MFA de um colaborador. O reset de MFA exige código MFA do responsável, auditoria, aviso por e-mail e encerramento das sessões do alvo.
- Tarefas de IA devem avisar sucesso ou falha e atualizar a tela de acompanhamento enquanto estão em execução.
- A leitura de laudo laboratorial deve tolerar modelos mais lentos, extrair dados sem diagnosticar e sempre exigir revisão médica.
- Se o laudo terminar depois da finalização, a revisão aceita deve entrar como adendo, preservando a imutabilidade do atendimento finalizado.
- Contatos do paciente devem ser editáveis na ficha, com trilha de auditoria e renovação da confirmação dos canais alterados.
- A tabela “Localização” deve ser removida dos indicadores.
- Pré-cadastros não contam como carteira ativa, distribuição etária ou consumo de pacientes do plano.
- A cobrança de consulta agendada nasce no check-in e usa primeira consulta, seguimento ou retorno para resolver o honorário. Texto livre e estruturado continuam faturáveis; adendo não gera cobrança.
- Atendimento posteriormente aberto para o agendamento deve ser associado à cobrança já criada, sem duplicá-la.

## Evidência de produção em 28/09/2026

- Um convite de colaborador foi consumido e o usuário permaneceu sem `email_verified_at`; o fluxo de aceite não chamava o serviço de verificação.
- A rota `verify-email/<token>` precedia `verify-email/resend`, capturando `resend` como token e retornando 405 no POST.
- O job de hemograma falhou com `Model call exceeded 90s`.
- Quatro eventos `clinical.encounter_finalized` foram processados; quatro auditorias `finance.receivable_pricing_missing` foram gravadas e nenhum recebível foi criado.
- O atendimento recente que reproduziu o problema possui exatamente um agendamento correspondente, em check-in, do tipo primeira consulta, mas `Encounter.appointment` estava vazio.
- A clínica possui 3 pacientes completos ativos e 3 pré-cadastros ativos.

