"""2.0.0 (#125): reinitialize - remove all financial data but keep the users, with an automatic safety backup.

This is the one operation that physically removes financial records (an explicit exception to BR-001, BR-012,
BR-026, BR-033, BR-040 and BR-065, decided with the product owner): the safety backup and the append-only audit log
keep the record of it.

Order: confirmation (typed word, password, two-step code when enabled) -> safety backup (the .fmbak format, with the
passphrase entered or a random one, always recoverable by this server's owner, stored in `pre-reinitialize/`, never
listed for download or removed from the web) -> verified by decrypting it against its manifest -> the application is
paused and everyone else is signed out -> the removal, the reseeding and the REINITIALIZE audit event in ONE database
transaction -> the attachment files are removed after the commit.

Removed: Fiscal Years, budgets, entities (not the system entity Multiple), bank accounts and balances, the register
(transactions, allocations), Fiscal Year reviews, attachments (rows and files), fundraisers, the Payments module's data
(check styles, signers, letters, envelopes, printer settings), organization reminders, missing-check
acknowledgements and duplicate-request keys. Kept: users, roles, passwords, two-step data, security questions, the
organization name, the encryption key, module switches, personal preferences and reminders (their links to removed
records are cleared), backup settings and history, signature-page wording, and the audit log. Entity numbers continue
(decided 2026-10-12): a new entity never reuses a number from older backups or reports.
"""
from __future__ import annotations

import datetime as dt
import os
import secrets
import shutil
from pathlib import Path

from sqlalchemy import delete, func, select, update
from sqlalchemy.orm import Session

from .. import audit
from ..models import (Attachment, AuditEvent, BankAccount, BankAccountBalance, Budget, BudgetHistoryEntry, BudgetProjectionChoice, CheckAccount,
                      CheckDocument, CheckNumberAcknowledgement, CheckPrinterSetting, CheckSigner, CheckStyle, DonationDetail, DonationLine,
                      DonationReceipt, DonationSettings, Entity,
                      FiscalYear, FiscalYearReview, Fundraiser, FundraiserBucket, FundraiserBucketCategory, FundraiserBucketLine, FundraiserBudget,
                      FundraiserFyReportNote, FundraiserSeries, FundraiserSeriesResult,
                      FundraiserClassification, FundraiserExclusion, FundraiserLineContributor, RegisterTransaction, Reminder,
                      RequestKey,
                      TransactionAllocation, User, Workspace, utcnow)
from . import backup as bk
from . import server_recovery

PRE_DIR = "pre-reinitialize"
CONFIRM_WORD = "reinitialize"
COOLDOWN = dt.timedelta(hours=24)

# children first
WIPE = (DonationReceipt, DonationDetail, DonationLine, FundraiserBucketLine, FundraiserLineContributor, FundraiserClassification, FundraiserExclusion, FiscalYearReview, Attachment,
        TransactionAllocation, RegisterTransaction, CheckNumberAcknowledgement, CheckAccount, CheckPrinterSetting,
        BankAccountBalance, BankAccount, FundraiserBucket, FundraiserBucketCategory, FundraiserBudget, Fundraiser, FundraiserSeriesResult,
        FundraiserSeries, FundraiserFyReportNote, BudgetProjectionChoice, BudgetHistoryEntry, Budget, FiscalYear,
        CheckDocument, CheckSigner, CheckStyle, DonationSettings, RequestKey)   # 2.1.0 (#312): donations


class ReinitError(Exception):
    pass


def last_reinitialize(db: Session, ws_id: int) -> dt.datetime | None:
    return db.scalar(select(func.max(AuditEvent.timestamp)).where(AuditEvent.workspace_id == ws_id,
                                                                  AuditEvent.action == "REINITIALIZE"))


def cooldown_until(db: Session, ws_id: int, now: dt.datetime | None = None) -> dt.datetime | None:
    last = last_reinitialize(db, ws_id)
    from . import testing     # 2.2.0 (#231): cleared by a testing-mode Administrator
    cleared = testing.cooldown_cleared_at(db, ws_id)
    if last and cleared and cleared >= last:
        return None
    if last and (now or utcnow()) < last + COOLDOWN:
        return last + COOLDOWN
    return None


