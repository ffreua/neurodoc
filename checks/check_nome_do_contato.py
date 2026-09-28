"""Renomear o paciente renomeia o contato dele, e so o dele.

Encontrado em uso real. Um cadastro criado como "Teste 2 da Silva" foi
editado e virou um paciente de verdade; a ficha passou a mostrar o nome
novo e a lista de Contatos continuou com o antigo ao lado do telefone
certo. `created_at == updated_at` no contato provou que ele nunca tinha
sido tocado: `PatientUpdateView` salvava o paciente e nao olhava para os
contatos.

O contato do proprio paciente guarda uma **copia** do nome, e copia
diverge. Nao e cosmetico: esse nome e o que aparece no comprovante de
entrega de documento (`templates/documents/medical_detail.html`), onde
responde "para quem esta receita foi enviada". Errado ali, e registro de
entrega apontando para outra pessoa.

O que este roteiro cobra:

- renomear o paciente renomeia o contato do **proprio** paciente;
- **nao** renomeia o de um parente -- o nome de quem cuida do paciente nao
  se deduz do nome dele, e sincroniza-lo apagaria a informacao;
- a sincronizacao e idempotente: salvar sem mudar nome nao escreve;
- a relacao "Proprio paciente" vem de **uma** constante. Estava escrita a
  mao em dois modulos, e quem ajustasse a acentuacao de uma faria o
  contato do paciente passar a ser tratado como o de um terceiro -- sem
  erro nenhum, so deixando de sincronizar;
- o pre-cadastro nasce coerente.
"""
from django.conf import settings as dj_settings
from django.test import Client

dj_settings.ALLOWED_HOSTS = list(dj_settings.ALLOWED_HOSTS) + ['testserver']
dj_settings.SECURE_SSL_REDIRECT = False

from patients.contacts import SELF_RELATIONSHIP, sync_self_contact_name
from patients.models import Patient, PatientContact, RegistrationStage
from tenancy.models import Membership, MembershipStatus, Tenant

falhas = []
criados = []


def _cpf_valido(base):
    """Completa os dois digitos verificadores. O cadastro confere."""
    n = [int(x) for x in base]
    d1 = (sum(v * p for v, p in zip(n, range(10, 1, -1))) * 10) % 11 % 10
    d2 = (sum(v * p for v, p in zip(n + [d1], range(11, 1, -1))) * 10) % 11 % 10
    return base + str(d1) + str(d2)


def conferir(rotulo, obtido, esperado):
    ok = obtido == esperado
    print(f'  {"ok " if ok else "FALHA"}  {rotulo:58} -> {obtido}')
    if not ok:
        falhas.append(f'{rotulo}: esperado {esperado}, obtido {obtido}')


tenant = Tenant.objects.get(slug='demo-clinica-a')
vinculo = Membership.objects.filter(
    tenant=tenant, status=MembershipStatus.ACTIVE,
).select_related('user').first()

