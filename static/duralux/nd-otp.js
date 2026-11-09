/*
 * O código do segundo fator em casas, uma por dígito (1.41).
 *
 * Um campo só continua sendo o campo: o `<input>` original fica na página,
 * com o mesmo nome, por cima das casas e transparente. As casas só
 * **desenham** o que está nele. A alternativa comum — seis campos de um
 * dígito — quebra três coisas que aqui importam:
 *
 * - o gerenciador de senhas e o "código de uso único" do celular preenchem
 *   **um** campo `autocomplete="one-time-code"`; com seis, preenchem o
 *   primeiro e param;
 * - colar "123 456" vira um dígito por campo só com código para redistribuir,
 *   e o espaço do meio vira um dígito errado;
 * - o leitor de tela anuncia "campo de texto" seis vezes, sem rótulo em
 *   cinco delas.
 *
 * Sem JavaScript, nada muda: o campo aparece como sempre apareceu, e o
 * servidor recebe o mesmo `code`. Por isso as telas não precisam de outro
 * formulário — basta o atributo `data-nd-otp="6"` no campo.
 *
 * `data-nd-otp-recuperacao` acrescenta "Usar um código de recuperação": as
 * telas de entrar e de reconfirmar aceitam também o código de recuperação,
 * que não cabe em seis casas numéricas. A troca devolve o campo comum, sem
 * filtro de dígitos.
 *
 * `data-nd-otp-compacto` é a versão pequena, para o campo que mora numa
 * linha de botões (o "Resetar MFA" da equipe).
 */
(function () {
    'use strict';

    function montar(campo) {
        if (campo.getAttribute('data-nd-otp-pronto')) return;
        campo.setAttribute('data-nd-otp-pronto', '1');

        var casasPedidas = parseInt(campo.getAttribute('data-nd-otp'), 10) || 6;
        var maximoOriginal = campo.getAttribute('maxlength');
        var livre = false;

        var raiz = document.createElement('div');
        raiz.className = 'nd-otp' + (campo.hasAttribute('data-nd-otp-compacto') ? ' nd-otp--compacto' : '');
        if (campo.classList.contains('is-invalid')) raiz.classList.add('is-invalid');
        campo.parentNode.insertBefore(raiz, campo);

        var fila = document.createElement('div');
        fila.className = 'nd-otp__casas';
        fila.setAttribute('aria-hidden', 'true');
        var casas = [];
        for (var i = 0; i < casasPedidas; i++) {
            var casa = document.createElement('span');
            casa.className = 'nd-otp__casa';
            fila.appendChild(casa);
            casas.push(casa);
        }
        raiz.appendChild(fila);
        raiz.appendChild(campo);

        campo.classList.add('nd-otp__campo');
        campo.setAttribute('maxlength', String(casasPedidas));
        campo.setAttribute('inputmode', 'numeric');
        campo.setAttribute('autocomplete', 'one-time-code');
        campo.setAttribute('spellcheck', 'false');

        function soDigitos() {
            if (livre) return;
            var limpo = campo.value.replace(/\D/g, '').slice(0, casasPedidas);
            if (limpo !== campo.value) campo.value = limpo;
        }

        /* O cursor mora sempre no fim: as casas não têm como mostrar edição
         * no meio, e apagar e redigitar é o gesto que todo mundo faz. */
        function cursorNoFim() {
            try {
                var fim = campo.value.length;
                campo.setSelectionRange(fim, fim);
            } catch (erro) { /* tipo de campo sem seleção */ }
        }

        function desenhar() {
            if (livre) return;
            var valor = campo.value;
            var focado = document.activeElement === campo;
            var ativa = Math.min(valor.length, casasPedidas - 1);
            casas.forEach(function (c, indice) {
                c.textContent = valor.charAt(indice) || '';
                c.classList.toggle('is-preenchida', indice < valor.length);
                c.classList.toggle('is-ativa', focado && indice === ativa);
            });
        }

        campo.addEventListener('input', function () { soDigitos(); cursorNoFim(); desenhar(); });
        campo.addEventListener('focus', function () { raiz.classList.add('is-focada'); cursorNoFim(); desenhar(); });
        campo.addEventListener('blur', function () { raiz.classList.remove('is-focada'); desenhar(); });
        campo.addEventListener('click', cursorNoFim);
        campo.addEventListener('keyup', function (evento) {
            if (/^(Arrow|Home|End)/.test(evento.key)) cursorNoFim();
        });

        /* Colar antes do `maxlength`: "123 456" tem sete caracteres, e o
         * navegador cortaria o último dígito antes de o filtro tirar o
         * espaço. */
        campo.addEventListener('paste', function (evento) {
            if (livre) return;
            var dados = evento.clipboardData || window.clipboardData;
            var colado = dados ? (dados.getData('text') || '') : '';
            var limpo = colado.replace(/\D/g, '').slice(0, casasPedidas);
            if (!limpo) return;
            evento.preventDefault();
            campo.value = limpo;
            cursorNoFim();
            desenhar();
        });

        soDigitos();
        desenhar();

        if (campo.hasAttribute('data-nd-otp-recuperacao')) {
            var troca = document.createElement('button');
            troca.type = 'button';
            troca.className = 'btn btn-link btn-sm p-0 mt-2 nd-otp__troca';
            troca.textContent = 'Usar um código de recuperação';
            raiz.parentNode.insertBefore(troca, raiz.nextSibling);
            troca.addEventListener('click', function () {
                livre = !livre;
                raiz.classList.toggle('nd-otp--livre', livre);
                if (livre) {
                    if (maximoOriginal) campo.setAttribute('maxlength', maximoOriginal);
                    else campo.removeAttribute('maxlength');
                    campo.setAttribute('inputmode', 'text');
                    campo.setAttribute('autocomplete', 'off');
                    troca.textContent = 'Usar o código do aplicativo';
                } else {
                    campo.setAttribute('maxlength', String(casasPedidas));
                    campo.setAttribute('inputmode', 'numeric');
                    campo.setAttribute('autocomplete', 'one-time-code');
                    soDigitos();
                    troca.textContent = 'Usar um código de recuperação';
                }
                desenhar();
                campo.focus();
            });
        }
    }

    function iniciar() {
        Array.prototype.forEach.call(document.querySelectorAll('input[data-nd-otp]'), montar);
    }

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', iniciar);
    } else {
        iniciar();
    }
})();
