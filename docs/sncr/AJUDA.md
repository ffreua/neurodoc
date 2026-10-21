# SNCR — texto da central de ajuda (para publicar na ativação)

**Ainda não publicado, de propósito.** A central de ajuda é pública, e a
página de vendas e o manual não anunciam o que o cliente não pode usar
(regra de `base/content.py`). Este texto entra em `base/help_content.py`
no passo 11 de [ATIVACAO.md](ATIVACAO.md), quando a receita eletrônica
estiver ligada em produção. Ao publicar: conferir os passos contra a tela
real, gerar as capturas (`ops/capturar_ajuda.py`) e rodar `check_ajuda` e
`check_seo` (o sitemap conta os artigos).

---

## Receita eletrônica com numeração do SNCR (Anvisa)

*Para: médico. Resumo: Receita de Controle Especial e Receita Sujeita à
Retenção eletrônicas, no modelo da Anvisa, com o seu número.*

1. **Peça o seu bloco de números.** No menu, **Numeração SNCR** → **Pedir
   bloco com o Gov.br**. Você entra com o seu Gov.br e a Anvisa entrega
   1.000 números, que são **seus**: valem em todas as clínicas em que
   você atende, e só você os usa. São até 3 pedidos por mês de cada tipo
   (RCE e RET), e um bloco não pode ser devolvido — peça quando o painel
   mostrar que os números estão acabando.
2. **Se o pedido ficar "Resultado incerto"**, não peça de novo: a Anvisa
   pode ter gerado o bloco sem a resposta chegar. Entre em
   **sncr.anvisa.gov.br** com o Gov.br, veja se há bloco gerado nessa data
   e registre no painel — **Nenhum bloco foi gerado**, ou o primeiro e o
   último número que o portal mostra.
3. **Na receita**, escolha **Controle especial — eletrônica** (lista C1 e
   C5, e os adendos) ou **Sujeita à retenção — eletrônica**
   (antimicrobiano, GLP-1). Preencha até **3 medicamentos**: nome da
   substância, concentração, forma, quantidade em algarismos (o extenso
   entra sozinho) e posologia.
4. **Confira a classificação.** O NeuroDoc procura cada medicamento na
   lista oficial da Portaria 344 e mostra a lista de cada um. Medicamento
   que pede **Notificação de Receita** (B1, como o clonazepam) não sai
   aqui — use o talonário. Se o medicamento depende de dose para entrar
   no adendo, ou não foi encontrado, marque a confirmação: a decisão é sua
   e fica registrada.
5. **Assine.** Cada medicamento sai **na sua folha**, com o **seu número
   SNCR** — o paciente pode levar cada folha a uma farmácia. Todas as
   folhas vão numa assinatura digital só. A receita sai no modelo da
   Anvisa, sem o cabeçalho da clínica.
6. **Sem número livre, ou sem certificado agora?** Use **Refazer como
   receita impressa**: a prescrição é copiada para a receita impressa da
   clínica, para assinar e carimbar, e nenhum número é gasto.
7. **A receita eletrônica emitida não é corrigida** (o número dela já foi
   usado): emita uma nova.

**Pergunta frequente.** *"A farmácia vai conferir o quê?"* — o número na
plataforma da Anvisa (sncr.anvisa.gov.br), onde ela registra o uso, e a
assinatura digital no validar.iti.gov.br. O QR de cada folha abre a página
de verificação do NeuroDoc, com o documento e o médico.
