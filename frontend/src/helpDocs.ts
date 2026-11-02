/** 2.4.0 (#473): the bundled guides (see help.ts). Imported only by pages/Help.tsx, which App loads lazily. */
import userGuide from "../../docs/user-guide.md?raw";
import checkPrinting from "../../docs/check-printing.md?raw";
import backupRestore from "../../docs/backup-restore.md?raw";

/** The documents Help can show, by the name used in /help/<name> (and in Markdown links as <name>.md). */
export const HELP_DOCS: Record<string, { title: string; text: string }> = {
  "user-guide": { title: "User guide", text: userGuide },
  "check-printing": { title: "Check printing", text: checkPrinting },
  "backup-restore": { title: "Backup and restore", text: backupRestore },
};

