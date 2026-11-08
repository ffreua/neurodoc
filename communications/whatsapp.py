"""Lembrete pelo WhatsApp da própria clínica, enviado pela recepção (1.39).

**O NeuroDoc não envia mensagem de WhatsApp.** Ele monta o texto que a
clínica escreveu, com os dados do horário, e abre a conversa com o paciente
pelo link oficial `wa.me` — no WhatsApp Web ou no aplicativo da clínica. Quem
aperta "enviar" é a secretária, do número da clínica, como faria à mão.

As duas alternativas foram estudadas e recusadas (2026-11-08):

- **A API oficial da Meta** automatizaria o envio, mas exige o NeuroDoc
  credenciado como provedor na Meta, um modelo de mensagem aprovado a cada
  texto (até 24 h, e qualquer edição volta à análise), cartão de cada clínica
  na conta dela e cobrança por mensagem. Fica para depois, se o volume pedir.
- **Conectar o WhatsApp da clínica por QR Code** (Baileys, Evolution API,
  Z-API e afins) finge ser o WhatsApp Web, fere os termos do WhatsApp e expõe
  o número da clínica a bloqueio — justamente o número que os pacientes
  conhecem —, além de deixar no servidor uma sessão que lê todas as conversas
  dela.

O link não tem nenhum desses custos: não passa pela Meta como integração, não
precisa de aprovação, sai com acento e no texto inteiro, vale em todos os
planos e não põe o número em risco, porque o envio é de uma pessoa.

Duas regras do texto:

- **Os campos são uma lista fechada**, substituídos por expressão regular, e
  não por `str.format`: com `format`, um texto da clínica com
  `{paciente.__class__}` atravessaria atributos do objeto. Campo desconhecido
  é recusado ao salvar, com a lista dos que existem.
- **Nada clínico.** Os campos são de agenda — quando, com quem, onde. A
  política do WhatsApp manda não trafegar informação de saúde, e o texto
  passa pelos servidores dele.
"""

import re
from urllib.parse import quote

from django.utils import timezone

#: O que a clínica pode usar no texto, na ordem em que a tela mostra.
CAMPOS = {
    'primeiro_nome': 'primeiro nome do paciente (Maria)',
    'paciente': 'nome completo do paciente (Maria da Silva)',
    'data': 'data da consulta (25/11/2026)',
    'dia_semana': 'dia da semana (terça-feira)',
    'hora': 'horário (14:30)',
    'medico': 'nome do médico',
    'tipo': 'tipo de atendimento (Primeira consulta, Seguimento, Retorno…)',
    'clinica': 'nome da clínica',
    'endereco': 'endereço da clínica',
    'telefone_clinica': 'telefone da clínica',
}

#: O teto do texto da clínica. Folgado para um lembrete com endereço e
#: instrução, e curto o bastante para o link não passar do que os
#: navegadores abrem sem reclamar depois de codificado.
MAX_CARACTERES = 1000

#: Usado enquanto a clínica não escreve o seu (campo vazio). Duas versões
#: porque endereço é o único campo que costuma faltar numa clínica recém-
#: cadastrada, e "Endereço: ." no meio da mensagem parece descuido.
TEXTO_PADRAO = (
    'Olá, {primeiro_nome}! Aqui é da {clinica}. Passando para lembrar da sua '
    'consulta com {medico} em {data} ({dia_semana}), às {hora}.\n\n'
    'Endereço: {endereco}\n\n'
    'Podemos confirmar sua presença? Se precisar remarcar, é só responder '
    'esta mensagem.'
)
TEXTO_PADRAO_SEM_ENDERECO = (
    'Olá, {primeiro_nome}! Aqui é da {clinica}. Passando para lembrar da sua '
    'consulta com {medico} em {data} ({dia_semana}), às {hora}.\n\n'
    'Podemos confirmar sua presença? Se precisar remarcar, é só responder '
    'esta mensagem.'
)

#: Os dados de exemplo da prévia na tela de configuração.
EXEMPLO = {
    'primeiro_nome': 'Maria',
    'paciente': 'Maria da Silva',
    'data': '25/11/2026',
    'dia_semana': 'terça-feira',
    'hora': '14:30',
    'medico': 'Dr. João Souza',
    'tipo': 'Retorno',
}

_CAMPO = re.compile(r'\{([^{}]*)\}')
_DIAS = ['segunda-feira', 'terça-feira', 'quarta-feira', 'quinta-feira',
         'sexta-feira', 'sábado', 'domingo']
#: Partículas que ficam minúsculas no nome: "MARIA DA SILVA" vira "Maria da
#: Silva", e não "Maria Da Silva". O nome é gravado em caixa alta
#: (`patients.naming`), e "Olá, MARIA" numa mensagem pessoal soa como grito.
_PARTICULAS = {'da', 'das', 'de', 'do', 'dos', 'e'}


class SemTelefone(Exception):
    """Nenhum contato vigente do paciente tem um celular utilizável."""


