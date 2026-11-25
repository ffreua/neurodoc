# 2026-11-25 — Teleatendimento: link do vídeo, e-mail ao paciente e termo público (Leva B)

| Campo | Valor |
| --- | --- |
| Lado | NeuroDoc, na mesma rodada que o ProntDoc |
| Tipo | mudança (pedido do titular), feita nos dois |
| Origem | pedido do titular — segunda leva do conjunto cuja primeira foi a MD/PD-M 2026-11-25-01 |

O horário marcado como teleatendimento (`Appointment.teleatendimento`, NeuroDoc
1.43) ganha o **link do vídeo** e o envio dele ao paciente.

**1. O link.** Campo `Appointment.teleatendimento_link` (migração
`scheduling/0013_teleatendimento_link`, aditiva, `db_default=''`), gravado por
`scheduling.services.set_teleatendimento_link`: exige a marca de teleatendimento
e o horário ainda vivo (concluído, cancelado e falta recusados), não mexe em
`row_version`, e **o link não vai para a trilha** — pode carregar token de
acesso à sala. Qualquer plataforma (Meet, Teams, Zoom, cockpit de hospital); o
nome dela sai do domínio do link. Na revisão antes de publicar, o serviço
passou a **conferir o link** (`_conferir_link_de_video`): só `http`/`https` e
até 500 caracteres — ele grava sem `full_clean`, e o `URLField` sozinho não
conferia nada (um `javascript:` era gravado, e um link enorme estourava a
coluna com erro 500 na tela).

**2. "Enviar link".** Rota `scheduling:teleatendimento-link` (só POST; `acao`
salvar ou enviar), campo e botões no modal do horário, com o JS preenchendo o
link salvo. O envio é `communications.services.enviar_link_teleconsulta` pela
task `enviar_link_teleconsulta_task` **no worker** (o `app` não tem o segredo de
SMTP): **só e-mail**, só ao endereço do paciente, só pelo botão — o aviso comum
da agenda não muda. O corpo traz data, profissional, plataforma, link,
orientações (local iluminado e reservado, preferir computador, conferir a
conexão) e o endereço do termo. A secretária pode enviar.

**3. O termo público.** `/termo-teleconsulta/`, sem login, com a redação
autorizada pela Dra. Karina: aceite pela participação, sem assinatura por
paciente, sem autorização de gravação. Genérico (sem dado de clínica), porque o
NeuroDoc é público. Decisões em `docs/governance/teleconsulta-termo.md`.

**Verificação.** Roteiro novo `check_teleconsulta_link` nos dois (termo público,
exigência da marca, envio com link e termo, plataforma pelo domínio, trilha sem
o link, recusas, view e task, outra clínica em 404), passando duas vezes
seguidas e sem sobras; vizinhos `check_teleatendimento`, `check_idioma`,
`check_csp`, `check_provedor_e_sms`, `check_seo`, `check_fuso` e
`check_rotulos`. No NeuroDoc local (e-mail ligado), envio ponta a ponta pela
view da secretária até o Mailpit. Ao rodar, o próprio roteiro tinha três
defeitos, corrigidos nos dois: horários do mesmo médico sobrepostos, limpeza
sem apagar entrega e tentativa (`PROTECT`) e a caixa de e-mail suposta em
memória.

**Roteiro antigo corrigido junto.** `check_aviso_de_horario` criava
horários em "agora ± N dias" na agenda de um médico real do banco e reprovava
quando rodava na hora de um horário existente (às 11h, contra o da
demonstração das 11h00). Agora procura um intervalo livre (`_horario_livre`);
provado com as três janelas ocupadas de propósito.

**Bateria inteira nos dois** (195 roteiros). Além do `check_copia_nuvem`,
que falha desde 2026-11-18 em toda bateria rodada dentro da imagem (lê o
`.env.example`, que o `.dockerignore` exclui de propósito), apareceram três
roteiros antigos que reprovavam pelo ambiente, não pelo produto, e foram
corrigidos nos dois:

- `check_leitura_retirada`: o "PDF" de teste não tinha página e é recusado
  desde a auditoria de 2026-11-20 (o envio abre o PDF); passava só onde
  sobrava um exame de mesmo nome. Agora gera um PDF de uma página e só
  aceita o exame criado neste envio.
- `check_links_de_mensagem`: supunha o backend de e-mail do worker; com o
  e-mail desligado no `.env` local (ProntDoc) a fila nunca era chamada.
  Agora fixa o backend do worker na seção.
- `check_planos`: reprovou no NeuroDoc local por sobras de pré-cadastro de
  rodadas anteriores no banco de demonstração; com o banco limpo, passa —
  inclusive a recusa do pré-cadastro no limite, mexido na Leva A.

**Diferença entre os lados.** Nenhuma de comportamento: as âncoras eram
iguais e o patch entrou igual nos dois, conferido arquivo a arquivo.

**VERSION:** NeuroDoc **1.58**, ProntDoc **1.12.0**.
