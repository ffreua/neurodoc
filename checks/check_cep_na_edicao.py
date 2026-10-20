"""O CEP novo troca o endereço também na EDIÇÃO da ficha.

Relatado em uso real (2026-10-20): o paciente mudou de casa, o médico
abriu a ficha, digitou o CEP novo — e só município e UF mudaram. A busca
funcionava; quem barrava era a regra do preenchimento, "só escreve em
campo vazio", feita para não apagar o logradouro digitado antes do CEP
no cadastro novo. Na edição a rua antiga já vem preenchida do banco, e a
regra a tomava por escolha de quem estava na tela.

A regra agora é "não reescreve o que foi digitado NESTA tela", e número
e complemento da casa anterior saem quando o CEP muda. O comportamento é
de navegador (conferido no Chrome na homologação da 1.19.1); este roteiro
é a varredura que impede a regra antiga de voltar sem ninguém perceber.

As perguntas são:
  1. o preenchimento distingue o digitado nesta tela do que veio do banco?
  2. a mudança de CEP é medida contra o CEP com que a ficha abriu?
  3. número e complemento antigos saem quando o CEP muda?
  4. o cadastro novo (CEP inicial vazio) não apaga nada digitado à mão?
  5. as duas telas — cadastro e edição — continuam usando o mesmo script?
"""
from pathlib import Path

from django.conf import settings

BASE = Path(settings.BASE_DIR)
js = (BASE / 'static' / 'patients' / 'patient_form.js').read_text(encoding='utf-8')
tela = (BASE / 'templates' / 'patients' / 'form.html').read_text(encoding='utf-8')
views = (BASE / 'patients' / 'views.py').read_text(encoding='utf-8')

falhas = []


def conferir(condicao, rotulo):
    print(('ok    ' if condicao else 'FALHA ') + rotulo)
    if not condicao:
        falhas.append(rotulo)


print('=== 1. o digitado nesta tela, e não o que veio do banco ===')
conferir("addEventListener('input', function () { digitado[name] = true; })" in js,
         'cada campo do endereço marca quando foi digitado')
conferir("field.value.trim() && digitado[name]) return;" in js,
         'só preserva o campo preenchido SE foi digitado aqui')
conferir("if (!force && field.value.trim()) return;" not in js,
         'a regra antiga ("só escreve em campo vazio") não voltou')

print('=== 2. mudança medida contra o CEP de abertura ===')
conferir("var cepInicial = cep ? onlyDigits(cep.value) : '';" in js,
         'o CEP com que a ficha abriu é guardado')
conferir("Boolean(cepInicial) && digits !== cepInicial" in js,
         'redigitar o mesmo CEP não conta como mudança de endereço')

print('=== 3. número e complemento da casa anterior saem ===')
conferir("['number', 'complement'].forEach(limparDoEnderecoAnterior)" in js,
         'número e complemento limpos quando o CEP muda')
conferir("['street', 'district'].forEach(limparDoEnderecoAnterior)" in js,
         'rua e bairro antigos saem mesmo com CEP geral de cidade')
conferir("if (field && !digitado[name]) field.value = '';" in js,
         'o que foi digitado nesta tela não é limpo')

print('=== 4. cadastro novo ===')
conferir('Boolean(cepInicial)' in js,
         'sem CEP inicial (cadastro novo) nada é tratado como endereço anterior')

print('=== 5. o mesmo script nas duas telas ===')
conferir("patients/patient_form.js" in tela and 'data-cep-url' in tela,
         'o formulário carrega o script e a rota da busca')
conferir(views.count("'patients/form.html'") >= 2 or views.count('patients/form.html') >= 2,
         'cadastro e edição usam o mesmo formulário')

if falhas:
    print(f'\nFALHA: {len(falhas)} item(ns): ' + '; '.join(falhas))
    raise SystemExit(1)
print('\nOK: o CEP novo troca o endereço na edição sem apagar o digitado à mão.')
