# Intercâmbio NeuroDoc ⇄ ProntDoc

**Lado NeuroDoc** desta pasta (repositório público). O ProntDoc nasceu do NeuroDoc 1.46 (`02c7e483`) e os dois continuam com a
maior parte do código em comum. Um defeito achado num costuma existir no
outro. Esta pasta é o canal: **cada achado de um sistema fica registrado
aqui, e o outro sistema avalia se também o tem** — e registra a avaliação.
Assim todo achado crítico, erro de caminho ou de execução é auditável nos
dois, sem que um copie o outro às cegas.

## Onde fica cada lado

| Repositório | Pasta | Visibilidade |
| --- | --- | --- |
| ProntDoc (`ffreua/prontdoc`) | `docs/intercambio/` | **privado** |
| NeuroDoc (`ffreua/neurodoc`) | `docs/intercambio/` | **público** |

Os dois têm a **mesma estrutura**:

```
docs/intercambio/
├── README.md          este protocolo
├── INDICE.md          tabela de todos os achados e avaliações
├── MODELO.md          o formulário de um achado
├── achados/           o que ESTE sistema encontrou (e corrigiu ou não)
├── mudancas/          TODA mudança deste sistema que não é defeito: decisão
│                      comercial, funcionalidade, comportamento, texto, operação
└── avaliacoes/        o que este sistema concluiu sobre achados e mudanças DO OUTRO
```

**Toda mudança vai para cá** (decisão do responsável, 2026-11-15): defeito
em `achados/`, o resto em `mudancas/` (`MD-` / `PD-M-`), com o commit e o
roteiro. Mudança não obriga o outro a copiar — decisão comercial, por
exemplo, é de cada produto —, mas o outro precisa saber que ela existe e
registrar o que concluiu.

## Como um lado lê o outro (só leitura)

**Do ProntDoc, ler o NeuroDoc** — o remoto `upstream` já existe, com envio
desligado:

```bash
git fetch upstream main
git ls-tree -r --name-only upstream/main docs/intercambio/
git show upstream/main:docs/intercambio/INDICE.md
```

**Do NeuroDoc, ler o ProntDoc** — num clone de trabalho do NeuroDoc (nunca na
VPS de produção), um remoto só de leitura. Pelo HTTPS, com a credencial do
`gh` (`gh auth status` mostra a conta; o ProntDoc é privado, e só ela lê):

```bash
git remote add prontdoc https://github.com/ffreua/prontdoc.git
git remote set-url --push prontdoc DISABLED--leitura-apenas
git fetch prontdoc
git show prontdoc/main:docs/intercambio/INDICE.md
git diff <commit-antes> <commit-depois> -- <arquivo>   # a correção do outro, para ler
```

Sem clone, pela API do GitHub — útil para conferir um arquivo do outro lado
na hora da avaliação:

```bash
gh api repos/ffreua/prontdoc/contents/docs/intercambio/INDICE.md -H "Accept: application/vnd.github.raw"
gh api repos/ffreua/neurodoc/contents/docs/intercambio/INDICE.md -H "Accept: application/vnd.github.raw"
gh api "repos/ffreua/prontdoc/commits?path=docs/intercambio&per_page=5" --jq '.[].commit.message'
```

O ProntDoc é privado: só quem tem acesso a ele lê o lado de cá.

## Como um lado escreve no outro

O remoto de leitura nunca empurra. Para **gravar** no intercâmbio do outro
(a conversa), usa-se o clone de trabalho **dele** — `~/projects/prontdoc` e
`~/projects/neurodoc` nesta máquina —, com três regras:

1. **Só `docs/intercambio/`.** Código do outro nunca é alterado daqui: a
   correção lá é feita pela avaliação de lá, adaptada.
2. **O que se grava no outro é o que ele precisa saber:** o registro novo
   deste lado como avaliação `pendente` em `avaliacoes/` dele, e a coluna "No
   NeuroDoc"/"No ProntDoc" do `INDICE.md` dele (mais o `no_outro` do registro)
   com a conclusão a que este lado chegou, apontando para o arquivo deste lado.
3. **Commit próprio, só de documentação**, com a mensagem começando por
   "Intercambio" — e só no ramo que o outro publica (`main` aqui; no ProntDoc,
   `main` e `prontdoc/derivacao`, que andam juntos). Nunca na VPS.

## O ciclo de um achado

1. **Achou e corrigiu aqui** → cria `achados/AAAA-MM-DD-assunto.md` pelo
   `MODELO.md`, com o commit da correção e o roteiro que a cobre, e uma linha
   no `INDICE.md`. No campo **"No outro sistema"**, diz o que já sabe: o código
   equivalente existe lá? Em que arquivo e linha (lido do outro repositório)?
2. **O outro lado avalia** → cria `avaliacoes/AAAA-MM-DD-assunto.md` com a
   conclusão: `afetado`, `nao_afetado` (e por quê — muitas vezes é uma das
   diferenças abaixo) ou `ja_corrigido`. Se afetado, corrige **no próprio
   código, adaptado**, com roteiro próprio, e registra o commit.
3. O `INDICE.md` dos dois lados aponta o estado final.

Nada é aplicado por cópia de patch: o arquivo pode ter divergido, e a
correção certa num pode ser errada no outro.

## Segurança — a regra por causa da visibilidade

O NeuroDoc é **público**. Um achado que descreve como explorar uma falha
(vazamento entre clínicas, contorno de permissão, injeção, credencial) **não
entra na pasta pública** antes de corrigido e publicado nos dois sistemas.
Até lá ele fica só no lado privado (ProntDoc), marcado `sigiloso: sim`, e a
pasta do NeuroDoc recebe, depois da correção, só o registro de que existiu e
foi corrigido. Defeito funcional (tela, caminho, perda de texto, erro 500)
pode ir direto.

Nunca: dado de paciente, de clínica, segredo, chave, IP de servidor, trecho
de log com conteúdo clínico.

## Diferenças que a avaliação respeita

| Assunto | NeuroDoc | ProntDoc |
| --- | --- | --- |
| Prontuário | estruturado (abas, roteiro de exame neurológico, escalas) **e** texto livre | só texto livre, três tipos (`Encounter.estrutura`) |
| Modelos de pedido | 7 categorias (com líquor, neurofisiologia…) | 3 (laboratório, imagem, outros) |
| Identificadores | `neurodoc_*`, `NEURODOC_*` | `prontdoc_*`, `PRONTDOC_*`; `ops/guarda.py` recusa os do outro |
| Contrato | 2.x (MIT) | 1.x (proprietário) — numerações independentes |
| Licença | MIT, repositório público | proprietária, repositório privado |
| Versão | 1.47+ | 1.2.0+ — o número de um não diz nada do outro |
| Tema | azul | verde |

Um achado em tela do estruturado é `nao_afetado` no ProntDoc; um achado da
tela única de texto livre pode afetar o texto livre do NeuroDoc.
