/* As listas da solicitação de cirurgia como linhas, cada uma com a sua
 * quantidade (caixa de setas) e o botão de tirar.
 *
 * A caixa de texto (`textarea[data-nd-linhas]`) continua sendo o campo que
 * vai no envio, no formato que `modelos/estrutura.py` lê — o script só a
 * esconde e a reescreve a cada mudança. Sem o script, ou se ele falhar, a
 * caixa aparece e funciona como antes: uma linha por item.
 *
 * Três formas de linha, a mesma da leitura no servidor:
 *   procedimento  "30715016 Artrodese da coluna x2"  (quantidade no fim)
 *   material      "2 x Parafusos pediculares"        (quantidade no começo)
 *   lista         "Caixa de laminectomia"            (sem quantidade)
 *
 * A busca na TUSS (`modelos.js`) insere na caixa de texto e avisa com o
 * evento `input`; as linhas são refeitas a partir dela. Nunca `innerHTML`:
 * a descrição vai por `value`.
 */
(function () {
    'use strict';

    var QTD_NO_FIM = /^(.*?)\s+[xX×]\s*(\d{1,3})$/;
    var QTD_NO_INICIO = /^(\d{1,3})\s*[xX×]\s+(.+)$/;

    function ler(texto, forma) {
        return texto.split('\n').map(function (l) { return l.trim(); }).filter(Boolean).map(function (l) {
            var achado;
            if (forma === 'procedimento' && (achado = QTD_NO_FIM.exec(l))) {
                return { texto: achado[1].trim(), quantidade: parseInt(achado[2], 10) || 1 };
            }
            if (forma === 'material' && (achado = QTD_NO_INICIO.exec(l))) {
                return { texto: achado[2].trim(), quantidade: parseInt(achado[1], 10) || 1 };
            }
            return { texto: l, quantidade: 1 };
        });
    }

    function escrever(itens, forma) {
        return itens.filter(function (i) { return i.texto.trim(); }).map(function (i) {
            var texto = i.texto.trim();
            var q = Math.max(1, Math.min(999, parseInt(i.quantidade, 10) || 1));
            if (forma === 'procedimento') { return q > 1 ? texto + ' x' + q : texto; }
            if (forma === 'material') { return q + ' x ' + texto; }
            return texto;
        }).join('\n');
    }

    function ligar(caixa) {
        var forma = caixa.getAttribute('data-nd-linhas');
        var rotulo = (document.querySelector('label[for="' + caixa.id + '"]') || {}).textContent || 'item';
        rotulo = rotulo.replace('*', '').trim();
        var painel = document.createElement('div');
        painel.className = 'nd-linhas';
        painel.setAttribute('data-nd-linhas-de', caixa.id);
        var corpo = document.createElement('div');
        var incluir = document.createElement('button');
        incluir.type = 'button';
        incluir.className = 'btn btn-sm btn-light-primary mt-1';
        incluir.textContent = '+ Incluir linha';
        painel.appendChild(corpo);
        painel.appendChild(incluir);
        caixa.insertAdjacentElement('afterend', painel);
        caixa.classList.add('d-none');

        var itens = ler(caixa.value, forma);
        var sincronizando = false;

        function gravar() {
            sincronizando = true;
            caixa.value = escrever(itens, forma);
            caixa.dispatchEvent(new Event('change', { bubbles: true }));
            sincronizando = false;
        }

        function linha(item, indice) {
            var div = document.createElement('div');
            div.className = 'd-flex align-items-center gap-2 mb-1';
            if (forma !== 'lista') {
                var qtd = document.createElement('input');
                qtd.type = 'number';
                qtd.min = '1';
                qtd.max = '999';
                qtd.step = '1';
                qtd.value = item.quantidade;
                qtd.className = 'form-control form-control-sm';
                qtd.style.width = '5.5rem';
                qtd.setAttribute('aria-label', 'Quantidade — ' + rotulo + ', linha ' + (indice + 1));
                qtd.addEventListener('input', function () { item.quantidade = qtd.value; gravar(); });
                div.appendChild(qtd);
            }
            var texto = document.createElement('input');
            texto.type = 'text';
            texto.value = item.texto;
            texto.className = 'form-control form-control-sm';
            texto.setAttribute('aria-label', rotulo + ', linha ' + (indice + 1));
            texto.addEventListener('input', function () { item.texto = texto.value; gravar(); });
            div.appendChild(texto);
            var tirar = document.createElement('button');
            tirar.type = 'button';
            tirar.className = 'btn btn-sm btn-light-danger';
            tirar.textContent = '×';
            tirar.title = 'Tirar esta linha';
            tirar.setAttribute('aria-label', 'Tirar a linha ' + (indice + 1) + ' de ' + rotulo);
            tirar.addEventListener('click', function () {
                itens.splice(indice, 1);
                gravar();
                desenhar();
            });
            div.appendChild(tirar);
            return div;
        }

        function desenhar() {
            while (corpo.firstChild) { corpo.removeChild(corpo.firstChild); }
            itens.forEach(function (item, indice) { corpo.appendChild(linha(item, indice)); });
        }

        incluir.addEventListener('click', function () {
            itens.push({ texto: '', quantidade: 1 });
            desenhar();
            var campos = corpo.querySelectorAll('input[type="text"]');
            if (campos.length) { campos[campos.length - 1].focus(); }
        });

        /* A busca na TUSS escreve direto na caixa de texto. */
        caixa.addEventListener('input', function () {
            if (sincronizando) { return; }
            itens = ler(caixa.value, forma);
            desenhar();
        });

        desenhar();
    }

    document.querySelectorAll('textarea[data-nd-linhas]').forEach(ligar);
})();
