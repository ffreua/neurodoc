"""As recusas do cadastro de contato saem em português (auditoria da 1.24, B1).

`PatientContact.clean()` recusava em inglês, e o formulário da tela é um
`ModelForm`: o `_post_clean` chama o `clean()` do modelo mesmo depois do do
formulário. Resultado na tela:
- sem telefone nem e-mail: "Informe telefone ou e-mail." **e** "A contact
  needs a phone or an e-mail", uma embaixo da outra;
- contato autorizado a receber documento sem relação, ou representante legal
  sem comprovação: a recusa saía **só** em inglês, no campo.

`check_idioma` não pegava: cada frase tinha menos de duas palavras da lista
dele. Este roteiro passa pelo formulário de verdade e lê o que a tela leria.

    docker compose exec -T app python manage.py shell < checks/check_contato_em_portugues.py
"""
from patients.forms import PatientContactForm

falhas = []

INGLES = ('contact', 'needs', 'registered', 'relationship', 'legal authority', 'evidence', 'phone or')


def conferir(nome, ok, detalhe=''):
    print(f"  {'ok   ' if ok else 'FALHA'} {nome}" + (f' -> {detalhe}' if not ok and detalhe else ''))
    if not ok:
        falhas.append(nome)


def erros(dados):
    form = PatientContactForm(data=dados)
    valido = form.is_valid()
    return valido, {campo: list(lista) for campo, lista in form.errors.items()}


def texto_de(erros_):
    return ' | '.join(m for lista in erros_.values() for m in lista)


print('=== 1. Sem telefone nem e-mail ===')
valido, e = erros({'name': 'Fulano de Tal'})
conferir('é recusado', not valido, e)
conferir('nenhuma palavra em inglês', not any(p in texto_de(e).lower() for p in INGLES), e)
mensagens = e.get('__all__', [])
conferir('a recusa aparece uma vez só', mensagens.count('Informe telefone ou e-mail.') == 1, mensagens)

print('=== 2. Autorizado a receber documentos sem relação ===')
valido, e = erros({'name': 'Fulano de Tal', 'phone': '11999990000', 'authorized_for_documents': 'on'})
conferir('é recusado', not valido, e)
conferir('a recusa é do campo relação', 'relationship' in e, e)
conferir('em português', not any(p in texto_de(e).lower() for p in INGLES), e)

print('=== 3. Representante legal sem comprovação ===')
valido, e = erros({'name': 'Fulano de Tal', 'phone': '11999990000',
                   'relationship': 'Mãe', 'legal_authority': 'on'})
conferir('é recusado', not valido, e)
conferir('a recusa é do campo comprovação', 'authority_evidence' in e, e)
conferir('em português', not any(p in texto_de(e).lower() for p in INGLES), e)

print('=== 4. O caminho certo continua aceito ===')
valido, e = erros({'name': 'Fulano de Tal', 'phone': '11999990000',
                   'relationship': 'Mãe', 'authorized_for_documents': 'on',
                   'legal_authority': 'on', 'authority_evidence': 'Certidão de nascimento conferida.'})
conferir('contato completo é aceito', valido, e)
valido, e = erros({'name': 'Fulano de Tal', 'email': 'fulano@example.com'})
conferir('só e-mail é aceito', valido, e)

if falhas:
    print(f'\nFALHA: {len(falhas)} — ' + '; '.join(falhas))
    raise SystemExit(1)
print('\nOK: as recusas do cadastro de contato saem em português, uma vez cada.')
