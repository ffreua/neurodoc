"""As sete versões do TISS são sete, e não uma com sete rótulos (1.30, Sprint 1).

Tenta quebrar:

- o pacote de cada versão bate com o manifesto (SHA-256), e um XSD
  adulterado no disco é recusado antes de virar regra de validação;
- cada versão carrega o seu XSD e declara o namespace oficial;
- o XML anexado ao pedido do módulo (`tiss/exemplos/`) é **reprovado** — como
  veio (namespace errado) e com o namespace corrigido (estrutura da
  4.01.00) —, e o hash dele é o MD5 da cadeia vazia;
- DTD e entidade externa (XXE) são recusados antes do parse;
- o domínio vem do XSD de cada versão: `05` (exame ambulatorial) existe até
  a 4.00.01 e some na 4.01.00, que traz o `23`;
- o rótulo `04.03.00` vira `4.03.00`, e versão desconhecida é recusada;
- CNPJ alfanumérico: o exemplo da Receita passa, DV errado não, e todo
  numérico válido continua válido;
- credenciamento: registro ANS de seis dígitos exigido, CNPJ com letra só
  na 4.03.00, e versão histórica só exporta para cobrança com o aceite
  declarado.

    docker compose exec -T app python manage.py shell < checks/check_tiss_versoes.py
"""
import hashlib
import shutil
import tempfile
from pathlib import Path
from unittest.mock import patch

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from patients.models import Insurer
from tenancy.models import Tenant
from tiss import validators, versoes
from tiss.models import Credenciamento, Prestador

falhas = []


def conferir(nome, ok, detalhe=''):
    print(f"  {'ok   ' if ok else 'FALHA'} {nome}" + (f' -> {detalhe}' if not ok and detalhe else ''))
    if not ok:
        falhas.append(nome)


class Desfazer(Exception):
    pass


print('=== 1. Sete pacotes, cada um conferido contra o manifesto ===')
conferir('sete versões', list(versoes.VERSOES) == [
    '4.03.00', '4.02.00', '4.01.00', '4.00.01', '4.00.00', '3.05.00', '3.04.00'])
for codigo in versoes.VERSOES:
    try:
        versoes.conferir_pacote(codigo)
        sch = versoes.schema(codigo)
        conferir(f'{codigo}: pacote íntegro e XSD carregado', sch is not None)
    except Exception as exc:
        conferir(f'{codigo}: pacote íntegro e XSD carregado', False, f'{type(exc).__name__}: {exc}')
    principal = (versoes.PASTA_XSD / versoes.versao(codigo).pasta / versoes.versao(codigo).principal).read_text('latin-1')
    conferir(f'{codigo}: namespace oficial', f'targetNamespace="{versoes.NAMESPACE}"' in principal)

with tempfile.TemporaryDirectory() as tmp:
    copia = Path(tmp) / 'xsd'
    shutil.copytree(versoes.PASTA_XSD, copia)
    alvo = copia / '040300' / 'tissSimpleTypesV4_03_00.xsd'
    alvo.write_bytes(alvo.read_bytes().replace(b'[A-Z0-9]{12}[0-9]{2}', b'.*'))
    with patch.object(versoes, 'PASTA_XSD', copia):
        try:
            versoes.conferir_pacote('4.03.00')
            conferir('XSD adulterado no disco é recusado', False, 'aceitou')
        except versoes.PacoteAdulterado:
            conferir('XSD adulterado no disco é recusado', True)

print('=== 2. O anexo do pedido é reprovado, e por quê ===')
anexo = (Path(versoes.__file__).parent / 'exemplos' / 'anexo_reprovado_4_01_00.xml').read_bytes()
erros = versoes.validar('4.01.00', anexo)
conferir('como veio: reprovado', bool(erros))
conferir('pelo namespace', any('No matching global declaration' in e for e in erros), str(erros[:1]))
corrigido = anexo.replace(b'http://www.ans.gov.br/padraotiss/schemas', versoes.NAMESPACE.encode())
erros = ' | '.join(versoes.validar('4.01.00', corrigido))
for esperado in ('versaoPadrao', 'sequencialProcedimento', 'valorTotalGuia', "'05'"):
    conferir(f'namespace corrigido, ainda reprovado em {esperado}', esperado in erros)
conferir('o hash do anexo é o MD5 da cadeia vazia',
         hashlib.md5(b'').hexdigest() == 'd41d8cd98f00b204e9800998ecf8427e'
         and b'd41d8cd98f00b204e9800998ecf8427e' in anexo)

print('=== 3. DTD e entidade externa são recusados ===')
for rotulo, dados in (
    ('DOCTYPE com entidade externa', b'<?xml version="1.0"?><!DOCTYPE x [<!ENTITY e SYSTEM "file:///etc/passwd">]><x>&e;</x>'),
    ('DOCTYPE em minúsculas', b'<?xml version="1.0"?><!doctype x><x/>'),
    ('não é XML', b'isto nao e xml'),
):
    try:
        versoes.carregar_xml(dados)
        conferir(f'{rotulo}: recusado', False, 'aceitou')
    except versoes.XmlRecusado:
        conferir(f'{rotulo}: recusado', True)

