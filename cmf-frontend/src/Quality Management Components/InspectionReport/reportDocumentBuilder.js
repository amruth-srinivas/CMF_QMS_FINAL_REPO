export function fmtReportTol(value) {
  const n = Number(value);
  if (!Number.isFinite(n)) return '0';
  if (Math.abs(n) < 1e-12) return '0';
  return n > 0 ? `+${n}` : `${n}`;
}

function esc(value) {
  return String(value ?? '')
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;');
}

function matchStageRow(qtyList, masterId) {
  return qtyList.find((row) => {
    try {
      return JSON.parse(row.bbox || '{}').master_boc_id === masterId;
    } catch {
      return false;
    }
  });
}

function rowFromChar(ch, m, sno) {
  const rowNominal = m ? (m.nominal_value ?? ch.nominal) : ch.nominal;
  const rowUpper = m ? (m.uppertol ?? ch.uppertol) : ch.uppertol;
  const rowLower = m ? (m.lowertol ?? ch.lowertol) : ch.lowertol;
  return {
    sno,
    specified: `${ch.dimension_type || 'Dim'}: ${rowNominal} (${fmtReportTol(rowUpper)}/${fmtReportTol(rowLower)})`,
    zone: ch.zone || '',
    measurements: m?.measurements || [],
    instrument: m?.measured_instrument || ch.measured_instrument || 'default',
    remarks: m?.remarks || '',
  };
}

export function buildRowsForOutcome(chars, outcome) {
  const qtyList = outcome?.data || [];
  return chars.map((ch, idx) => rowFromChar(ch, matchStageRow(qtyList, ch.id), idx + 1));
}

/** @deprecated use buildRowsForOutcome — kept for callers passing flat outcomes */
export function buildReportRows({ chars, outcomes, consolidated }) {
  if (consolidated) {
    return outcomes.map((o) => ({
      qty: o.qty,
      rows: buildRowsForOutcome(chars, o),
    }));
  }
  return buildRowsForOutcome(chars, outcomes[0]);
}

export function buildReportPayload({
  reportRows,
  reportQty,
  partName,
  partNumber,
  orderId,
  opNo,
  projectName,
  assembly,
  qtyMax = 1,
}) {
  const isConsolidated = reportQty === 'consolidated';
  const shared = {
    reportNo: `RPT-${orderId}-${opNo}`,
    componentTitle: partName || '',
    date: new Date().toLocaleDateString(),
    projectNo: String(orderId),
    drgNo: partNumber || '',
    projectName: projectName || '',
    assembly: assembly || 'Main',
  };

  if (isConsolidated) {
    const sheetSources = reportRows;
    const totalSheets = sheetSources.length;
    const sheets = sheetSources.map((source, index) => {
      const rows = source.rows || [];
      const maxSamples = Math.max(3, ...rows.map((r) => (r.measurements || []).length), 0);
      return {
        qty: source.qty,
        rows,
        sheet: `${index + 1} of ${totalSheets}`,
        totalQuantity: String(source.qty),
        maxSamples,
        totalCols: computeTableColumnLayout(false, maxSamples).totalCols,
      };
    });
    const maxSamples = Math.max(3, ...sheets.map((s) => s.maxSamples), 0);
    return {
      ...shared,
      isConsolidated: true,
      sheets,
      rows: sheets.flatMap((s) => s.rows),
      maxSamples,
      totalCols: computeTableColumnLayout(false, maxSamples).totalCols,
      sheet: totalSheets > 1 ? `1 of ${totalSheets}` : '1 of 1',
      totalQuantity: totalSheets > 1 ? `All (1–${totalSheets})` : '1',
    };
  }

  const rows = Array.isArray(reportRows) ? reportRows : [];
  const maxSamples = Math.max(3, ...rows.map((r) => (r.measurements || []).length), 0);
  return {
    ...shared,
    totalQuantity: String(reportQty),
    sheet: '1 of 1',
    rows,
    maxSamples,
    totalCols: computeTableColumnLayout(false, maxSamples).totalCols,
    isConsolidated: false,
  };
}

