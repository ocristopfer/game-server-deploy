/* Theme button (light/dark) in the header.
 *
 * The server only knows the theme the person CHOSE (cookie); when they never chose,
 * the screen follows the device, and only the browser knows that. Without this module the first click
 * on a phone in light mode would ask for "light" again and nothing would change. Here the target and the
 * icon become the OPPOSITE of the theme actually on the screen.
 */
const ICONS = { light: '☀️', dark: '🌙' };

function shownTheme() {
  const chosen = document.documentElement?.dataset?.theme;
  if (chosen === 'light' || chosen === 'dark') return chosen;
  return window.matchMedia?.('(prefers-color-scheme: light)').matches ? 'light' : 'dark';
}

export const themeToggle = {
  selector: 'form[action$="/preferences/theme"]',
  mount(form) {
    const target = form.querySelector('input[name="theme"]');
    const icon = form.querySelector('.icon');
    if (!target) return;
    const next = shownTheme() === 'light' ? 'dark' : 'light';
    target.value = next;
    if (icon) icon.textContent = ICONS[next];
  },
};
