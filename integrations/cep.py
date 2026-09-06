import re

import httpx

VIACEP_TIMEOUT_SECONDS = 3.0


def lookup_cep(cep):
    """Looks up a Brazilian postal code via ViaCEP.

    Sends only the CEP itself (no patient data). Any failure — invalid
    format, timeout, HTTP error, unknown CEP — returns None so the caller
    can fall back to manual entry; it never raises. `complement` is never
    returned, since ViaCEP's suggestion must never overwrite what the user
    typed there.
    """
    digits = re.sub(r'\D', '', cep or '')
    if len(digits) != 8:
        return None
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
        'source': 'viacep',
    }
