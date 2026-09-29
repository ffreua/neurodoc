/* O evento terminal precisa encerrar visualmente a geração, não só trocar o texto. */
const fs = require('fs');
const path = require('path');
const vm = require('vm');

const terminalTypes = ['complete', 'error', 'cancelled', 'revoked'];
const lives = [];
const messages = [];

terminalTypes.forEach((type) => {
  const controls = {
    removed: false,
    remove() { this.removed = true; },
  };
  const message = {
    dataset: { state: 'streaming' },
    querySelector(selector) {
      return selector === '[data-stream-controls]' ? controls : null;
    },
    controls,
  };
  const live = {
    innerHTML: '',
    textContent: '',
    textNode: null,
    getAttribute(name) { return name === 'data-stream-url' ? `/stream/${type}/` : null; },
    appendChild(node) { this.textNode = node; },
    closest(selector) { return selector === '.message' ? message : null; },
  };
  messages.push(message);
  lives.push(live);
});

global.document = {
  querySelectorAll(selector) {
    return selector === '.live[data-stream-url]' ? lives : [];
  },
  createTextNode(value) { return { textContent: value }; },
};

class FakeEventSource {
  static instances = [];
  constructor(url) {
    this.url = url;
    this.listeners = {};
    this.closed = false;
    FakeEventSource.instances.push(this);
  }
  addEventListener(type, handler) { this.listeners[type] = handler; }
  close() { this.closed = true; }
  emit(type, data) { this.listeners[type]({ data: JSON.stringify(data || {}) }); }
}
global.EventSource = FakeEventSource;

const source = fs.readFileSync(path.join(__dirname, '..', 'static', 'ai', 'chat.js'), 'utf8');
vm.runInThisContext(source, { filename: 'static/ai/chat.js' });

FakeEventSource.instances[0].emit('complete', { html: '<p>Resposta pronta.</p>' });
FakeEventSource.instances[1].emit('error', { message: 'Falhou.' });
FakeEventSource.instances[2].emit('cancelled', {});
FakeEventSource.instances[3].emit('revoked', {});

const failures = [];
terminalTypes.forEach((type, index) => {
  const message = messages[index];
  const stream = FakeEventSource.instances[index];
  if (!message.controls.removed) failures.push(`${type}: controles de geração continuaram visíveis`);
  if (message.dataset.state === 'streaming') failures.push(`${type}: mensagem continuou marcada como streaming`);
  if (!stream.closed) failures.push(`${type}: EventSource continuou aberto`);
});

if (failures.length) {
  failures.forEach((failure) => console.error(`FALHA: ${failure}`));
  process.exit(1);
}
console.log('OK: todo evento terminal remove spinner/Parar e encerra o estado de geração.');
