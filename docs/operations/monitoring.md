# Métricas operacionais e redação final

## Logs

`base.logging.RedactSensitiveDataFilter` (aplicado a todo handler de
console) substitui qualquer valor associado a uma chave sensível
(`password`, `token`, `secret`, `otp`, `authorization`, `pfx`, `code_hash`)
por `[REDACTED]` em `record.msg`/`record.args` antes de qualquer log sair —
testado desde S02 (M0) e revalidado aqui.

## Alertas (`ADMINS`/`AdminEmailHandler`, novo em S10)

`django.request` com nível `ERROR` (qualquer 5xx não tratado) dispara um
e-mail para os destinatários definidos em `ALERT_ADMIN_EMAILS`, usando o
mesmo backend nativo de e-mail já homologado em S08. Django só envia esses
e-mails com `DEBUG=False` (padrão de produção).

**Risco identificado e corrigido nesta sprint**: o filtro padrão do Django
para o corpo do e-mail de erro (`SafeExceptionReporterFilter`) só oculta
campos de POST cujo **nome** pareça sensível (`password`, `token`, ...) —
ele não tem como saber que `chief_complaint` ou `hpi` é texto clínico. Uma
falha 500 dentro de uma view de prontuário enviaria o corpo da requisição
inteiro (incluindo texto clínico) para a caixa de e-mail de operação. Criado
`base.logging.NoPostDataExceptionReporterFilter`, que suprime **todos** os
parâmetros de POST do relatório de erro (`DEFAULT_EXCEPTION_REPORTER_FILTER`
em `core/settings.py`) — um alerta precisa do traceback e do caminho da
requisição, nunca do corpo.

**Testado de ponta a ponta**: com `ALERT_ADMIN_EMAILS` configurado, uma
requisição POST sintética contendo um trecho de queixa clínica reconhecível
foi submetida a um erro simulado no logger `django.request`; o e-mail
gerado (capturado no backend `locmem`) chegou ao destinatário configurado
com o traceback, mas **sem** o trecho clínico em lugar nenhum do corpo —
confirmado por busca textual no e-mail renderizado real.

## Decisões de escopo

- Nenhum provedor de métricas/observabilidade externo (Sentry, Grafana
  Cloud, etc.) está contratado — não há P- numerado especificamente para
  isso, mas na prática depende da mesma decisão de operação que P-03
  (credenciais de serviços externos). O mecanismo de alerta por e-mail
  nativo do Django cobre o aceite mínimo ("alertas chegam ao destinatário
  definido") sem exigir um provedor terceiro; métricas de performance
  (RNF-01, H-23) permanecem para medição quando houver capacidade de
  produção real (P-02).
