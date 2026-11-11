# Contrato 2.0 — o texto conferido contra o sistema

A redação 2.0 do contrato de adesão (Dra. Karina Albuquerque Freua,
OAB/SP nº 450.476) foi conferida, afirmação por afirmação, contra a
instalação em produção em 2026-11-10, antes de ser publicada. A maior parte
batia: planos e limites (`tenancy/plans.py`), IA padrão na NVIDIA com
reserva na OpenRouter servindo DeepSeek, o canal "Fale com a NeuroDoc", o
contato `contato@neurodoc.app.br`, MFA, trilha, adendo no finalizado,
assinatura PAdES ICP-Brasil, nenhum cookie de terceiros.

Oito pontos não batiam. **O texto foi ajustado à realidade, com
autorização da Dra. Karina, no mesmo dia**, antes de qualquer aceite — e
por isso continua sendo a 2.0. Nenhum deles exigiu mudar o sistema.

| # | A minuta dizia | A realidade | Como o texto ficou |
| --- | --- | --- | --- |
| 1 | Suboperadores sem a Cloudflare | A Cloudflare processa todo o tráfego, inclusive o clínico, desde 2026-10-19 ([`suboperadores.md`](suboperadores.md)) | Linha própria no Anexo II; citada no Anexo III 1.1 e no Aviso §5 |
| 2 | Hospedagem "Integrator Host do Brasil" | Servidor da **Leaseweb USA, em San Jose (EUA)**, contratado pela Integrator; transferência internacional desde o primeiro dia | O país e a transferência no Anexo II, no III 1.1 e no Aviso §5 |
| 3 | Backup semanal, até 30 dias em SSD | Backup **diário**; **30 dias** no servidor (`BACKUP_RETENTION_DAYS`) e cópia diária no SSD, que guarda **60** (`scripts/puxar_backups.ps1`) | Quadro, 11.1, 14.6, Anexo I 6.1, Anexo IV, Anexo V 5.1 e Aviso §8 com os números reais |
| 4 | Exportação em CSV, MD, JSON e os PDFs originais | O acervo sai em **MD e JSON**, gerado pela clínica; os PDFs se baixam um a um na plataforma | Quadro, 14.3 e Anexo IV: MD e JSON, e os PDFs baixados individualmente ou fornecidos pela PRONTDOC a pedido |
| 5 | 90 dias de consulta e exportação depois do encerramento | A clínica encerrada não abre nada; a exportação é pedida ao contato, e o console pode reabrir só para leitura (suspensa) | 14.2, Anexo IV e Aviso §8: acesso desativado, exportação a pedido por 90 dias, consulta restabelecível a pedido |
| 6 | Na inadimplência, só novos cadastros de pacientes bloqueados | A suspensão congela **toda** escrita e mantém a leitura | 5.2 descreve o congelamento real |
| 7 | "DeepSeek" como destinatário | A OpenRouter repassa a provedor escolhido a cada pedido, e a instalação exige retenção zero, sem treino e fora da China (`ai/providers::ROTEAMENTO_OPENROUTER_DA_INSTALACAO`); a empresa DeepSeek não recebe o pedido | 9.2, Anexos II e III e Aviso §5 citam a restrição |
| 8 | Nada sobre quem já é cliente | Os aceites 1.0, 1.1 e 1.2 continuam nas versões que assinaram; não há tela de novo aceite | 2.4: a versão anterior vale até aceite expresso da nova, e o silêncio não é aceite |

`check_contrato` cobra os números e nomes reais no texto (Cloudflare,
Leaseweb, os 30 e os 60 dias) e a ausência das afirmações antigas (backup
semanal, CSV). Se o sistema mudar qualquer um desses pontos — um pacote de
exportação com os PDFs, a retenção do SSD, um provedor novo —, o contrato
muda junto, e aí é versão nova.
