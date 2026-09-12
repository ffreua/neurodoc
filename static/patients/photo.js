/* Fotografia do paciente: prévia do arquivo escolhido e captura pela câmera.
 *
 * Duas origens, um destino visível: a prévia. Quem envia um retrato precisa
 * ver o que está enviando antes de gravar — trocar a foto de um paciente
 * pela de outro é o erro que este bloco existe para evitar, e ele não é
 * detectável depois, porque as duas imagens são válidas.
 *
 * A captura vai para um campo oculto como data URL, e não para um
 * `<input type="file">`: o navegador esvazia todo campo de arquivo quando a
 * página volta, e o cadastro volta com frequência (aviso de duplicidade,
 * erro de campo). O oculto sobrevive; o de arquivo, não.
 */
(function () {
    'use strict';

    var fileInput = document.getElementById('photo');
    var captureInput = document.getElementById('nd-photo-capture');
    var preview = document.getElementById('nd-photo-preview');
    var empty = document.getElementById('nd-photo-empty');
    if (!fileInput || !captureInput || !preview) {
        return;
    }

    var openButton = document.getElementById('nd-photo-camera-open');
    var closeButton = document.getElementById('nd-photo-camera-close');
    var shootButton = document.getElementById('nd-photo-shoot');
    var panel = document.getElementById('nd-photo-camera');
    var video = document.getElementById('nd-photo-video');
    var canvas = document.getElementById('nd-photo-canvas');
    var errorBox = document.getElementById('nd-photo-camera-error');
    var stream = null;

    /* Largura máxima da captura. Uma webcam de 1080p gera um JPEG de mais de
     * 1 MB, e o servidor recusa acima de 2 MB: reduzir aqui evita que a
     * pessoa tire a foto, veja a prévia e só então receba "a imagem passa de
     * 2 MB" — com a câmera já fechada. Retrato de identificação não ganha
     * nada acima disto. */
    var MAX_EDGE = 900;

    function showPreview(src) {
        preview.src = src;
        preview.classList.remove('d-none');
        if (empty) {
            empty.classList.add('d-none');
        }
    }

    function showError(message) {
        if (!errorBox) {
            return;
        }
        errorBox.textContent = message;
        errorBox.classList.remove('d-none');
    }

    function clearError() {
        if (errorBox) {
            errorBox.classList.add('d-none');
            errorBox.textContent = '';
        }
    }

    function stopCamera() {
        if (stream) {
            stream.getTracks().forEach(function (track) { track.stop(); });
            stream = null;
        }
        if (video) {
            video.srcObject = null;
        }
        if (panel) {
            panel.classList.add('d-none');
        }
    }

    /* Arquivo escolhido descarta a captura anterior, e vice-versa. Sem isto
     * as duas viajariam juntas e o servidor decidiria por conta própria
     * (a captura ganha) — o que estaria certo pela regra e errado para quem
     * escolheu um arquivo depois de capturar, e veria a captura ser gravada. */
    fileInput.addEventListener('change', function () {
        captureInput.value = '';
        clearError();
        var file = fileInput.files && fileInput.files[0];
        if (!file) {
            return;
        }
        var reader = new FileReader();
        reader.onload = function () { showPreview(reader.result); };
        reader.readAsDataURL(file);
    });

    if (openButton) {
        openButton.addEventListener('click', function () {
            clearError();
            /* `mediaDevices` só existe em contexto seguro — HTTPS ou
             * localhost. Em produção há HTTPS; num acesso por IP na rede da
             * clínica, não. Dizer isso é melhor do que um botão que não
             * reage, que se lê como sistema quebrado. */
            if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) {
                showError(
                    'Este navegador não libera a câmera nesta página. A câmera só funciona ' +
                    'em endereço seguro (https) ou em localhost — pelo endereço atual, use ' +
                    'o envio de arquivo.'
                );
                return;
            }
            navigator.mediaDevices.getUserMedia({ video: { facingMode: 'user' }, audio: false })
                .then(function (media) {
                    stream = media;
                    video.srcObject = media;
                    video.play();
                    panel.classList.remove('d-none');
                })
                .catch(function (error) {
                    /* Os nomes vêm da especificação e distinguem os dois
                     * casos que a pessoa resolve de formas opostas: negar a
                     * permissão se conserta no próprio navegador; não haver
                     * câmera, não. */
                    if (error && (error.name === 'NotAllowedError' || error.name === 'SecurityError')) {
                        showError(
                            'A permissão para usar a câmera foi negada. Libere o acesso à câmera ' +
                            'para este endereço nas configurações do navegador, ou envie um arquivo.'
                        );
                    } else if (error && (error.name === 'NotFoundError' || error.name === 'OverconstrainedError')) {
                        showError('Nenhuma câmera foi encontrada neste computador. Envie um arquivo.');
                    } else {
                        showError('Não foi possível abrir a câmera. Envie um arquivo.');
                    }
                });
        });
    }

    if (closeButton) {
        closeButton.addEventListener('click', stopCamera);
    }

    if (shootButton) {
        shootButton.addEventListener('click', function () {
            if (!stream || !video.videoWidth) {
                showError('A câmera ainda não está pronta. Espere a imagem aparecer e tente de novo.');
                return;
            }
            var scale = Math.min(1, MAX_EDGE / Math.max(video.videoWidth, video.videoHeight));
            canvas.width = Math.round(video.videoWidth * scale);
            canvas.height = Math.round(video.videoHeight * scale);
            canvas.getContext('2d').drawImage(video, 0, 0, canvas.width, canvas.height);
            var dataUrl = canvas.toDataURL('image/jpeg', 0.85);
            captureInput.value = dataUrl;
            fileInput.value = '';
            showPreview(dataUrl);
            stopCamera();
        });
    }

    /* Câmera aberta continua acesa — e com a luz do equipamento ligada — se
     * a pessoa navegar para outra tela sem fechá-la. */
    window.addEventListener('pagehide', stopCamera);

    /* Captura devolvida pelo servidor num re-render: a prévia precisa voltar
     * junto, senão a tela diz "sem foto" enquanto o campo oculto carrega uma. */
    if (captureInput.value) {
        showPreview(captureInput.value);
    }
}());
