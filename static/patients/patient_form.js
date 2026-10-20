/*
 * Cadastro de paciente: máscaras, conferência de CPF, busca de CEP e o
 * bloco do plano de saúde.
 *
 * Nada aqui substitui a validação do servidor — o formulário é revalidado
 * por inteiro em `patients/forms.py`. O que roda no navegador existe para
 * a secretaria perceber o erro enquanto ainda está com o documento na mão,
 * em vez de descobrir depois de salvar.
 */
(function () {
    'use strict';

    var form = document.getElementById('patient-form');
    if (!form) return;

    function el(name) {
        return form.querySelector('[name="' + name + '"]');
    }

    function onlyDigits(value) {
        return (value || '').replace(/\D/g, '');
    }

    /* ------------------------------------------------------------ CPF */

    function isValidCpf(digits) {
        if (digits.length !== 11) return false;
        if (/^(\d)\1{10}$/.test(digits)) return false;
        function digit(slice, startWeight) {
            var total = 0;
            for (var i = 0; i < slice.length; i++) {
                total += parseInt(slice[i], 10) * (startWeight - i);
            }
            var remainder = total % 11;
            return remainder < 2 ? 0 : 11 - remainder;
        }
        var d1 = digit(digits.slice(0, 9), 10);
        var d2 = digit(digits.slice(0, 9) + d1, 11);
        return digits.slice(9) === '' + d1 + d2;
    }

    function maskCpf(digits) {
        var out = digits.slice(0, 11);
        if (out.length > 9) return out.replace(/(\d{3})(\d{3})(\d{3})(\d+)/, '$1.$2.$3-$4');
        if (out.length > 6) return out.replace(/(\d{3})(\d{3})(\d+)/, '$1.$2.$3');
        if (out.length > 3) return out.replace(/(\d{3})(\d+)/, '$1.$2');
        return out;
    }

    var cpf = el('cpf');
    if (cpf) {
        var cpfFeedback = document.createElement('div');
        /* Sem `d-block` no estado de repouso, e a visibilidade é controlada
         * por essa classe e não pelo atributo `hidden`.
         *
         * O motivo importa: `.invalid-feedback` nasce com `display:none`, e
         * `.d-block` do Bootstrap é `display:block !important` — o
         * `!important` vence o `hidden` do navegador. Com as duas classes
         * juntas, `feedback.hidden = true` não escondia nada, e a frase
         * "CPF inválido" ficava na tela junto do campo marcado como
         * válido. Era CPF certo com aviso de errado do lado. */
        cpfFeedback.className = 'invalid-feedback fs-11';
        cpf.insertAdjacentElement('afterend', cpfFeedback);

        function clearCpfFeedback() {
            cpf.classList.remove('is-invalid', 'is-valid');
            cpfFeedback.classList.remove('d-block');
            cpfFeedback.textContent = '';
        }

        cpf.addEventListener('input', function () {
            var caretAtEnd = cpf.selectionStart === cpf.value.length;
            cpf.value = maskCpf(onlyDigits(cpf.value));
            if (caretAtEnd) cpf.setSelectionRange(cpf.value.length, cpf.value.length);
            clearCpfFeedback();
        });

        cpf.addEventListener('blur', function () {
            var digits = onlyDigits(cpf.value);
            if (!digits) {
                clearCpfFeedback();
                return;
            }
            var ok = isValidCpf(digits);
            cpf.classList.toggle('is-invalid', !ok);
            cpf.classList.toggle('is-valid', ok);
            if (ok) {
                cpfFeedback.classList.remove('d-block');
                cpfFeedback.textContent = '';
                return;
            }
            cpfFeedback.textContent = digits.length !== 11
                ? 'O CPF tem 11 dígitos. Informe todos.'
                : 'CPF inválido: os dígitos verificadores não conferem.';
            cpfFeedback.classList.add('d-block');
        });
    }

    /* ------------------------------------------------------------ CEP */

    var cep = el('postal_code');
    var status = document.getElementById('cep-status');
    var lookupUrl = form.getAttribute('data-cep-url');
    var lastLookup = null;

    function setStatus(text, tone) {
        if (!status) return;
        status.textContent = text || '';
        status.className = 'fs-11 ' + (tone || 'text-muted');
    }

    /* O que o CEP pode reescrever é o que ninguém digitou NESTA tela.
     * A regra antiga era "só preenche campo vazio", para não apagar o
     * logradouro digitado antes do CEP no cadastro novo — e na edição isso
     * a impedia de funcionar: o paciente que mudou de casa chega com a rua
     * antiga preenchida, e o CEP novo trocava o município deixando a rua, o
     * bairro e o número da casa anterior. Valor que veio do banco não é
     * escolha de quem está na tela; valor digitado aqui é. */
    var ENDERECO = ['street', 'number', 'complement', 'district'];
    var digitado = {};
    ENDERECO.forEach(function (name) {
        var field = el(name);
        if (field) field.addEventListener('input', function () { digitado[name] = true; });
    });
    var cepInicial = cep ? onlyDigits(cep.value) : '';

    function fill(name, value, force) {
        var field = el(name);
        if (!field || !value) return;
        if (!force && field.value.trim() && digitado[name]) return;
        field.value = value;
    }

    function limparDoEnderecoAnterior(name) {
        /* Número e complemento não vêm do CEP: com a rua trocada, os da
         * casa antiga ficariam valendo para a nova sem ninguém perceber. */
        var field = el(name);
        if (field && !digitado[name]) field.value = '';
    }

    function applyAddress(address, cepMudou) {
        fill('city', address.city, true);
        if (cepMudou) {
            /* Rua e bairro antigos saem mesmo quando o CEP novo não os
             * informa (CEP geral de cidade) — senão ficaria a rua velha. */
            ['street', 'district'].forEach(limparDoEnderecoAnterior);
            ['number', 'complement'].forEach(limparDoEnderecoAnterior);
        }
        fill('street', address.street, false);
        fill('district', address.district, false);
        var state = el('state');
        if (state && address.state) state.value = address.state;

        if (address.street) {
            setStatus(
                'Endereço encontrado (' + address.city + '/' + address.state + ').' +
                    (cepMudou ? ' Informe o número e o complemento do endereço novo.' : ''),
                'text-success'
            );
        } else if (address.by_street === false) {
            setStatus(
                'CEP geral de ' + address.city + '/' + address.state + ' — informe o logradouro.',
                'text-muted'
            );
        } else {
            setStatus(
                address.city + '/' + address.state + ' preenchidos — informe o logradouro.',
                'text-muted'
            );
        }
    }

    function lookupCep() {
        var digits = onlyDigits(cep.value);
        if (digits.length !== 8 || digits === lastLookup) return;
        lastLookup = digits;
        setStatus('Buscando endereço…', 'text-muted');
        fetch(lookupUrl + '?cep=' + digits, {
            headers: { 'X-Requested-With': 'XMLHttpRequest' },
            credentials: 'same-origin',
        })
            .then(function (response) {
                if (!response.ok) throw new Error('http ' + response.status);
                return response.json();
            })
            .then(function (data) {
                if (data.found) {
                    /* Reabrir a ficha e redigitar o MESMO CEP não é mudança
                     * de endereço: não apaga número nem complemento. */
                    applyAddress(data.address, Boolean(cepInicial) && digits !== cepInicial);
                } else {
                    setStatus('CEP não encontrado — preencha o endereço à mão.', 'text-danger');
                }
            })
            .catch(function () {
                setStatus('Não foi possível consultar o CEP agora — preencha à mão.', 'text-danger');
            });
    }

    if (cep && lookupUrl) {
        cep.addEventListener('input', function () {
            var digits = onlyDigits(cep.value).slice(0, 8);
            cep.value = digits.length > 5 ? digits.replace(/(\d{5})(\d+)/, '$1-$2') : digits;
            if (digits.length === 8) lookupCep();
        });
        cep.addEventListener('blur', lookupCep);
    }

    /* ------------------------------------------------------ plano de saúde */

    var category = el('payment_category');
    var planBlock = document.getElementById('plan-block');
    var planSelect = el('coverage_plan');
    var planKind = document.getElementById('plan-kind');

    function showPlanKind() {
        if (!planSelect || !planKind) return;
        var option = planSelect.options[planSelect.selectedIndex];
        var kind = option ? option.getAttribute('data-kind') : '';
        planKind.textContent = kind ? 'Tipo: ' + kind : '';
        planKind.hidden = !kind;
    }

    function syncPlanBlock() {
        if (!category || !planBlock) return;
        var usesPlan = category.value === 'plan';
        planBlock.hidden = !usesPlan;
        /* Campo obrigatório escondido bloquearia o envio sem explicar por quê. */
        planBlock.querySelectorAll('input, select').forEach(function (field) {
            field.disabled = false;
        });
        if (usesPlan) showPlanKind();
    }

    if (category) {
        category.addEventListener('change', syncPlanBlock);
        syncPlanBlock();
    }
    if (planSelect) {
        planSelect.addEventListener('change', showPlanKind);
    }
})();
