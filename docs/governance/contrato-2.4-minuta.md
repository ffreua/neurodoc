# Contrato 2.4 — minuta do que muda (para a Dra. Karina conferir)

> **Aprovada pela Dra. Karina em 2026-11-18** e publicada como
> `tenancy/contrato/contrato-2.4.md` (`tenancy/contract.py::VERSAO = '2.4'`).
> A cópia no R2 foi ligada em produção no mesmo dia, por decisão do
> titular. O comunicado às clínicas está em
> `docs/governance/comunicado-2026-11-r2.md`. O que segue é o registro da
> minuta como foi enviada.

**Motivo:** decisão do Dr. Fernando (2026-11-18). Os backups diários são
cifrados na VPS e copiados para um SSD externo. Em 2026-11-18 viu-se que o
SSD tinha ficado 40 dias desconectado sem ninguém perceber; e o servidor e
os backups que ele guarda dependem de um fornecedor só: perder a conta
levaria produção e backups juntos. A correção é uma **segunda cópia
externa, automática, em outra empresa**: o armazenamento de objetos da
Cloudflare (R2), com **bloqueio contra exclusão** — nem quem invadir o
servidor consegue apagar as cópias antes do prazo.

O que a cópia é, para a redação:

- **cifrada antes de sair do servidor**, com a mesma chave pública dos
  backups de hoje; a chave que decifra fica com a PRONTDOC, **fora** do
  servidor e fora da Cloudflare. A Cloudflare guarda arquivos que não
  consegue ler;
- **diária**, logo depois do backup;
- **até 60 dias** de retenção (regra de ciclo de vida do balde), igual ao
  SSD; os primeiros 30 dias de cada cópia com bloqueio contra exclusão;
- na **América do Norte** (o R2 não oferece região na América do Sul); o
  servidor de produção já está nos EUA, então não há país novo;
- a Cloudflare **já é suboperadora** (proxy da borda), mas descrita "sem
  armazenamento como serviço": a guarda é finalidade nova e pede linha
  própria no Anexo II;
- o SSD continua, como terceira cópia, desconectada.

## O que muda no texto

| Onde | 2.3 | 2.4 (proposta) |
| --- | --- | --- |
| Quadro-resumo, BACKUPS | "diários, cifrados localmente, mantidos por até 30 dias no servidor de produção e copiados diariamente para mídia SSD externa, onde são mantidos por até 60 dias." | "diários, cifrados localmente, mantidos por até 30 dias no servidor de produção e copiados diariamente para armazenamento em nuvem da Cloudflare (R2), com bloqueio contra exclusão antecipada, e para mídia SSD externa, mantidos por até 60 dias em cada cópia externa." |
| 11.1 | "… retenção por até 30 dias no servidor de produção e cópia externa diária em unidade de estado sólido (SSD), com retenção por até 60 dias, conforme Anexos I e V. A natureza do SSD não representa, isoladamente, garantia de imutabilidade, redundância geográfica ou recuperação." | "… retenção por até 30 dias no servidor de produção e duas cópias externas diárias — em armazenamento de objetos da Cloudflare (R2), com bloqueio contra exclusão antecipada, e em unidade de estado sólido (SSD) —, cada uma com retenção por até 60 dias, conforme Anexos I e V. As cópias são cifradas antes de deixar o servidor, e a chave capaz de decifrá-las não é armazenada no servidor nem entregue à Cloudflare. Nenhuma das cópias representa, isoladamente, garantia de recuperação." |
| Anexo I, 6.1 | "… backups diários cifrados localmente, retidos por até 30 dias no servidor de produção e por até 60 dias em cópia externa em mídia SSD." | "… backups diários cifrados localmente, retidos por até 30 dias no servidor de produção e por até 60 dias em cada cópia externa (armazenamento em nuvem da Cloudflare, com bloqueio contra exclusão, e mídia SSD)." |
| Anexo II | — | **linha nova:** "Cloudflare — armazenamento de cópias de backup (R2) \| Guarda das cópias diárias de backup fora do fornecedor do servidor, para recuperação em caso de perda do ambiente \| Cópias cifradas de todo o ambiente, inclusive dados de saúde, sem acesso ao conteúdo: a chave de decifração fica com a PRONTDOC, fora do servidor e da Cloudflare \| América do Norte; transferência internacional (Anexo III); retenção de até 60 dias, com bloqueio contra exclusão antecipada" |
| Anexo II, data do inventário | 13/11/2026 | data da aprovação |
| Anexo III, 1.1 | (sem menção) | acrescentar: "As cópias diárias de backup, cifradas antes da saída do servidor, são guardadas no armazenamento de objetos da Cloudflare (R2), na América do Norte." |
| Anexo IV, linha "Backups cifrados" | "Diários; cifragem local; até 30 dias no servidor de produção e até 60 dias em SSD externo" | "Diários; cifragem local; até 30 dias no servidor de produção e até 60 dias em cada cópia externa (nuvem Cloudflare R2 e SSD)" |
| Anexo V, 5.1 | "… copiados diariamente para disco externo de estado sólido (SSD), onde são conservados por até 60 dias. Essa estratégia não comprova isolamento físico, cópia imutável ou recuperação bem-sucedida; …" | "… copiados diariamente para armazenamento em nuvem da Cloudflare (R2), com bloqueio contra exclusão antecipada, e para disco externo de estado sólido (SSD), conservados por até 60 dias em cada cópia. Essa estratégia não comprova recuperação bem-sucedida; …" |
| Aviso de Privacidade, hospedagem | (sem menção) | acrescentar, depois da Cloudflare: "As cópias de segurança, cifradas antes de sair do servidor, também são guardadas no armazenamento em nuvem da Cloudflare, na América do Norte, sem que ela tenha a chave para lê-las." |
| Aviso de Privacidade, segurança | "… backups diários cifrados localmente, mantidos por até 30 dias no servidor e por até 60 dias em cópia externa em SSD." | "… backups diários cifrados localmente, mantidos por até 30 dias no servidor e por até 60 dias em cada cópia externa (nuvem e SSD)." |
| Título e datas | 2.3, 17/11/2026 | 2.4, data da aprovação |

