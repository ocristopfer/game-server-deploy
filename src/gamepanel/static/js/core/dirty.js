/* Core - "you have unsaved changes".
 *
 * The text editor and the configuration form needed the same warning, and each
 * had its own copy, with a global flag (window.gpSaving) shared by
 * shouting. Here the flag is local and the only way to lower it is in the interface
 * this function returns.
 */
export function warnBeforeLeaving(estaSujo) {
  let allowed = false;

  window.addEventListener('beforeunload', (ev) => {
    if (!allowed && estaSujo()) ev.preventDefault();
  });

  // Deleting the open file, or any action that already asked "are you sure?", is a
  // deliberate exit: a second warning on top of it does not fit (see features/confirm.js).
  document.addEventListener('gp:saida-deliberada', () => { allowed = true; });

  return () => { allowed = true; };
}