/** Column spans for the measurement table (must match data rows + headers). */
export function computeTableColumnLayout(isConsolidated, maxSamples) {
  const slCols = 1;
  const specCols = 2;
  const qtyCols = isConsolidated ? 1 : 0;
  const zoneCols = 1;
  const measureCols = maxSamples;
  const instCols = 2;
  const totalCols = slCols + specCols + qtyCols + zoneCols + measureCols + instCols + 4;
  const remCols = totalCols - slCols - specCols - qtyCols - zoneCols - measureCols - instCols;
  return {
    totalCols,
    slCols,
    specCols,
    qtyCols,
    zoneCols,
    measureCols,
    instCols,
    remCols,
  };
}

function normalizeColWidths(widths) {
  const rounded = widths.map((w) => Math.round(w * 10) / 10);
  const diff = Math.round((100 - rounded.reduce((a, b) => a + b, 0)) * 10) / 10;
  if (Math.abs(diff) > 0.001 && rounded.length) {
    rounded[rounded.length - 1] = Math.round((rounded[rounded.length - 1] + diff) * 10) / 10;
  }
  return rounded;
}

/** Column width % — tuned so labels/values do not overlap (sums to 100). */
export function getReportColumnWidths(totalCols, isConsolidated, maxSamples) {
  if (!isConsolidated && maxSamples === 3 && totalCols === 13) {
    return [8, 8, 15, 7, 8, 7, 6, 6, 7, 7, 7, 8, 6];
  }
  const base = 100 / totalCols;
  return Array.from({ length: totalCols }, () => Math.round(base * 100) / 100);
}

export function computeReportLayoutMm(data) {
  const totalCols = data?.totalCols || 13;
  const maxSamples = data?.maxSamples || 3;
  const isConsolidated = Boolean(data?.isConsolidated);
  return {
    totalCols,
    colWidths: getReportColumnWidths(totalCols, isConsolidated, maxSamples),
  };
}

function dataRowHtml(row, layout) {
  const { maxSamples, specCols, instCols, remCols } = layout;
  const cells = Array.from({ length: maxSamples }, (_, mi) => {
    const v = row.measurements?.[mi];
    return `<td><p>${esc(v !== '' && v != null ? v : '')}</p></td>`;
  }).join('');
  return `<tr class="ir-data-row">
    <td><p>${esc(row.sno)}</p></td>
    <td colspan="${specCols}" class="ir-text-left"><p>${esc(row.specified)}</p></td>
    <td class="ir-col-zone"><p>${esc(row.zone)}</p></td>
    ${cells}
    <td colspan="${instCols}"><p>${esc(row.instrument || 'default')}</p></td>
    <td colspan="${remCols}" class="ir-text-left"><p>${esc(row.remarks || '')}</p></td>
  </tr>`;
}

function metaFieldHtml(label, value, colspan) {
  return `<td colspan="${colspan}" class="ir-meta-field ir-text-left"><p><strong>${label}</strong> ${esc(value)}</p></td>`;
}

function splitWidthsIntoThirds(colWidths) {
  const total = colWidths.reduce((a, b) => a + b, 0);
  const t1 = total / 3;
  const t2 = (2 * total) / 3;
  let cum = 0;
  let end1 = 0;
  for (; end1 < colWidths.length; end1 += 1) {
    cum += colWidths[end1];
    if (cum >= t1 - 0.001) break;
  }
  end1 += 1;
  let end2 = end1;
  for (; end2 < colWidths.length; end2 += 1) {
    cum += colWidths[end2];
    if (cum >= t2 - 0.001) break;
  }
  end2 += 1;
  return {
    chemCols: end1,
    ultCols: end2 - end1,
    hardCols: colWidths.length - end2,
  };
}

