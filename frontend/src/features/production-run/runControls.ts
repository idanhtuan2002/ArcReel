/** The element that holds an automatic run's controls on the overview: the operations summary while a run is
 * making the film, the status card once it stopped or finished. A notification or the run banner leads here. */
export const RUN_CONTROLS_ID = "run-controls";

/** Brings the run's controls into view and focus once they are on the page (the overview may still be mounting after
 * a navigation; on the overview itself the address does not change, so scrolling is the only response). */
export function showRunControls(tries = 30): void {
  const element = document.getElementById(RUN_CONTROLS_ID);
  if (element) {
    element.scrollIntoView({ behavior: "smooth", block: "center" });
    element.focus({ preventScroll: true });
    return;
  }
  if (tries > 0) window.setTimeout(() => showRunControls(tries - 1), 50);
}
