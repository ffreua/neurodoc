---
id: MD-2026-11-20-01
data: 2026-11-20
origem: sessao-unica
tipo: mudanca
sigiloso: nao
estado_aqui: feito e verificado no ambiente local
roteiro_aqui: checks/check_revisao_2026_11_20.py
no_outro: feito na mesma rodada — PD-M-2026-11-20-01
---

# Auditoria externa de 2026-11-20: o que procedeu e o que foi feito

Uma auditoria feita por IA, a pedido do titular, apontou dezessete pontos
nos dois sistemas. Cada um foi conferido no código antes de qualquer
mudança; o relatório (com o que procedeu, o que não procedeu e por quê) foi
aprovado pelo titular. Tudo abaixo vale igual nos dois sistemas, salvo onde
indicado.

## Segurança

1. **Segundo fator configurado por quem não tem o código.** A tela de
   configurar só exigia sessão iniciada e, para quem já tinha segundo
   fator, ligava um segundo aparelho, deixava a sessão verificada e com
   código recente e trocava os códigos de recuperação. Agora, para quem já
   tem segundo fator, a tela é uma **troca de celular** que só abre depois
   de confirmar o código atual (ou um código de recuperação) na sessão; ao
   confirmar, o aparelho antigo sai, os dispositivos confiáveis são
   revogados e a troca vai para a trilha (`accounts.mfa.confirmar_aparelho`).
   Até aqui a "troca" nunca trocou: o login continuava no aparelho antigo.
2. **`/admin/login/` só com a senha.** O endereço manda ao login do produto,
   que pede o código. Uma varredura no roteiro reprova qualquer
   `auth_login` novo fora dos quatro conhecidos — escolhida no lugar de
   deslogar sessões sem código em `/app/`, que derrubaria dezenas de
   roteiros sem proteger nada a mais.
3. **Download do acervo e do mailing**: só quem pediu, com o código recente,
   e todo download de exportação na trilha. A lista do acervo mostra só o
   que a pessoa pediu.
4. **Convite pago aceito com outro e-mail**: recusado, sem gastar o convite.
5. **Restauração**: a imagem de infraestrutura que o manifesto do backup
   indica precisa ser do repositório que o `.env` declara (achado ao
   conferir o item da guarda; a imagem do banco subia com as senhas
   montadas).

## Dinheiro, dados e disponibilidade

6. **Pagamento apagado depois de estorno solto** deixava o recebido
   negativo: recusado quando a conta da cobrança ficaria abaixo de zero.
7. **Reticências (…) no TISS** derrubavam a geração do lote (`TypeError`):
   a troca de caracteres vem antes, no texto inteiro.
8. **Campanha de clínica suspensa ou encerrada** seguia enviando: a fatia
   pausa, e o disparo é recusado.
9. **PDF do paciente em branco** no `/d/<token>/`: `SAMEORIGIN` só na rota
   do arquivo.
10. **Corrida ao finalizar**: as telas que gravam itens do atendimento e o
    descarte travam a linha do atendimento, numa transação com a escrita.
11. **Trilha** sem nome de medicamento, de exame, rótulo de hipótese nem
    escore de escala; o admin não mostra os metadados (os eventos antigos
    não se limpam: a trilha é imutável).
12. **Corpo de requisição** acima de 40 MB recusado na entrada ASGI, antes
    de o Django gravá-lo no `/tmp` (o `buffering` do Traefik foi recusado:
    ele retém a resposta e quebraria o SSE). Prévia de PDF com o lado maior
    preso a 1024 px.

## Melhorias

13. **Quem abriu o prontuário** (só no NeuroDoc, adoção do PD-M02 do
    ProntDoc): ficha, atendimento, resumos, linha do tempo e gráfico na
    trilha, e a lista na ficha para o responsável.
14. Um pool Redis por processo no chat da equipe.
15. Avisos do Asaas do ProntDoc reconhecidos e guardados sem o conteúdo.

## O que não procedeu, e o que fica como está

- O "vazamento" de conexões Redis não existe (a biblioteca fecha); era só
  ineficiência (item 14).
- Os webhooks do Asaas não se misturam: cada sistema casa pedido só pelos
  ids que a própria Asaas gera (item 15 é minimização).
- **Médico ver o financeiro e a lista de pacientes da própria clínica é
  decisão do titular** (2026-11-20): fica como está.
- O motivo do descarte de atendimento continua na trilha: o atendimento é
  apagado, e a trilha é o único registro de por que saiu.

## Verificação

`checks/check_revisao_2026_11_20.py`, com uma seção por item, mais a
bateria vizinha (MFA, dispositivo confiável, exportação, Dashboard,
pagamentos, TISS, campanhas, prontuário, texto livre, estruturado,
imutabilidade, contratação, isolamento, idioma, CSP).
