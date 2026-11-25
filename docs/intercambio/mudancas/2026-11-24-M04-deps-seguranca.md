# 2026-11-24 — Pillow e pypdf: correção de segurança (pentest Strix)

| Campo | Valor |
| --- | --- |
| Lado | NeuroDoc, na mesma rodada que o ProntDoc |
| Tipo | achado de segurança (dependências), corrigido nos dois |
| Origem | pentest local com Strix (OSS), contra o ambiente de demonstração |

**Achado.** O `requirements.txt` fixava `Pillow==12.3.0` e `pypdf==6.17.0`,
as duas com avisos de segurança conhecidos. Conferido na base oficial (OSV):

- **Pillow 12.3.0:** 62 avisos, todos corrigidos na **13.0.0** (estouro de heap
  na decodificação de imagem — o caminho da prévia de anexo, `documents/preview.py`
  `Image.open`; CVE-2026-112403 e outros).
- **pypdf 6.17.0:** 32 avisos, todos corrigidos até a **6.21.4** (negação de
  serviço na leitura de PDF — a validação do envio, `documents/validators.py`
  `PdfReader`, alcançável pelo **portal público** do paciente; CVE-2026-102994
  e outros). O Strix apontou só a 6.18.0; a leitura do OSV mostrou que faltariam
  ~26 avisos, por isso fomos à última da série 6.

**Correção.** `requirements.in`: `Pillow>=13,<14` e `pypdf>=6.21.4,<7`
(a série 6 evita o salto de major para 7.x). No `requirements.txt`, só os
blocos desses dois pacotes mudaram, com os hashes oficiais do PyPI — nenhum
outro pacote foi tocado (o `uvloop` e os demais ficaram idênticos; recompilar
o arquivo inteiro com um `uv` diferente arrastaria dependências sem relação).

**Verificação.** Imagem reconstruída nos dois (a instalação confere os hashes),
versões confirmadas no contêiner, `check_exames_do_portal`, `check_receitas`
e `check_modelos` passando, e smoke test da prévia de imagem e da leitura de PDF.

**Não é mudança de comportamento**, então `VERSION` não muda (o `RELEASE_ID`
identifica a correção). O teste dinâmico do Strix contra o app no ar (isolamento,
papéis, IDOR, portal, injeção, XSS, SSRF, login) **não achou falha explorável**.