print('=== 4. O domínio vem do XSD de cada versão ===')
conferir('05 existe na 4.00.00', '05' in versoes.dominio('4.00.00', 'dm_tipoAtendimento'))
conferir('05 existe na 4.00.01', '05' in versoes.dominio('4.00.01', 'dm_tipoAtendimento'))
conferir('05 não existe na 4.01.00', '05' not in versoes.dominio('4.01.00', 'dm_tipoAtendimento'))
conferir('23 (exame) existe na 4.03.00', '23' in versoes.dominio('4.03.00', 'dm_tipoAtendimento'))
conferir('CBO do neurologista em todas', all('225112' in versoes.dominio(v, 'dm_CBOS') for v in versoes.VERSOES))
conferir('a 4.03.00 tem mais CBOs que a 3.04.00',
         len(versoes.dominio('4.03.00', 'dm_CBOS')) > len(versoes.dominio('3.04.00', 'dm_CBOS')))
conferir('tipo inexistente devolve lista vazia', versoes.dominio('4.03.00', 'dm_naoExiste') == [])
conferir('04.03.00 vira 4.03.00', versoes.versao('04.03.00').codigo == '4.03.00')
try:
    versoes.versao('5.00.00')
    conferir('versão desconhecida recusada', False)
except versoes.VersaoDesconhecida:
    conferir('versão desconhecida recusada', True)

print('=== 5. CNPJ alfanumérico ===')
conferir('exemplo da Receita (12.ABC.345/01DE-35)', validators.cnpj_valido('12.ABC.345/01DE-35'))
conferir('DV errado recusado', not validators.cnpj_valido('12.ABC.345/01DE-36'))
conferir('numérico válido continua válido', validators.cnpj_valido('69.887.146/0001-05'))
conferir('minúscula é normalizada', validators.cnpj_valido('12abc34501de35'))
conferir('repetido recusado', not validators.cnpj_valido('00000000000000'))
conferir('registro ANS com zero à esquerda', validators.registro_ans_valido('005711'))
conferir('registro ANS sem o zero recusado', not validators.registro_ans_valido('5711'))

print('=== 6. As regras do credenciamento ===')
clinica = Tenant.objects.get(slug='demo-clinica-a')
try:
    with transaction.atomic():
        sem_registro = Insurer.objects.create(tenant=clinica, name='SEM REGISTRO ROTEIRO', ans_registration='5711')
        hapvida = Insurer.objects.create(tenant=clinica, name='OPERADORA ROTEIRO', ans_registration='368253')
        pj_letra = Prestador.objects.create(tenant=clinica, nome='PJ LETRA', cnpj='12ABC34501DE35')
        pj = Prestador.objects.create(tenant=clinica, nome='PJ NUM', cnpj='69887146000105')

        def erros_de(codigo='123', **campos):
            cred = Credenciamento(tenant=clinica, codigo_na_operadora=codigo, **campos)
            try:
                cred.full_clean(exclude=['tenant'])
                return {}
            except ValidationError as exc:
                return exc.message_dict

        conferir('registro ANS de 5 dígitos recusado', 'operadora' in erros_de(prestador=pj, operadora=sem_registro))
        conferir('CNPJ com letra na 4.02.00 recusado', 'versao' in erros_de(
            prestador=pj_letra, operadora=hapvida, identificacao='cnpj', versao='4.02.00'))
        conferir('CNPJ com letra na 4.03.00 aceito', not erros_de(
            prestador=pj_letra, operadora=hapvida, identificacao='cnpj', versao='4.03.00'))
        conferir('identificação por código exige o código', 'codigo_na_operadora' in erros_de(
            codigo='', prestador=pj, operadora=hapvida, identificacao='codigo'))
        conferir('código com zero à esquerda é preservado', not erros_de(
            codigo='000123', prestador=pj, operadora=hapvida, identificacao='codigo'))
        cred = Credenciamento(tenant=clinica, prestador=pj, operadora=hapvida, codigo_na_operadora='1', versao='3.04.00')
        conferir('3.04.00 sem aceite: só conferência', not cred.exporta_para_cobranca)
        cred.aceite_versao_em, cred.aceite_versao_motivo = timezone.now(), 'portal recebeu o lote de 10/2026'
        conferir('3.04.00 com aceite declarado: cobrança', cred.exporta_para_cobranca)
        conferir('4.00.00 exporta sem aceite', Credenciamento(
            tenant=clinica, prestador=pj, operadora=hapvida, versao='4.00.00').exporta_para_cobranca)
        raise Desfazer
except Desfazer:
    pass

print()
if falhas:
    print(f'FALHOU: {len(falhas)} verificação(ões): {falhas}')
    raise SystemExit(1)
print('Tudo certo.')