function signSplitByWidth(colWidths) {
  const total = colWidths.reduce((a, b) => a + b, 0);
  let cum = 0;
  let left = 0;
  for (; left < colWidths.length; left += 1) {
    cum += colWidths[left];
    if (cum >= total / 2 - 0.001) break;
  }
  left += 1;
  return { signLeftCols: left, signRightCols: colWidths.length - left };
}

function labelSpanForSection(sectionCols) {
  return Math.max(1, Math.min(2, Math.round(sectionCols / 2)));
}

/** Label|value per test section; sign row 50/50 by table width. */
export function getFooterLayout(totalCols, colWidths) {
  const widths = colWidths?.length === totalCols ? colWidths : null;
  const sections = widths
    ? splitWidthsIntoThirds(widths)
    : {
        chemCols: Math.floor(totalCols / 3),
        ultCols: Math.floor(totalCols / 3),
        hardCols: totalCols - Math.floor(totalCols / 3) * 2,
      };
  const { chemCols, ultCols, hardCols } = sections;
  const labelW = labelSpanForSection(chemCols);
  const labelW2 = labelSpanForSection(ultCols);
  const labelW3 = labelSpanForSection(hardCols);
  const sign = widths
    ? signSplitByWidth(widths)
    : { signLeftCols: Math.floor(totalCols / 2), signRightCols: totalCols - Math.floor(totalCols / 2) };
  return {
    chemCols,
    ultCols,
    hardCols,
    chunk: chemCols,
    tailCols: hardCols,
    labelW,
    labelW2,
    labelW3,
    valueW1: Math.max(1, chemCols - labelW),
    valueW2: Math.max(1, ultCols - labelW2),
    valueW3: Math.max(1, hardCols - labelW3),
    ...sign,
  };
}

function footerLabelTd(text, span) {
  const spanAttr = span > 1 ? ` colspan="${span}"` : '';
  return `<td${spanAttr} class="ir-footer-label"><p><strong>${text}</strong></p></td>`;
}

function footerDetailRow(label1, label2, label3, layout, values = ['', '', '']) {
  const { labelW, labelW2, labelW3, valueW1, valueW2, valueW3 } = layout;
  const [v1 = '', v2 = '', v3 = ''] = values;
  const valueCell = (text, span) =>
    `<td colspan="${span}" class="ir-footer-value"><p>${text ? esc(text) : '<br>'}</p></td>`;
  return `<tr class="ir-page-footer ir-footer-row">
    ${footerLabelTd(label1, labelW)}
    ${valueCell(v1, valueW1)}
    ${footerLabelTd(label2, labelW2)}
    ${valueCell(v2, valueW2)}
    ${footerLabelTd(label3, labelW3)}
    ${valueCell(v3, valueW3)}
  </tr>`;
}

function footerSignRow(layout, inspectedBy = '', checkedBy = '') {
  const { signLeftCols, signRightCols } = layout;
  const leftValue = inspectedBy ? esc(inspectedBy) : '<br>';
  const rightValue = checkedBy ? esc(checkedBy) : '<br>';
  return `<tr class="ir-page-footer ir-sign">
    <td colspan="${signLeftCols}" class="ir-sign-block ir-sign-inspected"><p><strong>Inspected by:</strong> ${leftValue}</p></td>
    <td colspan="${signRightCols}" class="ir-sign-block ir-sign-checked"><p><strong>Checked by:</strong> ${rightValue}</p></td>
  </tr>`;
}

function footerRowValues(footerRows, index) {
  const row = footerRows?.[index];
  if (!row) return ['', '', ''];
  return [row.chemical || '', row.ultrasonic || '', row.hardness || ''];
}