try:
    print('\n1. A relacao vem de uma constante, e nao de duas strings')
    import inspect

    from patients import forms as pforms
    from scheduling import services as sservices

    for modulo, nome in [(pforms, 'patients/forms.py'), (sservices, 'scheduling/services.py')]:
        fonte = inspect.getsource(modulo)
        conferir(f'{nome} nao repete a string', "'Próprio paciente'" in fonte, False)
        conferir(f'{nome} usa a constante', 'SELF_RELATIONSHIP' in fonte, True)

    print('\n2. Renomear o paciente renomeia o contato dele')
    paciente = Patient.objects.create(
        tenant=tenant, full_name='Teste 2 da SIlva',
        birth_date_unknown_reason='Roteiro de verificacao.',
        registration_stage=RegistrationStage.PRELIMINARY,
    )
    criados.append(paciente.id)
    proprio = PatientContact.objects.create(
        tenant=tenant, patient=paciente, name='Teste 2 da SIlva',
        relationship=SELF_RELATIONSHIP, phone='11984006131',
    )
    parente = PatientContact.objects.create(
        tenant=tenant, patient=paciente, name='Maria da Silva',
        relationship='Mãe', phone='11955554444',
    )

    paciente.full_name = 'Fernando Freua'
    paciente.save(update_fields=['full_name'])
    mudou = sync_self_contact_name(paciente)
    proprio.refresh_from_db()
    parente.refresh_from_db()

    conferir('o contato do proprio paciente acompanha', proprio.name, 'Fernando Freua')
    conferir('devolve quantas linhas mudaram', mudou, 1)

    print('\n3. O contato do parente NAO e tocado')
    conferir('o nome da mae continua o dela', parente.name, 'Maria da Silva')
    conferir('a relacao dela tambem', parente.relationship, 'Mãe')

    print('\n4. Sincronizar de novo nao escreve')
    conferir('nada a fazer na segunda vez', sync_self_contact_name(paciente), 0)

    print('\n5. Pelo caminho de verdade: a tela de edicao')
    # A funcao pode estar certa e ninguem chama-la. Esta secao passa pela
    # view, que e onde o defeito morava.
    paciente2 = Patient.objects.create(
        tenant=tenant, full_name='Nome Antigo Do Roteiro',
        birth_date_unknown_reason='Roteiro de verificacao.',
        registration_stage=RegistrationStage.PRELIMINARY,
    )
    criados.append(paciente2.id)
    c2 = PatientContact.objects.create(
        tenant=tenant, patient=paciente2, name='Nome Antigo Do Roteiro',
        relationship=SELF_RELATIONSHIP, phone='11933332222',
    )
    cliente = Client()
    cliente.force_login(vinculo.user)
    sessao = cliente.session
    sessao['tenant_id'] = str(tenant.id)
    sessao.save()
    # O corpo do POST e **derivado do formulario**, e nao escrito a mao:
    # a ficha tem seis campos obrigatorios, e uma lista escrita aqui
    # passaria a faltar um no dia em que o cadastro ganhasse outro -- com
    # o roteiro acusando "o contato nao acompanhou" quando o que houve foi
    # formulario invalido. A primeira versao deste roteiro caiu nisso.
    from patients.forms import PatientForm

    molde = PatientForm(instance=paciente2, tenant_id=tenant.id)
    corpo = {'row_version': str(paciente2.row_version)}
    for nome_campo, campo in molde.fields.items():
        if not campo.required:
            continue
        if nome_campo == 'full_name':
            corpo[nome_campo] = 'Nome Novo Do Roteiro'
        elif nome_campo == 'cpf':
            corpo[nome_campo] = _cpf_valido('529982247')
        elif hasattr(campo, 'choices'):
            opcoes = [v for v, _ in campo.choices if v not in ('', None)]
            corpo[nome_campo] = opcoes[0]
        else:
            corpo[nome_campo] = 'Roteiro'
    corpo['birth_date_unknown_reason'] = 'Roteiro de verificacao.'
    resposta = cliente.post(f'/app/patients/{paciente2.id}/edit/', corpo)
    if resposta.status_code == 200:
        # Formulario invalido: mostra por que, em vez de deixar a falha
        # aparecer como "o contato nao acompanhou".
        conteudo = resposta.content.decode('utf-8', 'replace')
        import re as _re
        erros = _re.findall(r'invalid-feedback[^>]*>\s*([^<]{3,90})', conteudo)
        print('  formulario recusado:', erros[:4] or '(sem mensagem legivel)')
    paciente2.refresh_from_db()
    c2.refresh_from_db()
    print(f'  POST na edicao -> HTTP {resposta.status_code}')
    conferir('a ficha mudou de nome', paciente2.full_name, 'Nome Novo Do Roteiro')
    conferir('e o contato acompanhou pela view', c2.name, 'Nome Novo Do Roteiro')

    print('\n6. O pre-cadastro ja nasce coerente')
    from scheduling.services import quick_register_patient
    from tenancy.context import AccessContext

    ctx = AccessContext(
        user_id=vinculo.user_id, tenant_id=tenant.id, membership_id=vinculo.id,
        permissions=frozenset(vinculo.roles or []), request_id=None,
        tenant_status=tenant.status, capabilities=frozenset(),
    )
    p3 = quick_register_patient(ctx, 'Recem Pre Cadastrado', '11911112222')
    criados.append(p3.id)
    c3 = PatientContact.objects.filter(patient=p3).first()
    conferir('nome do contato bate com o da ficha', c3.name, p3.full_name)
    conferir('e a relacao e a constante', c3.relationship, SELF_RELATIONSHIP)

finally:
    n = PatientContact.objects.filter(patient_id__in=criados).delete()[0]
    m = Patient.objects.filter(id__in=criados).delete()[0]
    print(f'\n  limpeza: {n} contato(s) e {m} objeto(s) removidos')

if falhas:
    for item in falhas:
        print('FALHA:', item)
    raise SystemExit(1)
print('\nOK: renomear o paciente acompanha o contato dele, nao mexe no do parente,')
print('    e a relacao vem de uma constante so.')
