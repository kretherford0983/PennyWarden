import { useEffect, useState } from "react";
import { api } from "../api";
import { ErrorBox, Loading } from "../components";

// 2.4.0 (#251): the Invoices module. Its sections (invoices, products, payments, reports) arrive with the later 2.4.0
// builds (#252-#255); this page says what the module is for and who does what (separation of duties).
export default function Invoices() {
  const [o, setO] = useState<any>(null);
  const [err, setErr] = useState<unknown>(null);
  useEffect(() => { api.get("/api/invoices/overview").then(setO, setErr); }, []);
  if (!o) return <><ErrorBox error={err} />{err ? null : <Loading />}</>;
  return (
    <div>
      <div className="page-head"><h1>Invoices</h1></div>
      <section className="card" aria-labelledby="inv-roles-h">
        <h2 id="inv-roles-h">Who does what</h2>
        <ul>
          <li><b>Budget Managers</b> decide the budgets and mark Income budgets as <b>Invoiced Income</b>.</li>
          <li><b>Invoice Managers</b> decide what is billed and for how much.</li>
          <li><b>Register Users</b> receive and record the money.</li>
          <li><b>Auditors</b> review everything.</li>
        </ul>
        <p className="hint">One person may hold several of these roles in a small organization; keeping them apart lets someone else check each step.</p>
        <p className="muted" data-testid="inv-coming">Invoices, the product catalog, payments and invoice reports appear here as they are added in this release.</p>
      </section>
    </div>
  );
}

// 2.4.0 (#251): the Administrator's module setup (numbering, terms, template and test print come with the Invoices
// build, #253). Administrators never see real invoices or products (BR-003).
export function InvoiceSetup() {
  const [o, setO] = useState<any>(null);
  const [err, setErr] = useState<unknown>(null);
  useEffect(() => { api.get("/api/invoices/setup").then(setO, setErr); }, []);
  if (!o) return <><ErrorBox error={err} />{err ? null : <Loading />}</>;
  return (
    <div>
      <div className="page-head"><h1>Invoices Setup</h1></div>
      <section className="card">
        <p>Invoice numbering, payment terms, custom fields, the invoice PDF template, overdue-reminder days and a test print with sample data will be set up here.</p>
        <p className="muted">Nothing to set up yet in this test build.</p>
      </section>
    </div>
  );
}
