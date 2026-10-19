# Comunicado às clínicas — novo suboperador (Cloudflare)

**Aprovado pela Dra. Karina Albuquerque Freua em 2026-10-19.** Cumpre a
cláusula 8.4 do contrato de adesão (inclusão de suboperador comunicada à
CONTRATANTE) e lembra os direitos das cláusulas 8.5 e 8.6. A cláusula
pede comunicação **prévia**; a Cloudflare foi ligada antes do aviso como
**medida urgente de proteção** da disponibilidade e do endereço do
servidor, e a advogada considerou a comunicação posterior juridicamente
justificada nessas condições. Por isso o texto diz que foi urgente e
mantém o mesmo direito de oposição e de rescisão sem multa que a clínica
teria com o aviso antecipado.

**Enviado em 2026-10-19** de `contato@neurodoc.app.br`, pelo SMTP da
instalação, um e-mail por clínica, ao responsável (papel *owner*) das
quatro clínicas de terceiros: Caldas, Rego e Urbano; Luca SB; Santos
Dias Medical Care; e Schalch Serviços Médicos. Cópia oculta para
`contato@neurodoc.app.br`, que guarda o registro. As duas clínicas do
próprio titular (Consultório Dr Fernando Freua e Consultório FK) não
receberam, por já conhecerem a mudança.

---

**Assunto:** NeuroDoc — inclusão da Cloudflare na infraestrutura (proteção do servidor)

Prezado(a) responsável pela clínica,

Comunicamos, nos termos da cláusula 8 do Contrato de Adesão ao NeuroDoc,
a inclusão de um novo suboperador na infraestrutura que hospeda o
sistema.

**O que mudou.** Desde 19 de outubro de 2026, todo acesso ao NeuroDoc
passa pela **Cloudflare**, empresa de segurança e rede, antes de chegar
ao servidor. O sistema, os seus dados e a forma de usar continuam
exatamente os mesmos; nada foi migrado nem copiado.

**Por que, e por que agora.** Foi uma medida urgente de proteção, adotada antes deste aviso para não deixar o servidor exposto enquanto ele era preparado. A Cloudflare protege o servidor contra ataques de
sobrecarga, que poderiam deixar o prontuário indisponível durante o
atendimento, e esconde o endereço do servidor na internet. Desde a
mesma data, o servidor só aceita conexões vindas dela.

**O que ela trata.** Para filtrar ataques, a Cloudflare processa o
tráfego entre o navegador e o servidor enquanto ele está em trânsito —
o que inclui o conteúdo das telas do sistema. Ela não armazena esse
conteúdo como parte do serviço. A conexão é criptografada nos dois
trechos (navegador → Cloudflare e Cloudflare → servidor), e o
certificado do servidor é conferido. A Cloudflare opera sob acordo de
tratamento de dados com cláusulas-padrão para transferência
internacional.

**Onde estão os dados.** Para total transparência: o servidor do
NeuroDoc está hospedado nos **Estados Unidos** (Leaseweb, em San Jose,
Califórnia), desde o início da operação, e a Cloudflare opera uma rede
global. A relação completa e atualizada dos suboperadores, com a
finalidade e a localização de cada um, está em:
<https://github.com/ffreua/neurodoc/blob/main/docs/governance/suboperadores.md>

**Seus direitos.** Se a clínica tiver oposição fundamentada a este
suboperador, responda a este e-mail. Buscaremos uma solução técnica
alternativa — inclusive voltar ao modo anterior, sem a Cloudflare — e,
não havendo alternativa razoável, a clínica pode rescindir o contrato
sem multa, com restituição proporcional do período pago e não
utilizado, conforme as cláusulas 8.5 e 8.6.

Nenhuma ação é necessária da sua parte para continuar usando o sistema.

Atenciosamente,

Dr. Fernando Freua
NeuroDoc — contato@neurodoc.app.br
