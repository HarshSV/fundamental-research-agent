export const OPEN_SEARCH_EVENT = "navrist-open-search";
export const OPEN_SCREENER_EVENT = "navrist-open-screener"; // the header's Create Screener button
export const OPEN_RESISTANCE_EVENT = "navrist-open-resistance"; // the header's Horizontal Resistance button

/** Ask the page to open the full-screen search; `from` is the element it springs out of. */
export function openSearch(from: Element | null) {
  window.dispatchEvent(new CustomEvent(OPEN_SEARCH_EVENT, { detail: { rect: from ? from.getBoundingClientRect() : null } }));
}
