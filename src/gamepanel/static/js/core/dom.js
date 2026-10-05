/* Core - DOM shortcuts.
 *
 * No framework: four functions that remove the querySelector noise from the
 * features and centralize the only safe way to mount a table cell with
 * text that came from the container.
 */

export const $ = (selector, root = document) => root.querySelector(selector);
export const $$ = (selector, root = document) => Array.from(root.querySelectorAll(selector));

/* Creates an element. `text` always goes in through textContent - never through innerHTML -
 * because almost every text the panel shows (player name, file path,
 * log line) came from outside and must not become markup. */
export function createEl(tag, { className = '', text = '', attrs = {} } = {}) {
  const el = document.createElement(tag);
  if (className) el.className = className;
  if (text !== '') el.textContent = text;
  for (const [k, v] of Object.entries(attrs)) el.setAttribute(k, v);
  return el;
}

/* Replaces an element's content with a list of children, all at once. */
export function reset(target, children) {
  target.replaceChildren(...children);
  return target;
}

/* Fills a form's fields from { name: value }. A checkbox is turned on with
 * '1' and off with anything else; a name the form does not have is ignored.
 *
 * Several checkboxes with the SAME name (the recipes) arrive as a group, and the value is the list
 * of checked ones separated by spaces: 'proton xvfb'. The group has no `tagName` (it is a list, not
 * an element) - and the `select`, which also has `length`, does. Without this case the "Unreal
 * Windows" template left Proton unchecked, and the broker rejected the Windows game with no runtime. */
export function fillForm(form, values) {
  Object.entries(values).forEach(([name, value]) => {
    const field = form.elements[name];
    if (!field) return;
    if (!field.tagName) {
      const marked = String(value).split(/\s+/).filter(Boolean);
      Array.from(field).forEach((box) => { box.checked = marked.includes(box.value); });
    } else if (field.type === 'checkbox') field.checked = value === '1';
    else field.value = value;
  });
}
