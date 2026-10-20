/* Собственные модальные диалоги вместо confirm() и prompt().

   Зачем: Chrome после нескольких нативных диалогов подряд показывает
   «Предотвратить создание дополнительных диалоговых окон». Если эту
   галочку поставить (или браузер решит сам), все последующие confirm()
   молча возвращают false — кнопки удаления перестают работать без
   единого сообщения об ошибке.

   Здесь тот же интерфейс, но на DOM: диалоги не блокируются, одинаково
   выглядят во всех браузерах и работают в мобильном виде. */

let dialogDepth = 0;

function closeAllDialogs() {
  document.querySelectorAll('.mtr-dialog-backdrop').forEach((node) => node.remove());
  dialogDepth = 0;
}

function makeDialog({ title, message, input = null, okLabel = 'OK',
                      cancelLabel = 'Отмена', danger = false }) {
  return new Promise((resolve) => {
    const previousFocus = document.activeElement;
    dialogDepth += 1;

    const field = input !== null
      ? el('input', {
          type: 'text', class: 'mtr-dialog-input',
          value: input, 'aria-label': title || 'Значение',
        })
      : null;

    let settled = false;
    const finish = (value) => {
      if (settled) return;
      settled = true;
      dialogDepth = Math.max(0, dialogDepth - 1);
      backdrop.remove();
      document.removeEventListener('keydown', onKey);
      if (previousFocus && previousFocus.focus) previousFocus.focus();
      resolve(value);
    };

    const onKey = (event) => {
      if (event.key === 'Escape') { event.preventDefault(); finish(null); }
      // Enter подтверждает: в диалоге с полем это ожидаемое поведение.
      if (event.key === 'Enter') { event.preventDefault(); finish(field ? field.value : true); }
    };

    const okButton = el('button', {
      class: danger ? 'danger-solid' : 'primary',
      onclick: () => finish(field ? field.value : true),
    }, okLabel);

    const cancelButton = el('button', {
      class: 'ghost',
      onclick: () => finish(null),
    }, cancelLabel);

    const backdrop = el('div', {
      class: 'mtr-dialog-backdrop', role: 'presentation',
      onclick: (event) => { if (event.target === backdrop) finish(null); },
    },
      el('div', {
        class: 'mtr-dialog', role: 'dialog', 'aria-modal': 'true',
        'aria-label': title || 'Подтверждение',
      },
        title ? el('h3', { class: 'mtr-dialog-title' }, title) : null,
        message ? el('p', { class: 'mtr-dialog-text' }, message) : null,
        field,
        el('div', { class: 'mtr-dialog-actions' }, cancelButton, okButton),
      ),
    );

    document.body.append(backdrop);
    document.addEventListener('keydown', onKey);
    (field || okButton).focus();
    if (field) field.select();
  });
}

/* Возвращает true при подтверждении, null при отказе/закрытии. */
function confirmDialog(message, { title = '', okLabel = 'Удалить',
                                  cancelLabel = 'Отмена', danger = true } = {}) {
  return makeDialog({ title, message, okLabel, cancelLabel, danger });
}

/* Возвращает строку или null, если пользователь отказался. */
function promptDialog(message, defaultValue = '', { title = '',
                                                    okLabel = 'Сохранить' } = {}) {
  return makeDialog({ title, message, input: defaultValue, okLabel });
}
