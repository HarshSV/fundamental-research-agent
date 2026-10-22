export const OPEN_SEARCH_EVENT = "navrist-open-search";

/** Ask the page to open the full-screen search; `from` is the element it springs out of. */
export function openSearch(from: Element | null) {
  window.dispatchEvent(new CustomEvent(OPEN_SEARCH_EVENT, { detail: { rect: from ? from.getBoundingClientRect() : null } }));
}
