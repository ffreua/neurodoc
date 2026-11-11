# Contrato 2.0 — o que o texto diz e o sistema ainda não faz

A redação 2.0 do contrato de adesão (Dra. Karina Albuquerque Freua,
OAB/SP nº 450.476, 2026-11-10) foi conferida, afirmação por afirmação,
contra a instalação em produção no dia em que chegou. A maior parte bate:
planos e limites (`tenancy/plans.py`), IA padrão na NVIDIA com reserva na
OpenRouter servindo DeepSeek, o canal "Fale com a NeuroDoc", o contato
`contato@neurodoc.app.br`, MFA, trilha, adendo no finalizado, assinatura
PAdES ICP-Brasil, nenhum cookie de terceiros.

O que segue **não bate**. Cada item diz o que o texto afirma, o que o
sistema faz, e de quem é o próximo passo — do sistema (mudar o produto
para cumprir o texto) ou da advogada (ajustar o texto à realidade). O
texto não foi alterado aqui: correção de redação passa por ela.

| # | O texto diz | O sistema faz | Próximo passo |
| --- | --- | --- | --- |
| 1 | **Anexo II, III e Aviso §5**: suboperadores são Integrator, NVIDIA, OpenRouter/DeepSeek, SMSDEV e Hostinger | A **Cloudflare** processa todo o tráfego entre navegador e servidor, em claro na borda, desde 2026-10-19 — e está em [`suboperadores.md`](suboperadores.md) | Advogada: incluir a Cloudflare no Anexo II, no III e no Aviso |
| 2 | **Anexo II/III, Aviso §5**: hospedagem "Integrator Host do Brasil", "sujeito à localização física" | A VPS é da **Leaseweb USA, em San Jose (EUA)**, contratada pela Integrator; há transferência internacional desde o primeiro dia | Advogada: dizer o país, como `suboperadores.md` já diz |
| 3 | **Anexo II**: "DeepSeek — modelo via OpenRouter" como destinatário | A OpenRouter repassa a provedores de infraestrutura escolhidos a cada pedido, e a instalação **exige** retenção zero, sem treino e fora da China (`ai/providers::ROTEAMENTO_OPENROUTER_DA_INSTALACAO`) | Advogada: pode citar a restrição, que protege mais do que o texto diz |
| 4 | **Quadro, 11.1, Anexo I 6.1, IV, V 5.1, Aviso §8**: backups externos **semanais**, retidos **até 30 dias**, em SSD; cópia em backup eliminada no ciclo de 30 dias | Backup **diário** na VPS (9 dias lá) e cópia **diária** para o SSD, que guarda **60** (`scripts/puxar_backups.ps1`, `$Manter = 60`) | Decisão do controlador: reduzir o SSD a 30 (`-Manter 30`) **ou** a advogada escrever "diários" e o prazo real. O "30 dias" é promessa de eliminação; guardar 60 a contraria |
| 5 | **Quadro, 14.3, IV §2 e §3.2**: exportação ordinária em **CSV, MD e JSON**, com os **PDFs originais** dos anexos, inclusive os assinados ICP-Brasil | Exportação do acervo só em **Markdown e JSON**, sem arquivo anexo (`reporting/apps.py`) | Sistema: acrescentar CSV ao acervo e um pacote com os PDFs originais, vinculados a paciente e data |
| 6 | **Quadro, 14.2, IV §3.1**: depois do encerramento, **90 dias** de consulta e exportação, sem criar registro, com lembretes | Clínica encerrada (`CLOSED`) não abre nada — a tela manda escrever ao contato. Só a suspensa (`SUSPENDED`) lê sem escrever, e nela a exportação (um POST) é recusada | Sistema: um estado "em encerramento" — leitura e exportação por 90 dias, depois fechada — e os lembretes |
| 7 | **5.2**: "a implementação atual informada restringe novos cadastros de pacientes" | A suspensão por inadimplência **congela toda escrita** (prontuário, agenda, tudo), não só o cadastro | Escolha: a advogada descreve o congelamento real (o próprio 5.2 já o permite: "novos registros"), ou o sistema ganha um modo mais leve |
| 8 | **2.4 e 19**: alteração material com novo aceite quando necessário | Os 15 aceites existentes (1.0, 1.1, 1.2) continuam nas versões que assinaram; não há tela que peça o aceite da 2.0 a quem já é cliente | Decisão: se as clínicas atuais devem aceitar a 2.0, construir o pedido de novo aceite |

Os itens 1 e 2 são os que mais pesam: um anexo de suboperadores que
omite quem recebe dado sensível, ou que localiza no Brasil um servidor
que está nos EUA, é o argumento que a cláusula 10 existe para evitar.
