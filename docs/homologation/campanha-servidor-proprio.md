# Comunicação em massa: em qualquer plano, só pelo servidor da clínica

**Versão:** 1.9 "o e-mail da clínica" · **Data:** 2026-10-08 ·
**Roteiro:** `checks/check_campanha_servidor_proprio.py`

## O pedido

Campanha por e-mail deixa de ser exclusividade do plano Completo e passa a
existir em **qualquer plano**, com uma condição: a clínica ter cadastrado
o **próprio servidor de e-mail** (SMTP). E a página de vendas tem de dizer,
com todas as letras, que o Gratuito não tem IA nem SMS, mas que a
comunicação com o paciente acontece por e-mail, pelo remetente do NeuroDoc
ou pelo servidor que a clínica cadastrar.

## O que havia antes, e o furo que ele tinha

A campanha nunca foi barrada por plano no servidor: o Completo a
anunciava, e o código não conferia o plano. A guarda do disparo pedia só
que o e-mail da clínica estivesse **ativo e com remetente**.

Ativo com remetente não quer dizer servidor próprio. `_connection_for`
só abre conexão separada quando há host. Sem host, a mensagem sai **no
nome da clínica, pelo SMTP da instalação**. O comentário da guarda dizia
"comunicação em massa por remetente da instalação queimaria a reputação
de um domínio que não é o da clínica", e era exatamente isso que ela
deixava passar.

## A decisão

**"Servidor próprio" tem uma definição só**:
`communications/email.py::clinic_own_server`, que exige a configuração
ativa **e com host**. Remetente sem host não conta.

**O plano não entra na conta**, nem para dar nem para tirar. O motivo da
exigência não é comercial. A reputação do servidor da instalação é
dividida por todas as clínicas. Uma campanha que caia em filtro de spam
levaria junto a confirmação de conta, a recuperação de senha e a entrega
de documento de quem não tem nada com ela.

**A área abre e explica, em vez de sumir.** Um 404 esconderia a
funcionalidade de quem pode tê-la com um cadastro. A lista mostra o
aviso, com o botão para cadastrar o servidor, e o "Nova campanha" some.

**Quatro portas, e as quatro no servidor**, não só no template:

| Porta | Sem servidor próprio |
| --- | --- |
| Tela (criar: GET e POST; testar) | redireciona com a mensagem; nada é criado nem enviado |
| `marketing.guard` (disparar, retomar) | `CampaignBlocked` com a mesma mensagem da tela |
| Cada fatia (`_enviar_fatia`) | a campanha **pausa**; destinatários continuam pendentes |
| `send_email(require_own_server=True)` | `OwnServerRequired`, sem recuar para a instalação |

A terceira porta existe porque entre o disparo e a última fatia podem
passar horas, e a clínica pode desligar o servidor no meio. Seguir
mandaria o resto da lista pela instalação. A campanha **pausa**, e não
cancela: religado o servidor, "retomar" continua de onde parou, sem
reenviar a quem já recebeu. O destinatário da vez fica **pendente**, e não
"falhou", porque ele não chegou a sair.

**Pausar nunca depende de servidor.** Parar é a direção segura.

**O que não muda:** o e-mail do dia a dia (confirmação e aviso de horário,
entrega de documento, verificação de conta, recuperação de senha) segue
a cadeia de sempre (médico → clínica → instalação) e sai sem servidor
próprio. Campanhas antigas continuam legíveis.

## Na vitrine

- Cada cartão de plano ganhou a linha **E-mail: NeuroDoc ou o seu**, ao
  lado de IA clínica e SMS. Ela responde a quem lê "SMS não incluído" no
  Gratuito e se pergunta como o paciente fica sabendo das coisas.
- O Gratuito (e por "Tudo do Gratuito", todos) anuncia os avisos por
  e-mail e as campanhas com o servidor da clínica. O Completo deixou de
  vender a campanha como exclusividade dele.
- O bloco "Sobre a IA clínica, o SMS e o e-mail" diz que no Gratuito a
  comunicação sai pelo e-mail do NeuroDoc ou pelo servidor da clínica, e
  que a campanha está em todos os planos, sempre pelo servidor da
  clínica.

## Evidência

`check_campanha_servidor_proprio.py`, oito seções: a definição (ativo sem
host, host só com espaços, host desligado); os quatro planos; as portas
da tela, inclusive por POST direto; pausar sem servidor; o servidor que
some no meio do envio; `require_own_server`; o e-mail transacional
intacto nos dois casos sem servidor; e a vitrine lida do catálogo.

**O roteiro foi conferido contra o defeito.** Rodado com a regra antiga
simulada ("remetente ativo basta"), ele reprova em **19 verificações**.
Um roteiro que passasse nas duas versões não estaria testando a regra.

`check_g9.py` foi ajustado. Ele montava a clínica "ativa sem host" e
esperava que a campanha saísse, que é justamente o caso que a regra agora
recusa. Passou a configurar host, a trocar a conexão por caixa em memória
e a cobrar a recusa do remetente sem servidor (seção 12b). Ele também
deixava de restaurar o `smtp_host` da clínica de demonstração, e passou a
restaurar.

**Bateria:** 97 roteiros, nenhuma falha (2026-10-08, local, imagem
reconstruída).

## Para quem já usa

Uma clínica que tenha campanha em rascunho e remetente sem servidor vê o
aviso no lugar do botão de disparar. Nada é apagado. Basta cadastrar o
servidor em **Integrações → SMS e e-mail**.
