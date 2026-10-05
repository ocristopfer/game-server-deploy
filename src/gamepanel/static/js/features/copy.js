/* Copy to the clipboard.
 *
 * The target comes as a selector in data-copy. On the phone, selecting an 80-character
 * SSH key with a finger is torture - this button is the normal path, not a luxury.
 */
export const copyToClipboard = {
  selector: '[data-copy]',
  mount(button) {
    const target = document.querySelector(button.dataset.copy);
    if (!target || !navigator.clipboard) return;
    button.hidden = false;

    const label = button.textContent;
    button.addEventListener('click', async () => {
      try {
        await navigator.clipboard.writeText(target.textContent.trim());
        // The phrases come from the page (base.html); without them the button keeps its own text.
        button.textContent = document.body.dataset.labelCopied || label;
      } catch {
        // No permission (http without TLS, for example): the text stays on the screen to
        // be selected by hand, so this is a warning, not an error.
        button.textContent = document.body.dataset.labelCopyFailed || label;
      }
      setTimeout(() => { button.textContent = label; }, 2000);
    });
  },
};
