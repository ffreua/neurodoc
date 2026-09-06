import re

import httpx

VIACEP_TIMEOUT_SECONDS = 3.0


def _lookup_viacep(digits):
    """Logradouro e bairro do CEP, via ViaCEP. None em qualquer falha.

    Envia apenas o CEP — nunca qualquer dado do paciente. `complemento`
    nunca é devolvido: a sugestão do serviço não pode sobrescrever o que a
    pessoa digitou ali.
    """
    try:
        response = httpx.get(
            f'https://viacep.com.br/ws/{digits}/json/', timeout=VIACEP_TIMEOUT_SECONDS,
        )
        response.raise_for_status()
        data = response.json()
    except (httpx.HTTPError, ValueError):
        return None
    if data.get('erro'):
        return None
    return {
        'street': data.get('logradouro') or '',
        'district': data.get('bairro') or '',
        'city': data.get('localidade') or '',
        'state': data.get('uf') or '',
    }


def lookup_cep(cep):
    """Endereço de um CEP brasileiro, resolvendo primeiro pela base local.

    A base local de faixas dos Correios (`catalogs.PostalCodeRange`) é a
    fonte de município/UF: ela responde sempre, sem depender de rede, e é o
    que garante que o cadastro continue funcionando com a internet fora.
    Esse conjunto de dados é por faixa municipal e **não contém logradouro
    nem bairro**; para esses dois campos, e só para eles, o ViaCEP é
    consultado como complemento — se estiver indisponível, o restante do
    endereço já foi preenchido e o logradouro é digitado à mão.

    Nunca levanta exceção: devolve None quando o CEP não existe em lugar
    nenhum, para que a tela caia no preenchimento manual.
    """
    from catalogs.postal_codes import lookup_locality

    digits = re.sub(r'\D', '', cep or '')
    if len(digits) != 8:
        return None

    local = lookup_locality(digits)
    remote = _lookup_viacep(digits) if (local is None or local['by_street']) else None

    if local is None and remote is None:
        return None

    if local is None:
        # CEP fora das faixas conhecidas, mas o ViaCEP reconheceu: aceita o
        # que ele devolveu em vez de recusar um endereço real.
        return {
            'street': remote['street'],
            'district': remote['district'],
            'city': remote['city'],
            'state': remote['state'],
            'by_street': bool(remote['street']),
            'source': 'viacep',
        }

    return {
        'street': (remote or {}).get('street', ''),
        'district': (remote or {}).get('district', ''),
        'city': local['city'],
        'state': local['state'],
        'ibge_code': local['ibge_code'],
        'by_street': local['by_street'],
        'source': 'correios-local' if remote is None else 'correios-local+viacep',
    }
