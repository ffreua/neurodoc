# 2026-11-25 — WhatsApp automático pela Twilio da própria clínica (BYO)

| Campo | Valor |
| --- | --- |
| Lado | NeuroDoc, na mesma rodada que o ProntDoc |
| Tipo | mudança (pedido do titular), feita nos dois |
| Origem | pedido do titular: integração opcional de WhatsApp Business via Twilio, com a conta e o número de cada clínica, e tutorial de autoatendimento |

**Decisão revista.** A recusa de 2026-11-08 (`docs/homologation/whatsapp-da-recepcao.md`)
era o sistema ter de ser Tech Provider na Meta. No modelo BYO a **clínica** é
cliente direta da Twilio (Self Sign-up) e o sistema só guarda as credenciais
dela; a documentação oficial (fontes em `docs/governance/whatsapp-twilio.md`)
sustenta o caminho. O botão `wa.me` da recepção continua igual.

**O que entrou** (detalhe e porquês no documento de governança):

- Canal `DeliveryChannel.WHATSAPP` no mesmo `Delivery`/`DeliveryAttempt`, posse
  `PENDING→SENDING`, idempotência e fila — sem infraestrutura nova, sem SDK
  (`httpx`, já dependência).
- `WhatsAppTwilio` (uma por clínica: Account SID, **Auth Token cifrado**,
  número, Messaging Service opcional, interruptor, resultado da verificação,
  token aleatório da URL de status) e `WhatsAppModelo` (ContentSid por ocasião).
- Só **modelo aprovado pela Meta**, em cinco ocasiões (lembrete — também o de
  exame —, marcado, remarcado, cancelado, documento), com variáveis fixas e
  **nada clínico** (nem médico, nem tipo, nem paciente; o documento vai pelo
  link `/d/` de sempre). Nunca texto livre.
- **Aceite próprio de WhatsApp** no contato (`whatsapp_opt_in_at`,
  `_evidence`, `_opt_out_at`), com procedência obrigatória; "aceita SMS" não
  vale. No contato com aceite, o WhatsApp **substitui o SMS** da ocasião; o
  e-mail continua. Contato encerrado perde o aceite.
- Verificação e envio de teste **no worker**; a tela recarrega sozinha. Seis
  estados derivados (não configurado, pendente, inválido, validado,
  operacional, desativado): preencher nunca é "operacional".
- Aviso de status público (`/whatsapp/status/<token>/`), autenticado pela
  assinatura da Twilio sobre a URL de `PUBLIC_BASE_URL`, `AccountSid` e
  `MessageSid` conferidos contra a clínica, `UPDATE` que só avança; consulta
  periódica (15 e 60 min) para o aviso perdido.
- Chave da instalação no console (`InstallationSettings.whatsapp_twilio_liberado`),
  **nascendo recolhida**: liberar pede segundo fator, palavra e motivo;
  recolher é um clique.
- Auth Token na rotação da chave-mestra; as funções de rede do WhatsApp na
  varredura que proíbe envio de dentro de view.
- Tutorial na central de ajuda (`/ajuda/whatsapp-twilio/`), em
  `base/ajuda_whatsapp.py`, **o mesmo arquivo nos dois produtos**.

**Verificação.** Roteiro novo `check_whatsapp_twilio` (103 conferências)
contra uma **Twilio simulada**, com a assinatura conferida pelo vetor da
documentação e por vetores do SDK oficial (twilio 9.13.0); vizinhos de
mensageria, contato, ajuda, CSP, idioma, rótulos, isolamento e agenda de
exames; bateria inteira. Dois roteiros antigos ajustados por mudança de
assinatura interna, não de comportamento: `check_despachante` (a função
substituta passou a aceitar `whatsapp=`). **Não homologado com a Twilio
real** (o Sandbox não aceita modelos próprios).

**Diferença entre os lados.** Só o nome do produto nos textos e a dependência
da migração `communications.0014` (`tenancy` 0024 no NeuroDoc, 0025 no
ProntDoc). A alteração de cada arquivo foi comparada entre os dois.

**Jurídico:** a Dra. Karina avaliou em 2026-11-25 e **nada muda** (contrato,
Anexo II e Aviso). **Pendência** antes de liberar no console: homologação
com uma conta Twilio real.

**Revisão antes de publicar:** SMS de reserva quando o WhatsApp não sai na hora
(sem ele, o paciente com aceite ficava sem aviso numa recusa da Twilio); a
verificação que sempre termina (última tentativa de rede e espera máxima da
tela); a tarefa de teste sem credenciais; a caixa dos status normalizada.

**VERSION:** NeuroDoc **1.59**, ProntDoc **1.13.0**.
