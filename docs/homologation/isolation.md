# Homologação — Revisão de isolamento (S14)

Revisão consolidada de H-03 sobre as superfícies que mudaram desde a
última revisão dedicada (M2, S10): admin, exportações, chat, tasks,
download e cache. Não repete a evidência já registrada; referencia onde
cada ponto já foi comprovado e fecha os pontos que ainda não tinham
verificação própria.

## Admin

- [x] `/admin/` continua atrás de `base.middleware.TechnicalPanelMFAMiddleware`
  (superusuário + MFA verificada), verificado originalmente em M0 (S02) e
  não alterado desde então.
- [x] **Escopo do admin é deliberadamente global** (não filtrado por
  tenant) — isso é intencional: o admin técnico é operado por pessoal de
  operação/engenharia, não por usuários de clínica, e a autorização já
  exige superusuário + MFA antes de qualquer acesso. Isso é diferente de
  um bug de isolamento; é a natureza de um painel operacional interno.

## Exportações (reporting)

- [x] Já testado em S13 (`docs/homologation/reports-capture.md`): uma
  exportação da Clínica A responde 404 para um usuário autenticado na
  Clínica B, mesmo com o UUID exato do registro (`scope_to_tenant` em
  `reporting/views.py`).

## Chat (ai)

- [x] Já testado em S12 (`docs/homologation/chat.md`): sessões filtradas
  por `tenant_id` **e** `owner_user_id` (não apenas tenant — nem um outro
  médico do mesmo tenant vê a sessão de chat de outro médico); revogação
  de membership interrompe uma conexão SSE já aberta, não só bloqueia uma
  requisição nova.

## Tasks (Celery)

- [x] Todo handler assíncrono (outbox, IA, financeiro, relatórios) recebe
  apenas um ID no payload (nunca dados clínicos no broker, por desenho
  desde S08) e busca a linha real no banco antes de agir — a mesma linha
  já carrega seu próprio `tenant_id`, então um evento nunca pode "vazar"
  para o tenant errado mesmo que o worker processe eventos de tenants
  diferentes em sequência. `ai.services.run_job` reautoriza a membership
  a partir do zero dentro da task (não confia no estado do momento em que
  o job foi enfileirado) — testado em S11.
- [x] O dispatcher genérico (`events/dispatcher.py`) foi revisado
  novamente nesta sprint: múltiplos consumidores independentes do mesmo
  evento (financeiro + IA em `clinical.encounter_finalized`, desde a
  correção de bug de S11) cada um só enxerga e processa os dados que sua
  própria consulta ao banco retorna, escopada pelo `tenant_id` do evento.

## Download

- [x] Anexos (`documents:download`) e documentos médicos assinados: já
  testado em S06/S07 — 404 para tenant errado, `Cache-Control: private,
  no-store` em toda resposta de arquivo.
- [x] Exportação de relatório (`reporting:export-download`): mesmo padrão,
  `private, no-store`, mais a expiração de 24h já testada em S13.

## Cache

- [x] `django.core.cache` (Redis DB 1) só é usado por
  `accounts/throttling.py` (limite de tentativas de login, chave por
  e-mail normalizado + IP) — confirmado por busca em todo o código-fonte
  (`from django.core.cache`/`cache.set`/`cache.get`/`cache_page`).
  Nenhum dado clínico ou administrativo de tenant passa pelo cache
  compartilhado; não há risco de um valor cacheado vazar entre tenants
  porque nenhuma chave sensível ao tenant é cacheada.
- [ ] **O cache do navegador não foi examinado aqui, e tinha um furo.**
  Acrescentado em 2026-10-05, depois de o defeito aparecer em uso real:
  esta seção procurou `cache.set`/`cache_page` no código-fonte e concluiu
  corretamente sobre o cache do Django. O cache que mostrou a organização
  errada não é nosso e não aparece nessa busca — é o do navegador, que
  guardava `/app/org/clinica/logotipo.img` por cinco minutos porque a
  resposta pedia, e servia a imagem da clínica anterior depois da troca
  de organização (a URL não muda, e o cookie também não: `switch_tenant`
  escreve na mesma sessão). Corrigido em
  `docs/homologation/logotipo-por-organizacao.md`, com a regra geral e o
  roteiro `check_logotipo.py`, que varre o código atrás de `max-age` em
  endereço que não distingue o que serve.

## Achado real desta sprint (fora do escopo original de H-03, mas relacionado)

O gap de navegação após login (ausência de tela de escolha de organização,
ver `docs/homologation/design-adherence.md`) não era um problema de
**vazamento** entre tenants — era o oposto, um bloqueio total de acesso —
mas foi encontrado justamente ao testar a jornada completa de
autorização com um navegador real pela primeira vez nesta sessão. Reforça
a recomendação já registrada: uma passagem de navegador real por sprint,
além dos testes de view isolados, pega uma classe de problema que testes
de view sozinhos não pegam.

## Decisões de escopo

- Esta é uma revisão consolidada, não uma nova bateria completa de testes
  de isolamento do zero — cada ponto aponta para onde a evidência original
  já foi coletada. Nenhuma regressão foi encontrada nas superfícies
  revisadas.
