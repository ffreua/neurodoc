// Minimal SSE client for AI chat streaming (S12).
//
// EventSource is used deliberately: it is the browser's native SSE client,
// so reconnection with Last-Event-ID (RF-11.04) is handled by the browser
// itself, not hand-rolled here -- a dropped connection reconnects and the
// server (ai/sse.py) resumes from exactly the last event id it sent.
//
// While streaming, incoming text is appended via textContent, never
// innerHTML -- even though the server already escapes/sanitizes, deltas
// are raw model output and are never parsed as HTML on the client. Only
// the final "complete" event's pre-sanitized `html` field (produced by
// ai.rendering.render_markdown on the server) is inserted via innerHTML.
(function () {
  document.querySelectorAll('.live[data-stream-url]').forEach(function (el) {
    var url = el.getAttribute('data-stream-url');
    var source = new EventSource(url);
    var textNode = document.createTextNode('');
    el.appendChild(textNode);

    source.addEventListener('delta', function (event) {
      var payload = JSON.parse(event.data);
      textNode.textContent += payload.text;
    });

    source.addEventListener('complete', function (event) {
      var payload = JSON.parse(event.data);
      el.innerHTML = payload.html;
      source.close();
    });

    source.addEventListener('error', function (event) {
      var message = 'Falha ao gerar a resposta.';
      try {
        message = JSON.parse(event.data).message || message;
      } catch (e) { /* connection-level error, no payload */ }
      el.textContent = message;
      source.close();
    });

    source.addEventListener('cancelled', function () {
      el.textContent = 'Cancelado.';
      source.close();
    });

    source.addEventListener('revoked', function () {
      el.textContent = 'Sessão revogada. Faça login novamente.';
      source.close();
    });
  });
})();
