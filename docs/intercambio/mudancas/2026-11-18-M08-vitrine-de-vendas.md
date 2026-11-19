---
id: MD-2026-11-18-05
data: 2026-11-18
origem: sessao-unica
tipo: vitrine + SEO
sigiloso: nao
estado_aqui: verificado no ambiente local; não publicado
roteiro_aqui: checks/check_seo.py, checks/check_landing.py, checks/check_mobile.py
no_outro: feito na mesma rodada — PD-M-2026-11-18-06
---

# Vitrine de vendas e páginas de entrada da busca

Vitrine repaginada sobre a do ProntDoc (efeitos de rolagem e de cursor, copy de vendas, IA, portal com WhatsApp, SNCR, TISS e estruturado ou texto livre em destaque, código aberto citado de leve); o NeuroDoc como produto de neurologia, com as outras especialidades encaminhadas ao ProntDoc; dezoito páginas de entrada da busca (`base/paginas_seo.py`, `onboarding/tematica.html`, trazidas do ProntDoc); `llms.txt` sem a frase falsa "os dados ficam no Brasil". `check_seo` seção 9 reescrita para a regra nova. Versão 1.51.

**No outro lado.** No ProntDoc: a mesma rolagem horizontal no celular (28 px a 390 px), medida em produção e corrigida no `landing.css` de lá. A frase sobre o Brasil não existia lá.
