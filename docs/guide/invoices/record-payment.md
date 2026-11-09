1. Open the sent invoice and choose **Record payment…**. The payment form opens with this invoice ticked; the
   customer's other open invoices are listed below it, unticked.
2. Enter the **Amount received** (this invoice's open balance by default), then choose the bank account and the date.
3. **Record payment**. The deposit is created in the Register, split over the lines' budgets and each tax rate's
   budget.

- A **partial payment** leaves the invoice *Partly paid*; the next payment continues where it stopped.
- More than the open balance: choose what happens to **the other** amount (see below).
- **Link a deposit…** attaches a deposit already in the Register instead.

## When a payment is more than the invoices

Wherever a payment is recorded (**Record payment…**, **Record a payment…** for several invoices, or **Apply to
invoice…** in the Register), the amount above the invoices gets the same choices:

- **Apply it to the other open invoices**: shown when the customer still owes on other invoices. It ticks them and
  fills them oldest due date first; change any part before saving.
- **Kept on a budget** (for example a donation or a fundraiser): choose the budget. In the Register it stays on the
  allocation's budget.
- **Kept as the customer's account credit**: only when the customer owes nothing else. A customer with an open balance
  on another invoice isn't given credit; apply the extra to that invoice, keep it on a budget or refund it.
- **Refunded**: once the payment is saved, the **Refund** form opens for that invoice with the amount, bank account and
  date filled in. Add the check number and choose **Record refund**. If you choose **Not now**, the amount stays an
  overpayment on the invoice, and **Refund credit…** there finishes it later.

## One payment for several invoices

When one check or transfer pays more than one invoice, record it once so the Register shows a single deposit that
matches the bank:

1. On the **Invoices** page, either tick the invoices in the list and choose **Record payment for N invoices…**, or
   choose **Record a payment…** and pick the customer — or type an **invoice number** (for example from a payment
   stub) and choose **Find** to list that customer's open invoices.
2. Enter the **Amount received**. It fills the balances **oldest due date first**; change any invoice's part, or
   untick an invoice to leave it out.
3. If the amount is more than the balances, choose what happens to **the other** amount (see above; you'll be asked
   to confirm).
4. **Paid by** is the customer. When the invoices are for different customers (a company or parent paying for
   several members), choose who paid — you'll be asked to confirm.
5. Choose the bank account and the date, then **Record payment**.

Each invoice gets its part as **Record payment…** would give it, linked to that invoice. Voiding the deposit re-opens
every invoice it paid; unlinking on one invoice moves only that invoice's lines.

## A deposit entered in the Register first

When you're already entering a deposit in the **Register** and realize it pays an invoice:

1. Choose the **Entity** (the customer who paid) and enter the allocation's amount.
2. Choose **Apply to invoice…** on that allocation. The customer's open invoices are listed, oldest due date first, and
   the amount fills them in that order; change any invoice's part, or untick one.
3. If the allocation is more than you apply, choose what happens to **the other** amount (see above): keep it on the
   allocation's budget (for example a fundraiser or a donation — pick that budget), apply it to the customer's other
   open invoices, keep it as their **credit** (only when they owe nothing else), or **refund** it (the Refund form
   opens once the deposit is saved).
4. **Save**. The applied part is spread over each invoice's Invoiced Income budgets and tax and linked to the invoice;
   the deposit's other allocations stay as you entered them — one $1,150 check can pay a $1,000 invoice and put $150
   on a fundraiser.

A deposit already saved on another Income budget can be linked from the invoice: **Link a deposit…** lists the
customer's deposit lines first, and linking moves the line onto the invoice's budgets (a Register User does this).

## Customer credit

Money received above what a customer's invoices owe is their **account credit** — an overpayment on an invoice, not
yet refunded. It shows on the invoice (**Overpaid (customer credit)**), on the customer's other invoices, in **Record a
payment…** and on their **statement**.

- **Applied automatically:** when the customer's next invoice is **marked as sent**, their credit is applied to it,
  oldest first, up to what it owes. The invoice shows **Account credit applied**, and its PDF shows **New charges**,
  **Account credit applied** and **Total due**. The deposit that brought the money doesn't change; the credit's part
  moves onto the new invoice's budgets.
- **Take credit off…** (Register User, with a reason): the credit applied to an invoice becomes the customer's credit
  again, and the invoice owes that amount again.
- **Refund credit…** (Register User): a refund of the credit, with its check number.
- **Move credit…** (Register User, with a reason): for example when the customer says to keep it as a donation — the
  credit moves to another budget and is no longer theirs.

A credit held by a deposit in a **Closed** Fiscal Year can't be applied automatically; it can still be refunded.