def campos_desconhecidos(texto):
    """Os `{campos}` do texto que não estão em `CAMPOS`, sem repetição."""
    vistos = []
    for nome in _CAMPO.findall(texto or ''):
        if nome not in CAMPOS and nome not in vistos:
            vistos.append(nome)
    return vistos


def preencher(texto, valores):
    """Troca cada `{campo}` conhecido pelo valor; o resto fica como está."""
    return _CAMPO.sub(
        lambda m: valores.get(m.group(1), m.group(0)) if m.group(1) in CAMPOS else m.group(0),
        texto,
    )


def nome_proprio(nome):
    """'MARIA DA SILVA' → 'Maria da Silva'."""
    palavras = (nome or '').split()
    return ' '.join(
        p.lower() if i and p.lower() in _PARTICULAS else p[:1].upper() + p[1:].lower()
        for i, p in enumerate(palavras)
    )


def normalizar_telefone(telefone):
    """O número no formato do `wa.me` (só dígitos, com o país), ou `None`.

    Número brasileiro chega de todo jeito — "(11) 98765-4321", "011 9876…",
    "+55 11 …". Com DDD e sem país (10 ou 11 dígitos) ganha o 55; com o 55
    na frente (12 ou 13) fica; com "+" de outro país, vale como veio. O que
    não fecha nessas contas devolve `None`, e a tela diz que o telefone não
    serve, em vez de abrir uma conversa com um número que não existe.
    """
    bruto = (telefone or '').strip()
    digitos = ''.join(c for c in bruto if c.isdigit())
    if not digitos:
        return None
    if bruto.startswith('+'):
        return digitos if 8 <= len(digitos) <= 15 else None
    digitos = digitos.lstrip('0')
    if digitos.startswith('55') and len(digitos) in (12, 13):
        return digitos
    if len(digitos) in (10, 11):
        return '55' + digitos
    return None


def _dados_da_clinica(tenant):
    from .services import _contato_e_endereco_da_clinica

    telefone, endereco, _mapa = _contato_e_endereco_da_clinica(tenant)
    return {
        'clinica': tenant.trade_name or tenant.legal_name or 'clínica',
        'endereco': endereco,
        'telefone_clinica': telefone,
    }


def padrao_da_clinica(tenant):
    """O texto padrão que vale para esta clínica (com ou sem endereço)."""
    return TEXTO_PADRAO if _dados_da_clinica(tenant)['endereco'] else TEXTO_PADRAO_SEM_ENDERECO


def texto_da_clinica(tenant, endereco=''):
    """O texto que a clínica escreveu, ou o padrão do sistema."""
    from .models import MessagingSettings

    proprio = (
        MessagingSettings.objects.filter(tenant_id=tenant.id)
        .values_list('whatsapp_texto', flat=True).first()
    )
    if proprio and proprio.strip():
        return proprio
    return TEXTO_PADRAO if endereco else TEXTO_PADRAO_SEM_ENDERECO


def mensagem(appointment):
    """O texto pronto para o horário, com os dados de agora."""
    tenant = appointment.tenant
    clinica = _dados_da_clinica(tenant)
    quando = timezone.localtime(appointment.starts_at)
    medico = appointment.physician_membership.user
    valores = {
        'primeiro_nome': nome_proprio((appointment.patient.full_name or '').split(' ')[0]),
        'paciente': nome_proprio(appointment.patient.full_name),
        'data': quando.strftime('%d/%m/%Y'),
        'dia_semana': _DIAS[quando.weekday()],
        'hora': quando.strftime('%H:%M'),
        'medico': medico.get_full_name() or medico.email,
        'tipo': appointment.get_type_display(),
        **clinica,
    }
    return preencher(texto_da_clinica(tenant, clinica['endereco']), valores)


def exemplo(tenant, texto=None):
    """A prévia da tela de configuração: o texto com dados fictícios do
    paciente e os dados reais da clínica, que é o que muda de uma para outra."""
    clinica = _dados_da_clinica(tenant)
    if texto is None:
        texto = texto_da_clinica(tenant, clinica['endereco'])
    return preencher(texto, {**EXEMPLO, **clinica})


def telefone_do_paciente(appointment):
    """O primeiro celular utilizável, com o contato do próprio paciente na
    frente — a mesma escolha da confirmação por SMS
    (`services.confirmation_contacts`), para os dois botões do mesmo
    horário não apontarem para pessoas diferentes."""
    from .models import DeliveryChannel
    from .services import confirmation_contacts

    for contato in confirmation_contacts(appointment, DeliveryChannel.SMS):
        numero = normalizar_telefone(contato.phone)
        if numero:
            return numero
    raise SemTelefone


def link(appointment):
    """O endereço `wa.me` com o número do paciente e a mensagem escrita."""
    numero = telefone_do_paciente(appointment)
    return f'https://wa.me/{numero}?text={quote(mensagem(appointment), safe="")}'