def counts(db: Session, ws_id: int) -> dict:
    def n(model, *where):
        return db.scalar(select(func.count()).select_from(model).where(*where)) or 0
    return {"fiscal_years": n(FiscalYear, FiscalYear.workspace_id == ws_id),
            "budgets": n(Budget, Budget.workspace_id == ws_id),
            "entities": n(Entity, Entity.workspace_id == ws_id, Entity.is_system.is_(False)),
            "bank_accounts": n(BankAccount, BankAccount.workspace_id == ws_id),
            "transactions": n(RegisterTransaction, RegisterTransaction.workspace_id == ws_id),
            "attachments": n(Attachment, Attachment.workspace_id == ws_id),
            "fundraisers": n(Fundraiser, Fundraiser.workspace_id == ws_id),
            "check_styles": n(CheckStyle, CheckStyle.workspace_id == ws_id)}


# ------------------------------------------------------------------ the safety backup
def safety_backup(settings, passphrase: str, created_by: str, job=None) -> dict:
    """Creates, verifies and stores the safety backup. Raises ReinitError (nothing removed) when anything fails."""
    try:
        path, name, manifest = bk.create_backup(settings, passphrase, job)
    except Exception as e:  # noqa: BLE001
        raise ReinitError(f"The safety backup could not be created ({type(e).__name__}); nothing was removed.") from None
    check = bk.work_dir(settings) / f"verify-{secrets.token_hex(6)}"
    try:
        if job:
            job.advance("Checking the safety backup")
        bk.unpack(path, passphrase, check)
    except Exception:  # noqa: BLE001
        try:
            path.unlink()
        except OSError:
            pass
        raise ReinitError("The safety backup could not be verified; nothing was removed.") from None
    finally:
        shutil.rmtree(check, ignore_errors=True)
    d = settings.data_dir / PRE_DIR
    d.mkdir(parents=True, exist_ok=True)
    try:
        os.chmod(d, 0o700)
    except OSError:  # pragma: no cover
        pass
    final = d / f"pre-reinitialize-{dt.datetime.utcnow():%Y%m%d-%H%M%S}-{name}"
    i = 1
    while final.exists():   # every safety backup is kept: never overwrite one made in the same second
        i += 1
        final = d / f"pre-reinitialize-{dt.datetime.utcnow():%Y%m%d-%H%M%S}-{i}-{name}"
    shutil.move(str(path), final)
    try:
        os.chmod(final, 0o600)
    except OSError:  # pragma: no cover
        pass
    rec = server_recovery.write_recovery(settings, final, final.name, passphrase, created_by, kind="PRE_REINITIALIZE",
                                         location=f"{PRE_DIR}/{final.name}")
    return {"path": final, "filename": final.name, "folder": str(d), "recovery_id": rec["id"],
            "counts": manifest.get("counts")}


def new_passphrase() -> str:
    return secrets.token_urlsafe(24)


