/**
 * Cardbitrage order tracker — Gmail upsert helper (optional).
 *
 * Setup:
 * 1. Import Cardbitrage_Order_Tracker.xlsx into Google Sheets (or create sheets manually).
 * 2. Extensions → Apps Script → paste this file.
 * 3. Set SCRIPT_GMAIL_LABEL and SHEET_ID below.
 * 4. Forward Yahoo tcgplayer.com mail to this Gmail account.
 * 5. Create a Gmail label "cardbitrage/inbox" for forwarded mail.
 * 6. Run createTrigger() once (authorize Gmail + Sheets).
 *
 * Sheets must have tabs: Orders, CK_batches (Cards is manual only).
 */

const SHEET_ID = "PASTE_YOUR_GOOGLE_SHEET_ID_HERE";
const SCRIPT_GMAIL_LABEL = "cardbitrage/inbox";
const PROCESSED_LABEL = "cardbitrage/processed";
const ORDERS_TAB = "Orders";

const TRANSACTIONS_TAB = "Transactions";
const CARDS_TAB = "Cards";

const ORDER_STATUS = {
  confirmation: "Ordered",
  processed: "Ordered",
  shipped: "Shipped",
  delivered: "Delivered",
};

function createTrigger() {
  const triggers = ScriptApp.getProjectTriggers();
  for (const t of triggers) {
    if (t.getHandlerFunction() === "processInbox") ScriptApp.deleteTrigger(t);
  }
  ScriptApp.newTrigger("processInbox").timeBased().everyMinutes(15).create();
}

function processInbox() {
  const ss = SpreadsheetApp.openById(SHEET_ID);
  const sheet = ss.getSheetByName(ORDERS_TAB);
  if (!sheet) throw new Error(`Missing tab: ${ORDERS_TAB}`);

  const processed = GmailApp.getUserLabelByName(PROCESSED_LABEL) || GmailApp.createLabel(PROCESSED_LABEL);
  const threads = GmailApp.search(`label:${SCRIPT_GMAIL_LABEL} -label:${PROCESSED_LABEL}`, 0, 50);

  for (const thread of threads) {
    for (const msg of thread.getMessages()) {
      try {
        upsertFromMessage_(sheet, msg);
      } catch (err) {
        console.error(err);
      }
    }
    thread.addLabel(processed);
  }
}

function upsertFromMessage_(sheet, msg) {
  const subject = msg.getSubject() || "";
  const body = msg.getPlainBody() || "";
  const orderId = extractOrderId_(subject, body);
  if (!orderId) return;

  const headers = sheet.getRange(1, 1, 1, sheet.getLastColumn()).getValues()[0];
  const col = indexMap_(headers);
  const rowNum = findRowByOrderId_(sheet, col.tcg_order_id, orderId);
  const now = msg.getDate();
  const status = inferStatus_(subject);
  const patch = {
    tcg_order_id: orderId,
    seller: extractSeller_(body) || "",
    status: status,
    tracking: extractTracking_(body) || "",
    buy_total: extractBuyTotal_(body) || "",
    last_email_at: now,
    last_email_subject: subject,
  };

  if (status === ORDER_STATUS.confirmation && !rowNum) {
    patch.ordered_on = now;
  }
  if (status === ORDER_STATUS.shipped) {
    patch.shipped_on = now;
  }
  if (status === ORDER_STATUS.delivered) {
    patch.delivered_on = now;
  }

  if (rowNum) {
    updateRow_(sheet, col, rowNum, patch);
  } else {
    appendRow_(sheet, col, patch);
  }
}

function extractOrderId_(subject, body) {
  const html = body || "";
  const text = `${subject}\n${html}`;
  // TCGplayer seller order UUID (processed / shipped emails)
  const uuid = text.match(/Order Number:\s*([A-F0-9]{8}-[A-F0-9]{6}-[A-F0-9]{5})/i);
  if (uuid) return uuid[1].toUpperCase();
  const patterns = [
    /order\s*(?:number|#|no\.?)\s*[:#]?\s*([A-F0-9-]{20,})/i,
    /SearchString=([A-F0-9-]{20,})/i,
  ];
  for (const re of patterns) {
    const m = text.match(re);
    if (m) return m[1].toUpperCase();
  }
  return "";
}

function extractTracking_(body) {
  const usps = body.match(/\b(94\d{20,})\b/);
  if (usps) return usps[1];
  const fedex = body.match(/\b(\d{12,15})\b/);
  return fedex ? fedex[1] : "";
}

function extractSeller_(body) {
  // Processed email: "Mirrodin Card Bazaar $25.99" line before Order Number
  const m = body.match(/([^<\n]+?)\s+\$\d+\.\d{2}\s*(?:<br|\n)\s*Order Number:/i);
  if (m) return m[1].trim();
  const legacy = body.match(/seller\s*:\s*(.+)/i);
  return legacy ? legacy[1].trim().split("\n")[0] : "";
}

function extractBuyTotal_(body) {
  const m = body.match(/([^<\n]+?)\s+\$(\d+\.\d{2})\s*(?:<br|\n)\s*Order Number:/i);
  return m ? parseFloat(m[2]) : "";
}

function inferStatus_(subject) {
  const s = subject.toLowerCase();
  if (s.includes("delivered")) return ORDER_STATUS.delivered;
  if (s.includes("shipped") || s.includes("tracking")) return ORDER_STATUS.shipped;
  if (s.includes("processed")) return ORDER_STATUS.processed;
  return ORDER_STATUS.confirmation;
}

function indexMap_(headers) {
  const map = {};
  headers.forEach((h, i) => {
    map[String(h).trim()] = i + 1;
  });
  return map;
}

function findRowByOrderId_(sheet, col, orderId) {
  if (!col) return 0;
  const last = sheet.getLastRow();
  if (last < 2) return 0;
  const values = sheet.getRange(2, col, last - 1, 1).getValues();
  for (let i = 0; i < values.length; i++) {
    if (String(values[i][0]) === String(orderId)) return i + 2;
  }
  return 0;
}

function updateRow_(sheet, col, rowNum, patch) {
  for (const [key, value] of Object.entries(patch)) {
    const c = col[key];
    if (!c || value === "" || value === null) continue;
    const existing = sheet.getRange(rowNum, c).getValue();
    if (key === "status" && existing === "Sent to CK") continue;
    if (key === "status" && existing === "Done") continue;
    sheet.getRange(rowNum, c).setValue(value);
  }
}

function appendRow_(sheet, col, patch) {
  const width = sheet.getLastColumn();
  const row = new Array(width).fill("");
  for (const [key, value] of Object.entries(patch)) {
    const c = col[key];
    if (c) row[c - 1] = value;
  }
  if (col.simplified_lot && patch.seller) {
    row[col.simplified_lot - 1] = slugify_(patch.seller);
  }
  sheet.appendRow(row);
}

function slugify_(text) {
  return String(text)
    .toLowerCase()
    .replace(/['']/g, "")
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-|-$/g, "");
}