O ciclo de expurgo de backup (Anexo IV 3.7 e cláusula 14.6, "até 60 dias")
**não muda**: a cópia na nuvem segue o mesmo prazo. Um ponto para a
senhora avaliar: o bloqueio contra exclusão impede apagar uma cópia antes
de 30 dias mesmo a pedido; isso já cabe no "ciclo ordinário de até 60
dias" da 3.7, mas talvez valha dizê-lo.

## Quem já aceitou a 2.3 (ou anterior)

A cláusula 10.1 dá autorização geral para suboperadores descritos no Anexo
II e manda comunicar **com antecedência razoável** as alterações materiais
que envolvem dados sensíveis. Ao mesmo tempo, a cláusula 2.4 diz que o
contrato aceito numa versão anterior "permanece regido por ela até que o
CONTRATANTE aceite expressamente versão nova", e que o silêncio não vale
como aceite. **Como as duas se combinam é a pergunta para a senhora**: se o
comunicado com antecedência basta para ligar a cópia também para quem está
na 2.3 (porque a 10.1 já autoriza suboperador descrito com transparência),
ou se a cópia de quem não aceitou a 2.4 precisa esperar o aceite (o que, na
prática, adiaria a proteção para todo o acervo, já que o backup é de
banco inteiro e não por clínica).

Proposta: publicar a 2.4 para os aceites novos e mandar às clínicas ativas
o comunicado abaixo, ligando a cópia **depois** do prazo que a senhora
indicar (o de 2026-10 com a Cloudflare, `comunicado-2026-10-cloudflare.md`,
é o precedente).

> **Assunto: os backups do NeuroDoc ganham uma cópia em nuvem**
>
> A partir de [data], os backups diários do NeuroDoc, que já são cifrados
> no servidor e copiados para um disco externo, passam a ter também uma
> cópia automática no armazenamento em nuvem da Cloudflare, empresa que
> já protege o acesso ao sistema. A cópia sai cifrada do servidor, e a
> Cloudflare não tem a chave para lê-la; ela fica na América do Norte, é
> guardada por até 60 dias e não pode ser apagada antes do prazo, nem por
> quem invadisse o servidor. O objetivo é que os seus dados possam ser
> recuperados mesmo se o servidor inteiro se perder. O contrato de adesão
> 2.4 descreve a mudança: [link].

## O que muda no sistema quando a 2.4 for publicada

- `tenancy/contrato/contrato-2.4.md` e `VERSAO = '2.4'`, como nas anteriores;
- `check_contrato` cobrando a menção à cópia em nuvem e os 60 dias;
- na VPS: `BACKUP_R2_*` no `.env` e o arquivo de credenciais
  (`docs/operations/copia-externa.md`, "Cópia no Cloudflare R2").
