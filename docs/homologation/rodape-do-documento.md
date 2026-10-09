# A assinatura no rodapé da folha

**Versão:** 1.12 "o rodapé" · **Data:** 2026-10-08 ·
**Roteiro:** `checks/check_rodape_do_documento.py`

## O pedido

Cabeçalho no alto, corpo no meio e, **no rodapé**, a assinatura do médico
(com o QR de verificação) e, no receituário de controle especial, o quadro
de identificação do comprador e do fornecedor. Vale para todos os
documentos: receita simples, controle especial, relatório, pedido de
exame e encaminhamento. A folha inteira é usada, como no receituário em
papel.

Antes o rodapé vinha logo depois do corpo. Uma receita de uma linha
terminava com a assinatura no meio da folha e meia página em branco
abaixo dela.

## Como ficou

Os quatro tipos de documento passam por `documents/pdf/common.py::_one_copy`,
e a mudança é ali, num lugar só. O rodapé (linha, assinatura, QR e, quando
houver, o quadro da farmácia) virou um único bloco, `NoPeDaFolha`:

- **na medição**, ele ocupa todo o espaço que sobra na página;
- **no desenho**, põe o conteúdo encostado no fim desse espaço, que é o pé
  da folha;
- **se o corpo encheu a folha** e o rodapé não cabe no que sobrou, ele vai
  **inteiro** para a página seguinte e desce ao pé dela. Nunca se parte:
  assinatura, QR e quadro ficam sempre na mesma folha. Antes, quem
  garantia isso eram dois `KeepTogether` separados, um para a assinatura e
  outro para o quadro, e os dois podiam cair em folhas diferentes. Agora o
  bloco é um só.

Cada via do controle especial continua numa folha própria, com o próprio
rodapé.

**A posição não afeta a assinatura digital.** O campo PAdES é invisível
(`signing.sign_pdf` não desenha caixa), e a assinatura cobre o arquivo
inteiro, não um retângulo da página. A bateria assina PDFs de verdade e
confere a validação.

## Um defeito que ficou à vista

No quadro do fornecedor, "Assinatura do farmacêutico:" e "Carimbo da
farmácia / drogaria:" saíam cortados por uma linha. O texto tinha
entrelinha de 15 pt numa fileira de 0,42 cm (cerca de 12 pt) e vazava
para cima. O defeito existia antes, e ficou evidente quando o quadro
desceu para o pé da folha. Os dois rótulos ganharam estilo próprio
(`CONTROL_CAPTION`, entrelinha de 9 pt) e a fileira passou a 0,5 cm.

## Evidência

`check_rodape_do_documento.py` mede **onde** o texto cai na página, pelas
coordenadas que o `pypdf` extrai. Procurar o texto não bastaria: um
roteiro desses passaria com a assinatura no meio da folha. São cinco
seções:

1. receita curta: uma página, assinatura no quarto de baixo, e espaço
   entre o corpo e ela;
2. controle especial curto: duas vias, e em cada uma o quadro no pé,
   **abaixo** da assinatura, como no formulário do Anexo XVII;
3. corpo que enche a folha: a assinatura, o QR e o quadro juntos, no pé da
   página seguinte;
4. relatório de duas páginas: a assinatura no pé da última, e só nela;
5. pedido de exame e encaminhamento: uma página, assinatura no pé, sem
   folha extra.

**Conferido contra o defeito.** Com o comportamento antigo simulado
(rodapé logo depois do corpo), o roteiro reprova em 8 verificações.

## O que fica aberto

Quando o rodapé vai para a página seguinte, essa página tem só o rodapé,
sem repetir o cabeçalho nem a identificação do paciente. Era assim antes
(o rodapé ia para o alto da folha seguinte) e continua assim, agora no pé.
Repetir o cabeçalho em páginas de continuação é melhoria à parte.
