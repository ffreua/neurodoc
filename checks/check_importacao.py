"""Migracao de cadastro: o que entra, o que nao entra, e o que nao se repete.

Importar duas mil fichas e uma operacao que se faz uma vez e se descobre
errada seis meses depois, quando o paciente chega e a ficha dele esta
estranha. O que este roteiro cobra e o que so se percebe tarde:

- **nada e autorizado a receber mensagem.** O sistema anterior nao
  registrou consentimento, e importar um telefone nao e a pessoa pedindo
  para ser chamada nele. Esta e a assercao mais importante do roteiro:
  errar aqui e mandar SMS para duas mil pessoas que nunca autorizaram;
- **o responsavel que e o proprio paciente nao vira contato extra.** O
  arquivo real traz 85 fichas assim. Sem a guarda, a gravacao do
  responsavel casava com o contato do proprio paciente pelo nome, trocava
  a relacao dele e **apagava o telefone recem-gravado** -- e so estourava
  na segunda execucao, longe da causa;
- **pode rodar duas vezes.** Migracao falha no meio; sem chave estavel, a
  segunda tentativa duplica o que a primeira gravou;
- **quem ja esta cadastrado aqui nao ganha uma segunda ficha.** Dois
  prontuarios para a mesma pessoa partem o historico clinico em dois, e o
  dano aparece no dia em que alguem abre o errado: a consulta de marco
  esta num, a de setembro no outro, e nenhum dos dois esta errado o
  bastante para alguem desconfiar;
- **CPF repetido nao derruba a importacao** nem some: o primeiro fica com
  ele, os outros entram sem CPF e com o conflito escrito na ficha;
- **ficha sem nome nao vira paciente**; data impossivel vira ausencia com
  o motivo escrito, e nao excecao;
- **cancelado la vira arquivado aqui**, e nao apagado.
"""
import xml.etree.ElementTree as ET
from datetime import date
from io import StringIO

from django.conf import settings as dj_settings

dj_settings.ALLOWED_HOSTS = list(dj_settings.ALLOWED_HOSTS) + ['testserver']
dj_settings.SECURE_SSL_REDIRECT = False

from django.core.management import call_command

from patients.contacts import SELF_RELATIONSHIP
from patients.importacao import (
    data_br, ler_registro, origem_da_indicacao, separar_endereco, telefones,
)
from patients.models import (
    MaritalStatus, Patient, PatientContact, PatientStatus, ReferralSource,
    RegistrationStage, SexAtRegistration,
)
from tenancy.models import Tenant

falhas = []


def conferir(rotulo, obtido, esperado):
    ok = obtido == esperado
    print(f'  {"ok " if ok else "FALHA"}  {rotulo:58} -> {obtido!r}')
    if not ok:
        falhas.append(f'{rotulo}: esperado {esperado!r}, obtido {obtido!r}')


def xml_de(fichas):
    """Monta um XML com a forma do arquivo real."""
    campos = [
        'NUM_ICLIN', 'NOME', 'NUM_PRONTUARIO', 'SEXO', 'DT_NASC', 'LOCAL_NASC',
        'ESTADO_CIVIL', 'PROFISSAO', 'CPF', 'IDENTIDADE', 'CNS', 'ENDERECO', 'CEP',
        'BAIRRO', 'MUNICIPIO', 'UF', 'TEL_RES', 'TEL_OUTRO', 'EMAIL', 'RESPONSAVEL',
        'RESPONSAVEL_PAR', 'CONV_ANS', 'CONV_NOME', 'PLANO_NOME', 'NUM_CONVENIADO',
        'NOME_TITULAR', 'NOME_EMPRESA', 'COD_PROF', 'PROF_NOME', 'INDICACAO',
        'CANCELADO', 'DT_INCLUSAO', 'DT_ALTERACAO',
    ]
    partes = ['<?xml version="1.0" encoding="UTF-8"?><CLIENTES>']
    for ficha in fichas:
        partes.append('<CLIENTE>')
        for campo in campos:
            partes.append(f'<{campo}>{ficha.get(campo, "")}</{campo}>')
        partes.append('</CLIENTE>')
    partes.append('</CLIENTES>')
    return ''.join(partes)


def um(**campos):
    return campos


tenant = Tenant.objects.get(slug='demo-clinica-a')
ARQUIVO = '/tmp/roteiro-importacao.xml'
criados_legacy = []


