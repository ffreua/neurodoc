/*
 * Agenda: clicar num horário livre marca; clicar num marcado abre as ações.
 *
 * A grade tem centenas de células, então existem dois modais para toda ela e
 * o botão clicado diz de qual horário se trata. Declarar um modal por célula
 * encheria a página à toa.
 *
 * O que roda aqui é conveniência de tela. Quem valida disponibilidade,
 * duração e sobreposição é o servidor (`scheduling.services.reserve_from_grid`
 * e a ExclusionConstraint do banco) — inclusive quando duas secretárias
 * clicam no mesmo horário ao mesmo tempo.
 */
(function () {
    'use strict';

    var bookModal = document.getElementById('book-modal');
    var slotModal = document.getElementById('slot-modal');
    if (!bookModal && !slotModal) return;

    /* ------------------------------------------------- marcar num livre */

    if (bookModal) {
        var bookStartsAt = document.getElementById('book-starts-at');
        var bookDate = document.getElementById('book-date');
        var bookWhen = document.getElementById('book-when');
        var bookType = document.getElementById('book-type');
        var bookHint = document.getElementById('book-duration-hint');
        var bookPatientId = document.getElementById('book-patient-id');
        var bookSearch = document.getElementById('book-search');
        var bookChosen = document.getElementById('book-chosen');
        var bookNewName = document.getElementById('book-new-name');

        var bookForm = document.getElementById('book-form');

        function describeDuration() {
            var option = bookType.options[bookType.selectedIndex];
            if (!option || !option.value) {
                /* Sem tipo escolhido não há duração, e portanto não há fim de
                 * atendimento a anunciar. O aviso da configuração já está na
                 * tela; repetir aqui só encheria o espaço. */
                bookHint.textContent = '';
                return;
            }
            bookHint.textContent = 'O fim é calculado da duração deste tipo — ' +
                option.textContent.replace(/^.*—\s*/, '') + '.';
        }

        bookType.addEventListener('change', function () {
            bookType.classList.remove('is-invalid');
            describeDuration();
        });

        /* Envio bloqueado deixa o botão utilizável de novo.
         *
         * `data-nd-busy` (app.js) desabilita o botão e lhe põe um spinner no
         * `submit`, contando que a página vá embora em seguida. Quando o
         * envio é barrado aqui, a página fica — e o botão ficaria desabilitado
         * para sempre, o que é pior do que o campo vazio que se quis impedir.
         *
         * O desfazer vai num `setTimeout` porque os dois ouvintes de `submit`
         * rodam na ordem em que foram registrados, e essa ordem depende de
         * qual script carregou primeiro: desfazer de imediato pode ser
         * refeito logo depois. Ao fim da fila, ambos já rodaram. */
        function releaseBusy(form) {
            window.setTimeout(function () {
                form.querySelectorAll('[data-nd-busy]').forEach(function (button) {
                    button.disabled = false;
                    delete button.dataset.ndBusyDone;
                    var spinner = button.querySelector('.spinner-border');
                    if (spinner) spinner.remove();
                });
                /* O campo oculto que `app.js` cria para preservar o valor do
                 * botão clicado também tem de sair: o envio não aconteceu, e
                 * deixá-lo para trás mandaria a ação de agora junto com a do
                 * próximo envio. */
                form.querySelectorAll('[data-nd-busy-carrier]').forEach(function (field) {
                    field.remove();
                });
            }, 0);
        }

        /* O formulário é `novalidate`, então o navegador não barra o campo
         * vazio: sem isto o envio sai, o servidor recusa e o aviso aparece
         * como mensagem da página — com o modal já fechado, longe do campo
         * que faltou preencher. O erro tem de aparecer onde se digita. */
        if (bookForm) {
            bookForm.addEventListener('submit', function (event) {
                if (bookType.value) return;
                event.preventDefault();
                releaseBusy(bookForm);
                bookType.classList.add('is-invalid');
                bookHint.textContent = 'Escolha o tipo de atendimento para calcular o fim.';
                bookHint.className = 'form-text fs-11 text-danger';
                bookType.focus();
            });
        }

        document.addEventListener('click', function (event) {
            var cell = event.target.closest('[data-nd-book]');
            if (!cell) return;
            bookStartsAt.value = cell.getAttribute('data-nd-iso');
            bookDate.value = cell.getAttribute('data-nd-start').slice(0, 10);
            bookWhen.textContent = cell.getAttribute('data-nd-when');
            /* Cada abertura começa limpa: reaproveitar o paciente escolhido na
             * abertura anterior marcaria a pessoa errada no horário novo. */
            bookPatientId.value = '';
            bookSearch.value = '';
            bookNewName.value = '';
            document.getElementById('book-new-phone').value = '';
            document.getElementById('book-note').value = '';
            bookChosen.textContent = '';
            bookChosen.className = 'form-text fs-11';
            /* O erro da abertura anterior não pode sobreviver a esta: já foi
             * corrigido ou abandonado, e reaparecer num horário novo faria
             * parecer que o campo continua errado. */
            bookType.classList.remove('is-invalid');
            bookHint.className = 'form-text fs-11';
            describeDuration();
            window.NeuroDoc.openModal(bookModal);
            window.setTimeout(function () { bookSearch.focus(); }, 60);
        });
    }

    /* --------------------------------------- ações num horário marcado */

    if (slotModal) {
        var slotTitle = document.getElementById('slot-modal-title');
        var slotWhen = document.getElementById('slot-when');
        var slotType = document.getElementById('slot-type');
        var slotStatus = document.getElementById('slot-status');
        var slotPreliminary = document.getElementById('slot-preliminary');
        var openPatient = document.getElementById('slot-open-patient');
        var checkinForm = document.getElementById('slot-checkin-form');
        var confirmForm = document.getElementById('slot-confirm-form');
        var rescheduleLink = document.getElementById('slot-reschedule');
        var declaracaoLink = document.getElementById('slot-declaracao');
        var changePanel = document.getElementById('slot-change-panel');
        var cancelPanel = document.getElementById('slot-cancel-panel');
        var changeForm = document.getElementById('slot-change-form');
        var cancelForm = document.getElementById('slot-cancel-form');
        var changeChosen = document.getElementById('change-chosen');
        var changePatientId = document.getElementById('change-patient-id');
        var changeSearch = document.getElementById('change-search');
        var smsForm = document.getElementById('slot-sms-form');
        var emailForm = document.getElementById('slot-email-form');
        var contactHint = document.getElementById('slot-contact-hint');

        var STATUS_TONE = {
            scheduled: 'bg-soft-primary text-primary',
            confirmed: 'bg-soft-info text-info',
            checked_in: 'bg-soft-warning text-warning',
            in_progress: 'bg-soft-warning text-warning',
            completed: 'bg-soft-success text-success',
            no_show: 'bg-soft-danger text-danger'
        };

        document.addEventListener('click', function (event) {
            var cell = event.target.closest('[data-nd-appointment]');
            if (!cell) return;
            var id = cell.getAttribute('data-nd-appointment');
            slotTitle.textContent = cell.getAttribute('data-nd-patient');
            slotWhen.textContent = cell.getAttribute('data-nd-when') + ' até ' +
                cell.getAttribute('data-nd-until');
            slotType.textContent = cell.getAttribute('data-nd-type');
            slotStatus.textContent = cell.getAttribute('data-nd-status-label');
            slotStatus.className = 'badge ' +
                (STATUS_TONE[cell.getAttribute('data-status')] || 'bg-gray-200 text-dark');
            slotPreliminary.hidden = cell.getAttribute('data-nd-preliminary') !== '1';

            openPatient.href = '/app/patients/' + cell.getAttribute('data-nd-patient-id') + '/';
            checkinForm.action = '/app/scheduling/' + id + '/check-in/';
            confirmForm.action = '/app/scheduling/' + id + '/confirm/';
            cancelForm.action = '/app/scheduling/' + id + '/cancel/';
            changeForm.action = '/app/scheduling/' + id + '/trocar-paciente/';
            rescheduleLink.href = '/app/scheduling/' + id + '/remarcar/';
            if (declaracaoLink) {
                declaracaoLink.href = '/app/scheduling/' + id + '/declaracao/';
            }
            if (smsForm) smsForm.action = '/app/scheduling/' + id + '/confirmar-por/sms/';
            if (emailForm) emailForm.action = '/app/scheduling/' + id + '/confirmar-por/email/';
            if (contactHint) {
                /* Diz para onde a mensagem vai antes de clicar: mandar
                 * confirmação para o telefone errado é o tipo de erro que
                 * só aparece quando o paciente não vem. */
                var phone = cell.getAttribute('data-nd-phone') || '';
                var mail = cell.getAttribute('data-nd-email') || '';
                var parts = [];
                if (phone) parts.push('SMS para ' + phone);
                if (mail) parts.push('e-mail para ' + mail);
                contactHint.textContent = parts.length
                    ? parts.join(' · ')
                    : 'Este paciente não tem telefone nem e-mail cadastrado.';
            }

            /* Só faz sentido confirmar quem ainda não confirmou nem chegou. */
            var status = cell.getAttribute('data-status');
            confirmForm.hidden = status !== 'scheduled';
            checkinForm.hidden = ['checked_in', 'in_progress', 'completed', 'no_show'].indexOf(status) !== -1;
            /* Sem contato, o botão sai da tela: um botão que sempre devolve
             * erro é pior que a ausência dele. */
            if (smsForm) smsForm.hidden = !cell.getAttribute('data-nd-phone');
            if (emailForm) emailForm.hidden = !cell.getAttribute('data-nd-email');

            changePanel.hidden = true;
            cancelPanel.hidden = true;
            changeChosen.textContent = '';
            changePatientId.value = '';
            changeSearch.value = '';
            window.NeuroDoc.openModal(slotModal);
        });

        document.getElementById('slot-change-open').addEventListener('click', function () {
            cancelPanel.hidden = true;
            changePanel.hidden = !changePanel.hidden;
            if (!changePanel.hidden) changeSearch.focus();
        });
        document.getElementById('slot-cancel-open').addEventListener('click', function () {
            changePanel.hidden = true;
            cancelPanel.hidden = !cancelPanel.hidden;
            if (!cancelPanel.hidden) document.getElementById('cancel-reason').focus();
        });
    }

    /* ------------------------------------------- busca de paciente */

    /* Uma função para os dois campos (marcar e trocar): a busca é a mesma, e
     * duplicá-la garantiria que uma das duas ficasse desatualizada. */
    function wirePatientSearch(input, resultsBox, hiddenId, chosenLabel) {
        if (!input || !resultsBox) return;
        var timer = null;
        var inFlight = null;

        function close() {
            resultsBox.hidden = true;
            resultsBox.innerHTML = '';
        }

        function choose(patient) {
            hiddenId.value = patient.id;
            input.value = patient.full_name;
            chosenLabel.textContent = 'Selecionado: ' + patient.full_name;
            chosenLabel.className = 'form-text fs-11 text-success';
            close();
        }

        input.addEventListener('input', function () {
            /* Digitar de novo desfaz a escolha anterior: sem isto, corrigir o
             * nome deixaria o id antigo no formulário e marcaria outra pessoa. */
            hiddenId.value = '';
            chosenLabel.textContent = '';
            chosenLabel.className = 'form-text fs-11';
            var term = input.value.trim();
            window.clearTimeout(timer);
            if (term.length < 2) {
                close();
                return;
            }
            timer = window.setTimeout(function () {
                if (inFlight) inFlight.abort();
                var controller = new AbortController();
                inFlight = controller;
                fetch('/app/patients/autocomplete/?q=' + encodeURIComponent(term), {
                    headers: { 'X-Requested-With': 'XMLHttpRequest' },
                    signal: controller.signal
                })
                    .then(function (response) { return response.json(); })
                    .then(function (data) {
                        var rows = data.results || [];
                        resultsBox.innerHTML = '';
                        if (!rows.length) {
                            close();
                            chosenLabel.textContent =
                                'Nenhum paciente com esse nome. Use o pré-cadastro abaixo.';
                            return;
                        }
                        rows.forEach(function (patient) {
                            var row = document.createElement('button');
                            row.type = 'button';
                            row.className = 'list-group-item list-group-item-action py-2 fs-12 text-start';
                            row.textContent = patient.full_name;
                            row.addEventListener('click', function () { choose(patient); });
                            resultsBox.appendChild(row);
                        });
                        resultsBox.hidden = false;
                    })
                    .catch(function (error) {
                        if (error.name === 'AbortError') return;
                        close();
                        chosenLabel.textContent =
                            'Busca indisponível agora. Use o pré-cadastro abaixo.';
                        chosenLabel.className = 'form-text fs-11 text-warning';
                    });
            }, 220);
        });

        input.addEventListener('keydown', function (event) {
            if (event.key === 'Enter') {
                /* Enter na busca não pode enviar o formulário: enviaria sem
                 * paciente escolhido. */
                event.preventDefault();
                var first = resultsBox.querySelector('button');
                if (first) first.click();
            } else if (event.key === 'Escape') {
                close();
            }
        });

        document.addEventListener('click', function (event) {
            if (event.target !== input && !resultsBox.contains(event.target)) close();
        });
    }

    wirePatientSearch(
        document.getElementById('book-search'),
        document.getElementById('book-results'),
        document.getElementById('book-patient-id'),
        document.getElementById('book-chosen')
    );
    wirePatientSearch(
        document.getElementById('change-search'),
        document.getElementById('change-results'),
        document.getElementById('change-patient-id'),
        document.getElementById('change-chosen')
    );
})();
