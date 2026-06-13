/** Parse editable report HTML back into payload fields (remarks, footer values, signatories). */

function cellText(el) {
  return (el?.textContent || '').replace(/\u00a0/g, ' ').trim();
}

function parseDataRowRemarks(table) {
  const remarks = [];
  table.querySelectorAll('tr.ir-data-row').forEach((row, idx) => {
    const cells = row.querySelectorAll('td');
    if (!cells.length) return;
    const last = cells[cells.length - 1];
    remarks.push({ index: idx, text: cellText(last) });
  });
  return remarks;
}

function parseFooterRows(table) {
  const rows = [];
  table.querySelectorAll('tr.ir-footer-row').forEach((row) => {
    const values = Array.from(row.querySelectorAll('td.ir-footer-value')).map(cellText);
    if (values.length >= 3) {
      rows.push({
        chemical: values[0] || '',
        ultrasonic: values[1] || '',
        hardness: values[2] || '',
      });
    }
  });
  return rows;
}

function extractSignatory(cell, label) {
  if (!cell) return '';
  const text = cellText(cell);
  const match = text.match(new RegExp(`^${label}\\s*:?\\s*(.*)$`, 'i'));
  if (match) return (match[1] || '').trim();
  return text.replace(new RegExp(`^${label}\\s*:?`, 'i'), '').trim();
}

function parseSignatories(table) {
  const row = table.querySelector('tr.ir-sign');
  if (!row) return { inspectedBy: '', checkedBy: '' };
  const inspectedCell = row.querySelector('.ir-sign-inspected') || row.querySelector('td:first-child');
  const checkedCell = row.querySelector('.ir-sign-checked') || row.querySelector('td:last-child');
  return {
    inspectedBy: extractSignatory(inspectedCell, 'Inspected by'),
    checkedBy: extractSignatory(checkedCell, 'Checked by'),
  };
}

function parseSheetTable(table) {
  return {
    remarks: parseDataRowRemarks(table),
    footerRows: parseFooterRows(table),
    ...parseSignatories(table),
  };
}

function findSheetTables(doc) {
  const sections = Array.from(doc.querySelectorAll('.ir-consolidated-sheet'));
  if (sections.length) {
    return sections.map((section) => ({
      table: section.querySelector('table.ir-sheet-table') || section.querySelector('table'),
      sheetIndex: Number(section.getAttribute('data-sheet-index') || 0),
    }));
  }
  const table = doc.querySelector('table.ir-sheet-table') || doc.querySelector('table');
  return table ? [{ table, sheetIndex: 0 }] : [];
}

function applyRemarkEdits(rows, remarkEdits) {
  return (rows || []).map((row, idx) => {
    const edit = remarkEdits[idx];
    if (!edit) return { ...row };
    return { ...row, remarks: edit.text };
  });
}

/**
 * Merge editor HTML edits into a report payload copy.
 */
export function mergeReportEditsFromHtml(html, payload) {
  if (!payload) return null;

  const doc = new DOMParser().parseFromString(html || '', 'text/html');
  const sheetTables = findSheetTables(doc);

  if (!sheetTables.length) {
    return { ...payload, rows: [...(payload.rows || [])] };
  }

  if (payload.sheets?.length) {
    const sheets = payload.sheets.map((sheet, index) => {
      const match = sheetTables.find((s) => s.sheetIndex === index) || sheetTables[index];
      if (!match?.table) return { ...sheet };
      const parsed = parseSheetTable(match.table);
      return {
        ...sheet,
        rows: applyRemarkEdits(sheet.rows, parsed.remarks),
        footerRows: parsed.footerRows.length ? parsed.footerRows : sheet.footerRows,
        inspectedBy: parsed.inspectedBy,
        checkedBy: parsed.checkedBy,
      };
    });
    return {
      ...payload,
      sheets,
      rows: sheets.flatMap((s) => s.rows),
      footerRows: sheets[0]?.footerRows ?? payload.footerRows,
      inspectedBy: sheets[0]?.inspectedBy ?? payload.inspectedBy,
      checkedBy: sheets[0]?.checkedBy ?? payload.checkedBy,
      savedAt: new Date().toISOString(),
    };
  }

  const { table } = sheetTables[0];
  const parsed = parseSheetTable(table);
  const rows = applyRemarkEdits(payload.rows, parsed.remarks);

  return {
    ...payload,
    rows,
    footerRows: parsed.footerRows.length ? parsed.footerRows : payload.footerRows,
    inspectedBy: parsed.inspectedBy,
    checkedBy: parsed.checkedBy,
    savedAt: new Date().toISOString(),
  };
}

