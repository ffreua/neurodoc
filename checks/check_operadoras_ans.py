"""O catálogo de operadoras da ANS, para cadastrar qualquer convênio (1.30).

Tenta quebrar, sem falar com a ANS (o CSV é montado aqui):

- o registro ANS guarda os seis dígitos — zero à esquerda incluso, mesmo
  se o arquivo o perder;
- acento e cedilha chegam inteiros; linha sem registro ou sem razão social
  é descartada sem derrubar o resto;
- arquivo sem as colunas esperadas é recusado;
- lista curta demais (arquivo truncado) não grava nada — senão marcaria
  centenas de operadoras como inativas;
- repetir a importação atualiza; a operadora que saiu da lista fica
  **inativa**, não apagada;
- a busca: palavras em qualquer ordem, sem acento, e o registro digitado
  sem os zeros ("5711" acha 005711); inativa não aparece;
- a rota de busca responde a quem tem vínculo, e não a quem não tem.

Tudo numa transação desfeita no fim.

    docker compose exec -T app python manage.py shell < checks/check_operadoras_ans.py
"""

from django.conf import settings as dj_settings
from django.db import transaction
from django.test import Client

dj_settings.ALLOWED_HOSTS = list(dj_settings.ALLOWED_HOSTS) + ['testserver']

from catalogs.management.commands import import_operadoras_ans as imp
from catalogs.models import OperadoraAns
from catalogs.selectors import search_operadoras
from tenancy.models import Membership, MembershipStatus, Tenant

falhas = []


def conferir(nome, ok, detalhe=''):
    print(f"  {'ok   ' if ok else 'FALHA'} {nome}" + (f' -> {detalhe}' if not ok and detalhe else ''))
    if not ok:
        falhas.append(nome)


class Desfazer(Exception):
    pass


CABECALHO = ('REGISTRO_OPERADORA;CNPJ;RAZAO_SOCIAL;NOME_FANTASIA;MODALIDADE;LOGRADOURO;NUMERO;'
             'COMPLEMENTO;BAIRRO;CIDADE;UF;CEP;DDD;TELEFONE;FAX;ENDERECO_ELETRONICO;REPRESENTANTE;'
             'CARGO_REPRESENTANTE;REGIAO_DE_COMERCIALIZACAO;DATA_REGISTRO_ANS')


def linha(registro, cnpj, razao, fantasia='', uf='SP'):
    return f'"{registro}";"{cnpj}";"{razao}";"{fantasia}";"Medicina de Grupo";;;;;;"{uf}";;;;;;;;;'


def csv_de(*linhas):
    return ('\n'.join([CABECALHO, *linhas]) + '\n').encode('utf-8')


print('=== 1. Leitura do arquivo ===')
dados = csv_de(
    linha('005711', '92693118000160', 'BRADESCO SAÚDE S.A.', 'BRADESCO SAUDE S.A.', 'RJ'),
    linha('5712', '1', 'OPERADORA SEM ZERO ROTEIRO'),
    linha('', '1', 'SEM REGISTRO'),
    linha('368253', '63554067000198', 'HAPVIDA ASSISTÊNCIA MÉDICA S.A.', 'HAPVIDA', 'CE'),
    linha('339679', '04201372000137', 'UNIMED DE BELÉM COOPERATIVA DE TRABALHO MÉDICO', '', 'PA'),
)
linhas, descartadas = imp.ler(dados)
por_registro = {item['registro_ans']: item for item in linhas}
conferir('zero à esquerda preservado', '005711' in por_registro)
conferir('registro sem o zero é completado', '005712' in por_registro)
conferir('linha sem registro descartada', descartadas == 1, str(descartadas))
conferir('acento inteiro', por_registro['368253']['razao_social'] == 'HAPVIDA ASSISTÊNCIA MÉDICA S.A.')
try:
    imp.ler(b'COLUNA;OUTRA\n1;2\n')
    conferir('arquivo sem as colunas recusado', False)
except ValueError:
    conferir('arquivo sem as colunas recusado', True)
try:
    imp.gravar(linhas)
    conferir('lista curta não grava', False, 'gravou')
except ValueError:
    conferir('lista curta não grava', True)

try:
    with transaction.atomic():
        OperadoraAns.objects.all().delete()
        enchimento = [linha(f'9{n:05d}', '', f'OPERADORA ENCHIMENTO {n}') for n in range(imp.MINIMO_ESPERADO)]
        primeira, _ = imp.ler(csv_de(*enchimento, linha('005711', '1', 'BRADESCO SAÚDE S.A.', 'BRADESCO SAUDE S.A.'),
                                      linha('368253', '1', 'HAPVIDA ASSISTÊNCIA MÉDICA S.A.', 'HAPVIDA', 'CE'),
                                      linha('339679', '1', 'UNIMED DE BELÉM COOPERATIVA DE TRABALHO MÉDICO', '', 'PA')))
        r1 = imp.gravar(primeira)
        print('=== 2. Gravar e repetir ===')
        conferir('gravou todas', OperadoraAns.objects.filter(ativa=True).count() == len(primeira), str(r1))
        segunda, _ = imp.ler(csv_de(*enchimento, linha('005711', '1', 'BRADESCO SAÚDE S.A.', 'BRADESCO SAÚDE'),
                                     linha('339679', '1', 'UNIMED DE BELÉM COOPERATIVA DE TRABALHO MÉDICO', '', 'PA')))
        r2 = imp.gravar(segunda)
        hap = OperadoraAns.objects.get(registro_ans='368253')
        conferir('quem saiu da lista fica inativa, não apagada', not hap.ativa and r2['inativadas'] == 1, str(r2))
        conferir('repetir atualiza o nome fantasia',
                 OperadoraAns.objects.get(registro_ans='005711').nome_fantasia == 'BRADESCO SAÚDE')

        print('=== 3. A busca ===')
        conferir('"unimed belem" acha a Unimed de Belém',
                 any(r['registro_ans'] == '339679' for r in search_operadoras('unimed belem')))
        conferir('"belem unimed", em outra ordem, também',
                 any(r['registro_ans'] == '339679' for r in search_operadoras('belem unimed')))
        conferir('"5711" acha 005711', any(r['registro_ans'] == '005711' for r in search_operadoras('5711')))
        conferir('inativa não aparece', not search_operadoras('hapvida'))
        conferir('uma letra não busca', search_operadoras('u') == [])

        print('=== 4. A rota ===')
        clinica = Tenant.objects.get(slug='demo-clinica-a')
        vinculo = Membership.objects.filter(tenant=clinica, status=MembershipStatus.ACTIVE).select_related('user').first()
        c = Client(SERVER_NAME='localhost')
        c.force_login(vinculo.user)
        s = c.session
        s['tenant_id'] = str(clinica.id)
        s.save()
        r = c.get('/app/codigos/operadoras/buscar/', {'q': 'bradesco'})
        conferir('com vínculo, responde', r.status_code == 200 and r.json()['results'], str(r.status_code))
        anonimo = Client(SERVER_NAME='localhost').get('/app/codigos/operadoras/buscar/', {'q': 'bradesco'})
        conferir('sem login, não responde', anonimo.status_code in (302, 404), str(anonimo.status_code))
        raise Desfazer
except Desfazer:
    pass

print()
if falhas:
    print(f'FALHOU: {len(falhas)} verificação(ões): {falhas}')
    raise SystemExit(1)
print('Tudo certo.')
