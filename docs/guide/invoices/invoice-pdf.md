The **Invoice PDF** section of Invoices Setup designs every invoice. The preview beside it uses sample data and updates
as you type.

- **Font**, **size** and **accent color**.
- **Logo** — the [organization logo](../system-about/organization-logos.md), its own, or none — and its position: **Left, above the letterhead**, **Center, between the letterhead and the title**, or
  **Right, above the title**.
- **Letterhead** and **Bill to** lines — one per row, up to 6, with **Remove** and **+ Add line**. Type `{` to choose a
  variable such as `{ORG.ADDRESS}` or `{CUSTOMER.NAME}`. The **Title**, **Bill to heading** and **Footer** suggest
  variables too.
- **Line table columns**: tick the columns you want, rename their headings, and put them in order by dragging a row by
  **⠿** (or with **↑** / **↓**).
- **Invoice fields**, **Terms** and **Notes** can be left off the PDF.
- **Window envelope (#10 double-window)**: *On the invoice* prints the letterhead (return address) and the Bill to lines
  where the envelope's windows show them, and starts the invoice below the first fold. Move either address in steps of
  1/16 inch if your envelope differs. The preview draws the windows and marks the folds — print it on plain paper and
  hold it behind an envelope.
- **Fold marks**: small ticks at the left and right edges where the page folds in thirds, on the front or on the back
  (needs two-sided printing).

**Save template** applies it to every invoice PDF made from now on; PDFs already kept for sent invoices don't change.

## Payment stub

Turn on **Payment stub (detach and return with payment)** to print a stub at the bottom of the invoice's last page,
below a dashed cut line with scissors and *Please detach and return this portion with your payment.* (When the invoice
doesn't leave room, the stub prints on a page of its own.) The stub shows:

- the **invoice number** in large type — what a Register User types into **Record a payment…** to find the invoice;
- the invoice and due dates, the customer and their **customer number**;
- the **amount due** when the PDF was made, and a blank **Amount enclosed** line;
- **Make checks payable to** and the mailing address — filled from the organization profile (`{ORG}`,
  `{ORG.ADDRESS}`) and editable here.

**Place the address for a #9 return envelope window** puts the mailing address where a #9 envelope's window shows it
(move it right or down if your envelopes differ), so the customer can mail the stub in your return envelope.

**Payment stub on customer statements** is its own setting: the statement gets a last page with a stub listing the
customer's open invoices and the total due. Both are off until you turn them on; invoices already sent keep their PDFs.
