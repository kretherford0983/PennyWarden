/** 2.2.0 (#316): how this user sees and sorts Individuals - "First Last" (default) or "Last, First". Set from the
 * signed-in user (App) and changed on My account; used by the Entities list and the entity pickers. */
let order: "FIRST_LAST" | "LAST_FIRST" = "FIRST_LAST";

export function setNameOrder(o: string | null | undefined) {
  order = o === "LAST_FIRST" ? "LAST_FIRST" : "FIRST_LAST";
}

export function nameOrder() {
  return order;
}

/** The name shown for an entity: an Individual with no display name of its own follows the name order. */
export function entityName(e: any): string {
  if (e && e.entity_type === "INDIVIDUAL" && e.display_name_same !== false && order === "LAST_FIRST" && e.last_name) {
    return `${e.last_name}, ${e.first_name || ""}`.trim();
  }
  return e?.display_name || "";
}

/** The sort key for an entity: Individuals by last then first name when the order is "Last, First". */
export function entitySortKey(e: any): string {
  return entityName(e).toLowerCase();
}