/** One quantity sheet — standard layout with measured value columns. */
export function buildSingleSheetTableHtml(data) {
  if (!data) return '';

  const maxSamples = data.maxSamples || 3;
  const colLayout = computeTableColumnLayout(false, maxSamples);
  const { totalCols, specCols, instCols, remCols } = colLayout;
  const colWidths = getReportColumnWidths(totalCols, false, maxSamples);
  const layout = getFooterLayout(totalCols, colWidths);

  const bodyRows = (data.rows || [])
    .map((row) => dataRowHtml(row, { maxSamples, ...colLayout }))
    .join('');

  const sampleHead = Array.from({ length: maxSamples }, (_, i) => `<th><p>${i + 1}</p></th>`).join('');
  const colgroup = `<colgroup>${colWidths.map((w) => `<col style="width:${w}%">`).join('')}</colgroup>`;
  const { chemCols, ultCols, hardCols } = layout;

  return `<table class="ir-sheet-table">
    ${colgroup}
    <tbody class="ir-sheet-body">
      <tr class="ir-meta-row">
        ${metaFieldHtml('Report No :', data.reportNo, 4)}
        ${metaFieldHtml('Component Title:', data.componentTitle, 5)}
        ${metaFieldHtml('Date:', data.date, 4)}
      </tr>
      <tr class="ir-meta-row">
        ${metaFieldHtml('Project No.:', data.projectNo, 4)}
        ${metaFieldHtml('Drg No:', data.drgNo, 5)}
        ${metaFieldHtml('Sheet', data.sheet, 4)}
      </tr>
      <tr class="ir-meta-row">
        ${metaFieldHtml('Project Name:', data.projectName, 4)}
        ${metaFieldHtml('Quantity:', data.totalQuantity, 5)}
        ${metaFieldHtml('Assembly', data.assembly, 4)}
      </tr>
      <tr class="ir-head ir-head-main">
        <th><p>Sl No</p></th>
        <th colspan="${specCols}"><p>Specified Values</p></th>
        <th><p>Zone</p></th>
        <th colspan="${colLayout.measureCols}"><p>Measured Values</p></th>
        <th colspan="${instCols}"><p>Instrument</p></th>
        <th colspan="${remCols}"><p>Remarks</p></th>
      </tr>
      <tr class="ir-head ir-head-sub">
        <th><p></p></th>
        <th colspan="${specCols}"><p></p></th>
        <th><p></p></th>
        ${sampleHead}
        <th colspan="${instCols}"><p></p></th>
        <th colspan="${remCols}"><p></p></th>
      </tr>
      ${bodyRows}
      <tr class="ir-page-footer ir-footer-head">
        <td colspan="${chemCols}"><p><strong>Chemical Test</strong></p></td>
        <td colspan="${ultCols}"><p><strong>Ultrasonic Test</strong></p></td>
        <td colspan="${hardCols}"><p><strong>Hardness Test</strong></p></td>
      </tr>
      ${footerDetailRow('Date', 'Date', 'Date', layout, footerRowValues(data.footerRows, 0))}
      ${footerDetailRow('Report No', 'Report No', 'W.O.NO', layout, footerRowValues(data.footerRows, 1))}
      ${footerDetailRow('Authoriser', 'Authoriser', 'Hardness Value', layout, footerRowValues(data.footerRows, 2))}
      ${footerDetailRow('Status', 'Status', 'Status', layout, footerRowValues(data.footerRows, 3))}
      ${footerSignRow(layout, data.inspectedBy || '', data.checkedBy || '')}
    </tbody>
  </table>`;
}

/** Tiptap HTML — compact Word-style report (data rows only, no padding). */
export function buildReportDocumentHtml(data) {
  if (!data) return '<p></p>';

  if (data.sheets?.length) {
    return data.sheets
      .map(
        (sheet, index) =>
          `<div class="ir-consolidated-sheet" data-sheet-index="${index}" data-qty="${esc(sheet.qty)}">${buildSingleSheetTableHtml({
            ...data,
            ...sheet,
            rows: sheet.rows,
          })}</div>`,
      )
      .join('');
  }

  return buildSingleSheetTableHtml(data);
}