# ------------------------------------------------------------------ the wipe
def wipe(db: Session, ws_id: int, ctx, by: str, backup_name: str, via: str, before: dict) -> None:
    """Removes the financial data and records REINITIALIZE - in the caller's transaction (commit by the caller)."""
    tx_ids = select(RegisterTransaction.id).where(RegisterTransaction.workspace_id == ws_id)
    alloc_ids = select(TransactionAllocation.id).where(TransactionAllocation.transaction_id.in_(tx_ids))
    fr_ids = select(Fundraiser.id).where(Fundraiser.workspace_id == ws_id)
    bucket_ids = select(FundraiserBucket.id).where(FundraiserBucket.fundraiser_id.in_(fr_ids))
    style_ids = select(CheckStyle.id).where(CheckStyle.workspace_id == ws_id)
    scoped = {
        FundraiserBucketLine: FundraiserBucketLine.bucket_id.in_(bucket_ids),
        FundraiserClassification: FundraiserClassification.fundraiser_id.in_(fr_ids),
        FundraiserLineContributor: FundraiserLineContributor.fundraiser_id.in_(fr_ids),
        FundraiserExclusion: FundraiserExclusion.fundraiser_id.in_(fr_ids),
        TransactionAllocation: TransactionAllocation.id.in_(alloc_ids),
        FundraiserBucket: FundraiserBucket.id.in_(bucket_ids),
        FundraiserBucketCategory: FundraiserBucketCategory.fundraiser_id.in_(fr_ids),
        FundraiserSeriesResult: FundraiserSeriesResult.series_id.in_(
            select(FundraiserSeries.id).where(FundraiserSeries.workspace_id == ws_id)),
        FundraiserBudget: FundraiserBudget.fundraiser_id.in_(fr_ids),
        CheckAccount: CheckAccount.check_style_id.in_(style_ids),
    }
    for model in WIPE:
        cond = scoped.get(model)
        if cond is None:
            cond = model.workspace_id == ws_id
        db.execute(delete(model).where(cond).execution_options(synchronize_session=False))
    # budgets reference each other (parents, continued budgets) - already deleted together above
    db.execute(delete(Entity).where(Entity.workspace_id == ws_id, Entity.is_system.is_(False),
                                    Entity.is_organization.is_(False))      # 2.1.0 (#314): the organization stays
               .execution_options(synchronize_session=False))
    db.execute(delete(Reminder).where(Reminder.workspace_id == ws_id, Reminder.scope != "PERSONAL")
               .execution_options(synchronize_session=False))
    db.execute(update(Reminder).where(Reminder.workspace_id == ws_id)
               .values(link_type=None, link_id=None).execution_options(synchronize_session=False))
    db.execute(update(User).where(User.workspace_id == ws_id).values(last_payment_account_id=None)
               .execution_options(synchronize_session=False))
    ws = db.get(Workspace, ws_id)
    now = utcnow()
    ws.reinitialized_at, ws.reinitialized_by, ws.reinitialize_backup = now, by[:64], backup_name[:255]   # 64: label
    ws.reinitialize_ack_at = ws.reinitialize_ack_by = None
    db.flush()
    if not db.scalar(select(Entity).where(Entity.workspace_id == ws_id, Entity.is_system.is_(True))):
        from .bootstrap import MULTIPLE_ENTITY_NUMBER
        db.add(Entity(workspace_id=ws_id, entity_number=MULTIPLE_ENTITY_NUMBER, entity_type="SYSTEM",
                      organization_name="Multiple", is_system=True, active=True, name_key="multiple"))
    audit.record(db, ctx, "REINITIALIZE", "workspace", ws_id, {"counts": before},
                 {"by": by, "via": via, "safety_backup": backup_name, "kept": "users, roles, two-step, organization, "
                  "key, modules, preferences, audit log"}, category="SECURITY")


def remove_attachment_files(settings) -> None:
    """After the commit: every attachment file is gone with its row (only inside the attachments folder)."""
    base = settings.attachments_dir
    if not base.is_dir():
        return
    for p in base.iterdir():
        if p.is_dir():
            shutil.rmtree(p, ignore_errors=True)
        else:
            try:
                p.unlink()
            except OSError:
                pass


def banner(ws: Workspace | None) -> dict:
    if ws is None or ws.reinitialized_at is None or ws.reinitialize_ack_at is not None:
        return {"show": False}
    return {"show": True, "at": ws.reinitialized_at.replace(microsecond=0).isoformat() + "Z",
            "by": ws.reinitialized_by}


def acknowledge(db: Session, ctx) -> dict:
    ws = db.get(Workspace, ctx.workspace_id)
    if ws.reinitialized_at is not None and ws.reinitialize_ack_at is None:
        ws.reinitialize_ack_at, ws.reinitialize_ack_by = utcnow(), ctx.user.username
        db.flush()
        audit.record(db, ctx, "REINITIALIZE_ACKNOWLEDGED", "workspace", ws.id, None,
                     {"reinitialized_at": ws.reinitialized_at.isoformat() + "Z"})
    return banner(ws)


def pre_dir(settings) -> Path:
    return settings.data_dir / PRE_DIR
