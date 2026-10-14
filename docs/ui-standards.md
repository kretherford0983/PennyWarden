# UI standards

How PennyWarden screens are laid out, so every new screen looks and behaves like the existing ones (2.0.0, #214).
The rules are implemented once — in `frontend/src/styles.css` (section *#214 (build 11): UI standards*) and the
shared components in `frontend/src/components.tsx` — so a screen that uses them gets them for free. Don't restyle a
single screen to work around a rule; change the rule here and in the shared CSS.

The E2E test *"#214: form rows line up"* measures every form row on the main screens (Budget Manager, Register User
and Administrator screens, the entity, bank account, user and transaction forms, the Payments Setup editors) and
fails on any rule below that is broken. It also saves a screenshot of each form in `frontend/e2e-screenshots/forms/`
(uploaded with the E2E artifacts) for a visual review. Add a new screen to that test when you build one.

## 1. Fields: `Field` and form rows

Use the `Field` component for every labelled input: the label above, the control below, optional help text under the
control.

```tsx
<div className="row">
  <Field label="Check date"><input type="date" … /></Field>
  <Field label="Check #" hint="The number printed on the check you will use."><input … /></Field>
</div>
```

- **Labels are one short line** (12 px, bold, muted). Keep them short enough not to wrap at the usual widths; put
  explanations in the hint or a paragraph, not the label.
- **A row of fields lines up on the labels** (`.row`, `.filters`, `.page-head`, `.report-options`): all labels on one
  line, all controls on one line. Help text grows **downwards** under its own field and never pushes a neighbouring
  field up or down. (Before 2.0.0 rows aligned on their bottom edge, so a hint under *Check #* moved *Check date*.)
- Components that render their own label (the entity picker, the pattern input) use the same `.field` /
  `.field-label` structure, so they line up too.
- Inside a `GuardedForm` the fields are wrapped in a `fieldset.form-guard` with `display: contents`; the row rules
  look through it.

## 2. One control height

| Control | Height |
|---|---|
| Text box, number, date, password, search, select (single) | `--control-h` (34 px) |
| Button (default, `primary`, `danger`), `a.button` | `--control-h` (34 px) |
| Small button (`button.small`), `select.small`, upload label (`label.button`) | `--control-h-sm` (26 px) |

Dropdowns are exactly as tall as text boxes, date fields and buttons on the same row. Text links styled as buttons
(`.link`, `.linklike`) and icon buttons keep their own size. Never set a height or vertical padding on a single
control to make it fit.

## 3. Buttons and checkboxes in a form row

A button or an inline checkbox placed in a row of fields sits **on the input line**:

- a full-size button lines up with the inputs (same top, same height);
- a small button (for example *+ New entity* next to the payee box) and an inline checkbox (for example *Include VOID
  transactions*) are **vertically centred** on the inputs.

```tsx
<div className="row">
  <EntityPicker label="Payee (entity)" … />
  <button type="button" className="small" onClick={…}>+ New entity</button>
</div>
<div className="report-options">
  <Field label="Fiscal Year"><select …/></Field>
  <label className="check"><input type="checkbox" … /> Include VOID transactions</label>
</div>
```

Put the button or the `label.check` directly in the row (not wrapped in another `div`), so the row rules apply. A row
with no fields at all (only buttons, checkboxes and text) centres everything on one line.

## 4. Action bars

- The buttons that finish a form go in `.actions` at the bottom (right-aligned; `.actions.left` for page-level
  buttons). The primary action is last and `primary`.
- An editor long enough to scroll keeps its bar in view with `.actions.sticky-actions`. The sticky bar is a **solid
  footer**: opaque (`--bg`), the full width of the content area and down to the window's edge, with a top border and
  a light shadow — page content never shows through, beside or below it while scrolling. Used by the Payments Setup
  editors (check style, cover letter, envelope).

## 5. Where these rules live

| Rule | CSS / component |
|---|---|
| Control heights | `--control-h`, `--control-h-sm` on `:root`; the *#214* block at the end of `styles.css` |
| Label height | `--label-h` (= 17 px label line + 3 px field gap); `.field-label` |
| Form rows | `:is(.row, .filters, .page-head, .report-options):has(> .field)` rules |
| Sticky action bar | `.sticky-actions` (uses the content area's `--pad-x` / `--pad-y`) |
| Field | `Field` in `components.tsx` |
