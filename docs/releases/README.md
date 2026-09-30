# Registro de releases

A seção 18.6 do PRD exige que cada release publicada tenha, **antes** de
`NEURODOC_RELEASE_APPROVED=True`, um arquivo `docs/releases/<SHA>.md` com o
SHA, as evidências de homologação e o responsável que assinou.

A ordem importa. A flag no `.env` é uma trava declarativa: ela não executa
nem comprova homologação nenhuma, e `ops/deploy.py::preflight` só verifica
que alguém a ligou. O que responde "esta versão foi homologada por quem, com
base em quê?" é este diretório — e a pergunta é feita depois do incidente,
quando a flag já está ligada há semanas.

Copiar `TEMPLATE.md`, renomear para o SHA completo de 40 caracteres da
release, preencher, **commitar** e só então ligar a flag. Preflight recusa
repositório com mudança rastreada não commitada, então o registro entra na
mesma árvore que vai ao ar.

A versão de produto segue `docs/operations/versionamento.md`. Esta
consolidação permanece em 1.0; a próxima atualização funcional começa em
1.1. O SHA continua mudando em toda publicação, mesmo quando `VERSION` não
muda.
