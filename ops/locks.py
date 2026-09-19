"""Numeros de trava compartilhados entre o processo de backup e a aplicacao.

Moram aqui, e nao em `ops/backup.py` nem em `documents/retention.py`,
porque os dois lados precisam do **mesmo** numero e nenhum dos dois pode
importar o outro: `ops.backup` roda no host e arrasta `ops.deploy` (e
PyYAML junto); `documents.retention` roda dentro do Django. Um modulo sem
import nenhum e o unico lugar que os dois alcancam.

O erro que isso impede ja aconteceu: a aplicacao verificava um arquivo em
`/data/media/.backup_lock` que **nenhuma parte do sistema criava**, e o
backup travava uma sessao no PostgreSQL. Eram duas travas que nunca se
encontravam, e por isso a coleta de lixo e a compactacao do arquivo morto
podiam mexer nos arquivos durante a copia -- produzindo um backup cujo
banco aponta para arquivos que ja nao existem, descoberto so na
restauracao. Com um numero so, as duas operacoes disputam a mesma trava.
"""

#: Trava da copia de seguranca. Quem a segura esta copiando banco e
#: arquivos, e ninguem pode apagar, mover ou comprimir arquivo nenhum
#: enquanto isso.
BACKUP_LOCK = 72654002