def importar(fichas, gravar=True, conflito=None):
    with open(ARQUIVO, 'w', encoding='utf-8') as destino:
        destino.write(xml_de(fichas))
    saida = StringIO()
    argumentos = ['--clinica', tenant.slug, '--arquivo', ARQUIVO]
    if conflito:
        argumentos += ['--conflito-cpf', conflito]
    if gravar:
        argumentos.append('--gravar')
    call_command('import_pacientes_xml', *argumentos, stdout=saida, stderr=saida)
    for f in fichas:
        if f.get('NUM_ICLIN'):
            criados_legacy.append(str(f['NUM_ICLIN']))
    return saida.getvalue()


def ficha_de(legacy):
    return Patient.objects.filter(tenant=tenant, legacy_id=str(legacy)).first()


try:
    print('\n1. As traducoes, isoladas')
    conferir('data brasileira', data_br('13/01/1941'), date(1941, 1, 13))
    conferir('data impossivel vira ausencia', data_br('30/02/1980'), None)
    conferir('data no futuro vira ausencia', data_br('01/01/2099'), None)
    conferir('data antes de 1900 vira ausencia', data_br('05/06/1850'), None)
    conferir('vazio vira ausencia', data_br(''), None)

    conferir('endereco com numero e complemento',
             separar_endereco('RUA DAS FLORES, 295 AP 804'),
             ('RUA DAS FLORES', '295', 'AP 804'))
    conferir('endereco so com numero',
             separar_endereco('AV PAULISTA, 134'), ('AV PAULISTA', '134', ''))
    conferir('endereco sem virgula fica inteiro no logradouro',
             separar_endereco('ESTRADA DO MAR KM 12'),
             ('ESTRADA DO MAR KM 12', '', ''))
    conferir('virgula sem numero vira complemento',
             separar_endereco('RUA X, FUNDOS'), ('RUA X', '', 'FUNDOS'))

    conferir('indicacao por medico', origem_da_indicacao('DR. ALEXANDRE SEGRE'),
             ReferralSource.PHYSICIAN)
    conferir('indicacao por paciente', origem_da_indicacao('IND. DE PACIENTE'),
             ReferralSource.PATIENT)
    conferir('indicacao desconhecida erra para "Outro"',
             origem_da_indicacao('BP'), ReferralSource.OTHER)
    conferir('indicacao vazia nao afirma nada',
             origem_da_indicacao(''), ReferralSource.NOT_INFORMED)

    print('\n2. Uma ficha completa vira cadastro completo')
    importar([um(
        NUM_ICLIN='R-9001', NOME='maria  da silva', DT_NASC='13/01/1941', CPF='52998224725',
        SEXO='F', ESTADO_CIVIL='CA', PROFISSAO='Professora', IDENTIDADE='12345678',
        ENDERECO='RUA DAS FLORES, 295 AP 804', CEP='01310100', BAIRRO='Centro',
        MUNICIPIO='Sao Paulo', UF='SP', TEL_OUTRO='11 988887777',
        EMAIL='MARIA@EXEMPLO.COM', CONV_NOME='PARTICULAR', INDICACAO='DR. FULANO',
        NUM_PRONTUARIO='4321', CANCELADO='N',
    )])
    p = ficha_de('R-9001')
    conferir('a ficha existe', p is not None, True)
    conferir('nome no padrao do sistema', p.full_name, 'MARIA DA SILVA')
    conferir('nascimento', p.birth_date, date(1941, 1, 13))
    conferir('CPF', p.cpf, '52998224725')
    conferir('sexo', p.sex_at_registration, SexAtRegistration.FEMALE)
    conferir('estado civil', p.marital_status, MaritalStatus.MARRIED)
    conferir('logradouro', p.street, 'RUA DAS FLORES')
    conferir('numero', p.number, '295')
    conferir('complemento', p.complement, 'AP 804')
    conferir('CEP so com digitos', p.postal_code, '01310100')
    conferir('cadastro COMPLETO, nao pre-cadastro',
             p.registration_stage, RegistrationStage.COMPLETE)
    conferir('ativo', p.status, PatientStatus.ACTIVE)
    conferir('ganhou numero de prontuario proprio', bool(p.record_number), True)
    conferir('o prontuario antigo ficou anotado',
             'Prontuário no sistema anterior: 4321' in p.administrative_notes, True)
    conferir('e a migracao ficou datada na ficha',
             'migrada do sistema anterior' in p.administrative_notes, True)

    print('\n3. Ninguem e autorizado a receber mensagem')
    # A assercao que mais importa: o sistema anterior nao registrou
    # consentimento, e telefone importado nao e pedido de contato.
    contato = PatientContact.objects.filter(patient=p, relationship=SELF_RELATIONSHIP).first()
    conferir('o contato do proprio paciente existe', contato is not None, True)
    conferir('com o telefone', contato.phone, '11988887777')
    conferir('e o e-mail em minuscula', contato.email, 'maria@exemplo.com')
    conferir('SMS desligado', contato.sms_enabled, False)
    conferir('e-mail desligado', contato.email_enabled, False)
    conferir('documento desligado', contato.authorized_for_documents, False)

    print('\n4. O responsavel que e o proprio paciente nao vira contato extra')
    # 85 fichas do arquivo real sao assim.
    importar([um(
        NUM_ICLIN='R-9002', NOME='Joao Souza', DT_NASC='02/03/1950', CPF='',
        TEL_OUTRO='11977776666', RESPONSAVEL='JOAO SOUZA', RESPONSAVEL_PAR='',
        CANCELADO='N', ENDERECO='RUA A, 10',
    )])
    p2 = ficha_de('R-9002')
    todos = list(PatientContact.objects.filter(patient=p2))
    conferir('tem um unico contato', len(todos), 1)
    conferir('e ele e o do proprio paciente', todos[0].relationship, SELF_RELATIONSHIP)
    conferir('com o telefone preservado', todos[0].phone, '11977776666')

    print('\n5. Responsavel de verdade vira o segundo contato')
    importar([um(
        NUM_ICLIN='R-9003', NOME='Crianca Teste', DT_NASC='10/10/2015', CPF='',
        TEL_OUTRO='11966665555', TEL_RES='1133334444',
        RESPONSAVEL='Ana Mae Teste', RESPONSAVEL_PAR='Mãe',
        CANCELADO='N', ENDERECO='RUA B, 20',
    )])
    p3 = ficha_de('R-9003')
    contatos3 = {c.relationship: c for c in PatientContact.objects.filter(patient=p3)}
    conferir('dois contatos', len(contatos3), 2)
    conferir('a mae entrou com o parentesco', 'Mãe' in contatos3, True)
    conferir('e o nome dela no padrao', contatos3['Mãe'].name, 'ANA MAE TESTE')
    conferir('ela tambem nasce sem autorizacao', contatos3['Mãe'].sms_enabled, False)

    print('\n6. Pode rodar duas vezes sem duplicar')
    antes = Patient.objects.filter(tenant=tenant, legacy_id__startswith='R-900').count()
    contatos_antes = PatientContact.objects.filter(
        patient__legacy_id__startswith='R-900',
    ).count()
    importar([
        um(NUM_ICLIN='R-9001', NOME='maria  da silva', DT_NASC='13/01/1941',
           CPF='52998224725', SEXO='F', ENDERECO='RUA DAS FLORES, 295 AP 804',
           TEL_OUTRO='11 988887777', EMAIL='MARIA@EXEMPLO.COM', CANCELADO='N'),
        um(NUM_ICLIN='R-9002', NOME='Joao Souza', DT_NASC='02/03/1950',
           TEL_OUTRO='11977776666', RESPONSAVEL='JOAO SOUZA', CANCELADO='N',
           ENDERECO='RUA A, 10'),
    ])
    conferir('o numero de fichas nao mudou',
             Patient.objects.filter(tenant=tenant, legacy_id__startswith='R-900').count(), antes)
    conferir('nem o de contatos',
             PatientContact.objects.filter(patient__legacy_id__startswith='R-900').count(),
             contatos_antes)

    print('\n7. CPF repetido: o primeiro fica com ele, o outro entra sem')
    importar([
        um(NUM_ICLIN='R-9010', NOME='Primeiro Cpf', DT_NASC='01/01/1960',
           CPF='39053344705', CANCELADO='N', ENDERECO='RUA C, 1'),
        um(NUM_ICLIN='R-9011', NOME='Segundo Cpf', DT_NASC='02/02/1962',
           CPF='39053344705', CANCELADO='N', ENDERECO='RUA C, 2'),
    ])
    a, b = ficha_de('R-9010'), ficha_de('R-9011')
    conferir('os dois entraram', a is not None and b is not None, True)
    conferir('o primeiro ficou com o CPF', a.cpf, '39053344705')
    conferir('o segundo entrou sem CPF', b.cpf, None)
    conferir('e o conflito ficou escrito na ficha dele',
             'veio repetido na importação' in b.administrative_notes, True)

    print('\n8. Quem ja esta cadastrado aqui nao ganha uma segunda ficha')
    # Dois prontuarios para a mesma pessoa partem o historico clinico em
    # dois, e o dano aparece no dia em que alguem abre o errado: a consulta
    # de marco esta num, a de setembro no outro, e nenhum dos dois esta
    # errado o bastante para alguem desconfiar.
    daqui = Patient.objects.create(
        tenant=tenant, full_name='Cadastrado Aqui Antes', cpf='15350946056',
        birth_date=date(1970, 5, 5), registration_stage=RegistrationStage.COMPLETE,
    )
    saida8 = importar([um(
        NUM_ICLIN='R-9020', NOME='Homonimo Importado', DT_NASC='06/06/1971',
        CPF='15350946056', CANCELADO='N', ENDERECO='RUA D, 4',
    )])
    daqui.refresh_from_db()
    conferir('por padrao, a ficha de la e PULADA', ficha_de('R-9020'), None)
    conferir('e o comando diz quantas pulou',
             'pulada(s) por ja existirem aqui' in saida8, True)
    conferir('a ficha daqui continua com o nome dela',
             daqui.full_name, 'CADASTRADO AQUI ANTES')
    conferir('e continua com o CPF', daqui.cpf, '15350946056')

    # `--conflito-cpf anotar` existe para quando se sabe que sao pessoas
    # diferentes com o mesmo CPF digitado.
    importar([um(
        NUM_ICLIN='R-9021', NOME='Homonimo Importado', DT_NASC='06/06/1971',
        CPF='15350946056', CANCELADO='N', ENDERECO='RUA D, 4',
    )], conflito='anotar')
    anotado = ficha_de('R-9021')
    conferir('com --conflito-cpf anotar, a ficha entra', anotado is not None, True)
    conferir('sem CPF', anotado.cpf, None)
    conferir('e com o conflito escrito',
             'pertencia a uma ficha' in anotado.administrative_notes, True)
    daqui.delete()

    print('\n9. Sem nome nao vira ficha; cancelado vira arquivado')
    saida = importar([
        um(NUM_ICLIN='R-9030', NOME='', DT_NASC='', CANCELADO='N'),
        um(NUM_ICLIN='R-9031', NOME='Cancelado La', DT_NASC='03/03/1980',
           CANCELADO='S', ENDERECO='RUA E, 5'),
        um(NUM_ICLIN='R-9032', NOME='Sem Nascimento', DT_NASC='', CANCELADO='N',
           ENDERECO='RUA F, 6'),
    ])
    conferir('a ficha sem nome nao foi criada', ficha_de('R-9030'), None)
    conferir('e o comando disse que ignorou', 'sem nome (ignoradas)    : 1' in saida, True)
    cancelado = ficha_de('R-9031')
    conferir('cancelado la entrou arquivado aqui', cancelado.status, PatientStatus.ARCHIVED)
    conferir('com o motivo escrito', 'Cancelado no sistema anterior' in cancelado.archived_reason, True)
    sem_nasc = ficha_de('R-9032')
    conferir('sem nascimento, o motivo fica escrito',
             'Não constava no sistema anterior' in sem_nasc.birth_date_unknown_reason, True)

    print('\n10. O ensaio nao escreve nada')
    importar([um(NUM_ICLIN='R-9040', NOME='Nunca Gravado', DT_NASC='04/04/1984',
                 CANCELADO='N', ENDERECO='RUA G, 7')], gravar=False)
    conferir('o ensaio nao criou ficha', ficha_de('R-9040'), None)

finally:
    alvo = Patient.objects.filter(tenant=tenant, legacy_id__in=criados_legacy)
    PatientContact.objects.filter(patient__in=alvo).delete()
    n = alvo.delete()[0]
    Patient.objects.filter(tenant=tenant, full_name='CADASTRADO AQUI ANTES').delete()
    print(f'\n  limpeza: {n} objeto(s) de paciente removidos')

if falhas:
    for item in falhas:
        print('FALHA:', item)
    raise SystemExit(1)
print('\nOK: a ficha migrada entra completa e sem autorizacao de mensagem,')
print('    a importacao pode ser repetida, e conflito de CPF nao derruba nada.')
