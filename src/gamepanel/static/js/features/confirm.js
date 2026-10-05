/* Confirmation before an irreversible action.
 *
 * Before, each screen wrote `onsubmit="return confirm('Apagar {{ nome }}?')"` in its
 * own HTML. That has two problems: the name (which comes from the container or the game)
 * went INSIDE JavaScript code - an apostrophe in the file name broke the
 * page - and none of it survives a CSP policy without `unsafe-inline`.
 *
 * Here the message travels in data-confirm, which the browser already hands over decoded
 * and which is never interpreted as code.
 */
export const confirmAction = {
  selector: '[data-confirm]',
  mount(el) {
    // On a form the confirmation applies to the whole submission; on a button, only to
    // that button - an alerts form has "Save", "Test" and "Remove",
    // and only the last one asks. The click is cancelable and happens before the submit.
    const event = el.tagName === 'FORM' ? 'submit' : 'click';

    el.addEventListener(event, (ev) => {
      if (!window.confirm(el.dataset.confirm)) {
        ev.preventDefault();
        ev.stopPropagation();
        return;
      }
      // A confirmed exit is a deliberate exit: the file editor must not
      // ask "you have unsaved changes" on top of this confirmation.
      document.dispatchEvent(new CustomEvent('gp:saida-deliberada'));
    });
  },
};
