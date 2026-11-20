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

## Segunda leitura: o relatório completo da auditoria

O titular trouxe depois o relatório inteiro (24 achados por sistema). Os
17 da primeira leitura já estavam corrigidos acima. Do resto, conferido no
código já corrigido, procedeu e foi feito nos dois sistemas (salvo onde
indicado):

**Antes de publicar**

16. **Restauração:** a imagem do proxy do Docker também vem do `.env`, e
    não do manifesto do backup (o serviço monta o socket do Docker).
17. **Endereço da IA da instalação:** conferido contra o catálogo e a lista
    liberada ao gravar no console (com o código de novo quando muda) e a
    cada uso; o cliente HTTP do provedor não segue redirecionamento.
18. **Sanitizador do chat de IA:** lista de esquemas permitidos (http,
    https, mailto, relativo) no lugar da lista negra, que deixava passar
    `java\tscript:`.
19. **Sessões que nunca passaram pelo código:** a migração
    `accounts/0006_encerrar_sessoes_sem_codigo` apaga, uma vez, as sessões
    de quem tem segundo fator e não traz a marca do código; confirmar um
    aparelho encerra as outras sessões da pessoa.
20. **Chat da equipe:** a conferência solta a conexão do banco, e para com
    a clínica encerrada ou a pessoa desativada (a suspensa continua, porque
    só lê); o mesmo no stream da IA.

**Dados e operação**

21. **Avisos do Asaas:** o de assinatura também confere a referência, e o
    aviso que não é de pedido desta instalação é guardado sem o conteúdo.
22. **Trilha:** sem os valores de peso e altura e sem o nome do modelo de
    pedido (que revela a suspeita clínica).
23. **Quem abriu o prontuário:** a busca de pacientes por CID entra no
    registro, e a janela de 30 minutos passou a ser por objeto (o segundo
    atendimento do mesmo paciente também fica registrado).
24. **Logs:** o relatório de CSP tira o token de cadastro, convite,
    verificação de e-mail, descadastro e redefinição; o filtro de log tira
    `Bearer`/`Basic`, senha em URL e o mesmo nos tracebacks.
25. **Sessão de assinatura** revogada no logout, ao abrir outra e com o
    vínculo revogado. O certificado **não** é revogado com o vínculo: volta
    a valer se o médico for recontratado.
26. **Portal do paciente:** chave de sessão nova ao identificar, paciente
    arquivado deixa de valer na hora, limite na busca pública de
    medicamentos, teto de medicações conferido no servidor e cota própria
    dos envios do portal dentro da cota da clínica.
27. **Travas:** pagamento e ajuste recusados em cobrança repassada ou
    arquivada; renovação com trava na clínica (dois cliques, um checkout);
    indicação clínica da guia TISS sob a trava do rascunho, e a impressão da
    guia fechada lendo os campos do snapshot.

**Endurecimento**

28. PDF conferido pela estrutura (`pypdf`): danificado, sem páginas, com
    senha ou com mais de 500 páginas é recusado. Os 178 PDFs do NeuroDoc em
    produção passaram na validação nova antes de ela entrar. `documents/ocr.py`
    (sem chamador desde a 1.18) foi apagado.
29. O código do convite do pedido entra na rotação da chave-mestra.
30. `SEGUNDO_FATOR_OBRIGATORIO_DESDE` vazio volta ao padrão (exigido), em vez
    de desligar.
31. IA: o marcador de nascimento no relatório, doença rara no plural e com
    acento na trava, o pedido do médico avaliado pela trava e a confirmação
    de risco só depois de um bloqueio de fato.
32. Limites no reenvio de verificação de e-mail e no reenvio de documento
    (que passa a aceitar só documento assinado — o de papel mandava um link
    que dava 404); convite de equipe recusado em clínica que não está ativa
    (o convite continua valendo para quando ela voltar).
33. `/verificar/` com `no-store`, e consulta com código inexistente ou acima
    do limite no log, sem o código.
34. **Só no ProntDoc:** "Monitorização neurofisiológica intraoperatória"
    virou "Monitorização intraoperatória".
35. Mailing com médico que não está mais na clínica é recusado, em vez de
    exportar a clínica inteira.

**Não procedeu, ou fica como está (decisão do titular onde indicado)**

- Exigir autoria no reenvio de documento: o PRD autoriza dono e secretária.
- Restringir a edição do atendimento aberto ao médico dele (ND-015): fica
  como está, por decisão do titular — quebraria substituição, preceptoria e
  carteira compartilhada.
- A tela de bloqueio dos 180 dias continua mostrando a data e o médico
  (decisão do titular).
- Gatilho no banco contra apagar atendimento finalizado e hash do
  prontuário cobrindo os itens filhos: procedem, mas mudam prova jurídica e
  quebram roteiros; ficam para a rodada da trilha com hash encadeado.
- Nome completo na tela do portal: intencional (protege contra trocar a
  ficha entre abas). Limite do portal só por IP: escolha documentada.
  `delete_all_financial_history` sem trava: já trava.
- Prefixar `neurodoc:` na referência do Asaas: o ProntDoc já ignora o que
  não tem `prontdoc:`, e inverter o critério aqui perderia avisos de
  parcelas de pedidos antigos.

Seções 17 a 29 do mesmo roteiro cobrem a segunda leitura.
