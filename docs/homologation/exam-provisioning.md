# O roteiro de exame vem com a clínica

Reportado em uso real: cadastrar um paciente, abrir o atendimento, clicar
na aba **Exame neurológico** e ler

> Nenhum roteiro de exame publicado nesta organização. Instale o roteiro
> padrão com `manage.py install_exam_template` ou use o registro avulso
> abaixo.

Evidências: `checks/check_roteiro.py`.

## O defeito não era o aviso

O aviso estava tecnicamente correto — a organização realmente não tinha
roteiro. O defeito é que **nenhum caminho de criação de organização
instalava um**.

`exams/management/commands/install_exam_template.py` existe desde o
começo e funciona. Mas era um comando, e um comando só roda quando alguém
lembra de rodá-lo. Os dois lugares onde uma clínica nasce não o
chamavam:

- `tenancy/services.py::accept_platform_invitation` — o caminho de
  produção, o convite que cria a organização e o dono;
- `base/management/commands/seed_demo.py` — a demonstração.

Ou seja: **toda clínica que entrasse em produção cairia nessa tela**, e
a primeira pessoa a ver o exame neurológico seria também a primeira a
descobrir que ele não estava lá. O produto é um prontuário de
neurologia; o exame estruturado é o motivo de ele existir.

## Onde a correção foi parar

`exams/provisioning.py`, `ensure_default_template(tenant_id)`, chamada
nos dois pontos acima. Três decisões dentro dela:

**Idempotente.** Reinstalar versiona o roteiro, e isso está certo para
uma atualização deliberada — o atendimento antigo continua lendo a versão
com que foi preenchido. Mas provisionar não é atualizar: uma clínica que
já tem roteiro não ganha versão nova só porque a semeadura rodou de novo.
A função devolve `None` nesse caso, e `check_roteiro` seção 4 confere.

**Não derruba quem está entrando.** A falha aqui seria de empacotamento —
o YAML vem no repositório. E uma clínica sem roteiro ainda é utilizável:
registra o achado em texto avulso. Abortar o cadastro inteiro trocaria um
problema pequeno por um intransponível, então a exceção é registrada no
log e o cadastro segue.

**Ponto de salvamento próprio.** A carga roda dentro do seu próprio
`transaction.atomic()`, para que uma falha no meio desapareça sem
contaminar a transação de quem chamou — `accept_platform_invitation` é
atômica, e uma exceção de banco engolida lá dentro envenenaria o cadastro
inteiro.

As **14 escalas funcionais** vêm junto: `install_template` chama
`load_scales`. A clínica nova nasce com 387 nós de roteiro e as escalas
pontuadas.

## O aviso que sobrou

O estado continua possível — alguém pode despublicar o roteiro — então a
mensagem ficou, reescrita. A anterior pedia ao médico que rodasse
`manage.py install_exam_template`: um comando de terminal, num servidor a
que ele não tem acesso, com uma sintaxe que não significa nada para quem
está atendendo. A nova diz o que fazer agora (registrar pelo campo
avulso, que preserva o achado no prontuário) e a quem recorrer.

## Chegou até o manual público

As capturas `exame-roteiro.png` e `exame-escalas.png` da central de ajuda
foram tiradas contra o banco de demonstração recém-limpo — que, pelo
mesmo defeito, estava sem roteiro. O manual público mostrava o aviso de
erro como se fosse a tela normal do produto. Ambas refeitas.

É o segundo achado da mesma natureza nesta rodada: um defeito que só uma
**instalação limpa** revela. O primeiro foram os dois defeitos do
`seed_demo` (regra de agenda sem `starts_on`, catálogo real rebaixado
pelo de amostra). Banco de trabalho acumulado esconde exatamente a
experiência de quem chega agora.

## O que foi verificado

`checks/check_roteiro.py`, quatro seções, todas verdes:

| # | Pergunta | Resultado |
| --- | --- | --- |
| 1 | As clínicas existentes têm roteiro publicado e padrão? | 2 de 2, 387 nós |
| 2 | A tela de atendimento pede comando de terminal? | Não |
| 3 | Clínica criada por convite nasce com roteiro? | 387 nós, 14 escalas |
| 4 | Provisionar de novo versiona à toa? | Não |

A seção 1 confere também o **tamanho** do roteiro, não só a existência:
uma carga interrompida no meio deixa um punhado de nós, e um roteiro
truncado é pior do que roteiro nenhum — parece completo.
