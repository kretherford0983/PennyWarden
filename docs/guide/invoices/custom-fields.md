Custom fields are extra details an Administrator defines in [Invoices Setup](invoices-setup.md). Each has a type
(text, number, date or pick-list), a **Required** flag and **Show on PDF**. Each applies to one of:
- **The invoice** — details about the whole invoice, such as a *Purchase order* number, an event or a member ID. They
  print under *Bill to*.
- **Each line** — asked on every invoice line; printed after the line's description.
- **Lines of chosen products** — asked only on lines whose product has the field. Example: *Serial number* on
  *Instrument rental*. The Invoice Manager ticks the field on those products in the catalog
  ([Adding a product](add-product.md)); each sale then gets its own value.

A field is retired, never deleted; values already entered are kept. Custom fields are stored with the invoice and its
sent copy; they are not used in reports or filters.