export function applySavedEditsToPayload(payload, saved) {
  if (!payload || !saved?.saved) return payload;

  if (payload.sheets?.length && saved.sheets?.length) {
    const sheets = payload.sheets.map((sheet, sheetIndex) => {
      const savedSheet = saved.sheets[sheetIndex];
      if (!savedSheet) return sheet;
      const rows = (sheet.rows || []).map((row, idx) => {
        const savedRow = savedSheet.rows?.[idx];
        if (!savedRow || savedRow.remarks == null) return row;
        return { ...row, remarks: savedRow.remarks };
      });
      return {
        ...sheet,
        rows,
        footerRows: savedSheet.footerRows?.length ? savedSheet.footerRows : sheet.footerRows,
        inspectedBy: savedSheet.inspectedBy ?? sheet.inspectedBy ?? '',
        checkedBy: savedSheet.checkedBy ?? sheet.checkedBy ?? '',
      };
    });
    return {
      ...payload,
      sheets,
      rows: sheets.flatMap((s) => s.rows),
      footerRows: saved.footerRows?.length ? saved.footerRows : payload.footerRows,
      inspectedBy: saved.inspectedBy || sheets[0]?.inspectedBy || '',
      checkedBy: saved.checkedBy || sheets[0]?.checkedBy || '',
      savedAt: saved.savedAt || payload.savedAt,
    };
  }

  const rows = (payload.rows || []).map((row, idx) => {
    const savedRow = saved.rows?.[idx];
    if (!savedRow || savedRow.remarks == null) return row;
    return { ...row, remarks: savedRow.remarks };
  });

  let sheets = payload.sheets;
  if (sheets?.length && saved.rows?.length) {
    let offset = 0;
    sheets = sheets.map((sheet) => {
      const nextRows = (sheet.rows || []).map((row, idx) => {
        const savedRow = saved.rows[offset + idx];
        if (!savedRow || savedRow.remarks == null) return row;
        return { ...row, remarks: savedRow.remarks };
      });
      offset += (sheet.rows || []).length;
      return { ...sheet, rows: nextRows };
    });
  }

  return {
    ...payload,
    rows,
    sheets,
    footerRows: saved.footerRows?.length ? saved.footerRows : payload.footerRows,
    inspectedBy: saved.inspectedBy || '',
    checkedBy: saved.checkedBy || '',
    savedAt: saved.savedAt || payload.savedAt,
  };
}

export function reportStorageKey(target, reportQty) {
  if (!target) return null;
  const qty = reportQty === 'consolidated' ? 'consolidated' : String(reportQty);
  return `ir-report:${target.partNumber}:${target.orderId}:${target.opNo}:${qty}`;
}

export function loadSavedReportPayload(key) {
  if (!key) return null;
  try {
    const raw = sessionStorage.getItem(key);
    return raw ? JSON.parse(raw) : null;
  } catch {
    return null;
  }
}

export function persistSavedReportPayload(key, payload) {
  if (!key || !payload) return;
  try {
    sessionStorage.setItem(key, JSON.stringify(payload));
  } catch {
    /* ignore quota errors */
  }
}

export function clearSavedReportPayload(key) {
  if (!key) return;
  try {
    sessionStorage.removeItem(key);
  } catch {
    /* ignore */
  }
}
