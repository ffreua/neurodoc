# Boas-vindas e clínica sem médico

Versão 1.25. Roteiro: `checks/check_boas_vindas.py`.

## O problema

A clínica nasce só com o **responsável** (`tenancy/services.py::accept_platform_invitation`),
e o responsável não abre prontuário: a matriz de `tenancy/permissions.py` só
entrega leitura e escrita clínica, emissão de documento e IA clínica ao papel
**médico**. Quem acabava de cadastrar a clínica entrava, procurava "Novo
atendimento" e não achava, sem nada na tela dizendo que faltava cadastrar um
médico.

## O que entrou

| Peça | Onde | O que faz |
| --- | --- | --- |
| E-mail de boas-vindas | `tenancy/boas_vindas.py`, `templates/tenancy/email/boas_vindas.txt` | Sai no cadastro, depois da via do contrato. Traz o aviso do perfil médico, o resumo dos primeiros passos e o link para o artigo completo |
| Aviso permanente | `base/context_processors.py` (`nd_sem_medico`), `templates/base.html` | Faixa no alto de toda tela de `/app/` enquanto a clínica não tiver vínculo **ativo** com o papel médico |
| Primeiros passos | `base/help_content.py`, artigo `primeiros-passos` | Primeiro artigo do manual público, com os perfis, a IA e o SMS nativos, o e-mail e a comunicação em massa |
| Página inicial | `templates/onboarding/landing.html` | Botão e cartão "Comece aqui" na seção do manual |

## Decisões

- **O aviso aparece para todos os vínculos**, não só para o responsável: a
  secretária que procura o prontuário precisa saber por quê. O link para
  Equipe e papéis sai só para quem tem `MANAGE_ORGANIZATION`; os demais leem
  "peça ao responsável".
- **Sem botão de fechar**, como o aviso de clínica suspensa: ele descreve um
  estado e some sozinho quando o estado muda.
- **Conta o papel, não o CRM validado** (`tenancy/limits.py::has_doctor`). O
  que falta a quem não tem médico é cadastrá-lo; a validação do CRM é o
  passo seguinte, explicado no artigo e no e-mail.
- **IA e SMS no e-mail e no artigo seguem o plano**, lidos de
  `tenancy/plans.py` (`has_clinical_ai`, `has_sms`). O Gratuito não lê que tem
  SMS, e o artigo cita os planos pelo nome sem escrevê-los à mão.
- **Os links do e-mail saem de `PUBLIC_BASE_URL`** (`base.seo.absoluta`),
  nunca do `Host:` da requisição.
- **O e-mail sai pelo caminho de sempre** (`send_email` → backend do worker,
  depois do commit) e a falha **não desfaz** o cadastro. Não há coluna de
  envio: diferente da via do contrato, que é prova, este e-mail é orientação,
  e o mesmo conteúdo está no manual e na tela. A falha vai para o log.
- **Os cartões do manual na página inicial passaram a ser escolhidos por
  slug** (`base/views.py::MANUAL_DESTAQUES`). Eram `ARTICLES[1:5]`, e o artigo
  novo no topo da lista os trocaria em silêncio.
- `check_ajuda` seção 7 passou a olhar o primeiro artigo **com captura**: o
  "Primeiros passos" não tem nenhuma, de propósito, porque cada passo aponta
  o artigo que tem a tela.

## Homologação

| # | Pergunta | Resultado |
| --- | --- | --- |
| 1 | O cadastro manda as boas-vindas, com o aviso do médico e o link absoluto? | Gratuito e Completo |
| 2 | O texto de IA e SMS é o do plano? | Gratuito sem os dois, Completo com os dois |
| 3 | `Host:` forjado muda o link? | Não |
| 4 | O e-mail quebrado derruba o cadastro? | Não |
| 5 | O aviso aparece para o responsável (com link) e para a secretária (sem link)? | Sim |
| 6 | Médico suspenso conta? | Não |
| 7 | O aviso some quando o responsável vira médico, e a outra clínica continua com o dela? | Sim |
| 8 | O artigo abre, é o primeiro, entra no sitemap e só aponta artigos que existem? | Sim |
| 9 | A página inicial e a central levam a ele, sem perder os quatro cartões? | Sim |
