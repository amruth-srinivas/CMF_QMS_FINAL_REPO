import React, { forwardRef, useEffect, useImperativeHandle, useMemo, useRef, useState } from 'react';
import { EditorContent, useEditor } from '@tiptap/react';
import StarterKit from '@tiptap/starter-kit';
import { Table } from '@tiptap/extension-table';
import { TableRow } from '@tiptap/extension-table-row';
import { TableCell } from '@tiptap/extension-table-cell';
import { TableHeader } from '@tiptap/extension-table-header';
import TextAlign from '@tiptap/extension-text-align';
import { HolderOutlined } from '@ant-design/icons';
import { buildReportDocumentHtml, computeReportLayoutMm } from './reportDocumentBuilder';
import cmtiReportLogo from '../../assets/cmti-report-logo.png';

function classAttr() {
  return {
    default: null,
    parseHTML: (el) => el.getAttribute('class'),
    renderHTML: (attrs) => (attrs.class ? { class: attrs.class } : {}),
  };
}

const ReportTable = Table.extend({
  addAttributes() {
    return { ...this.parent?.(), class: classAttr() };
  },
});

const ReportTableRow = TableRow.extend({
  addAttributes() {
    return { ...this.parent?.(), class: classAttr() };
  },
});

const ReportTableCell = TableCell.extend({
  addAttributes() {
    return {
      ...this.parent?.(),
      class: classAttr(),
      colwidth: { default: null, renderHTML: () => ({}) },
    };
  },
});

const ReportTableHeader = TableHeader.extend({
  addAttributes() {
    return {
      ...this.parent?.(),
      class: classAttr(),
      colwidth: { default: null, renderHTML: () => ({}) },
    };
  },
});

function applySheetLayout(root, layout) {
  const tables = root?.querySelectorAll('table.ir-sheet-table') || [];
  if (!tables.length) return;

  const totalCols = layout.totalCols || 13;
  const widths = layout.colWidths?.length === totalCols
    ? layout.colWidths
    : Array.from({ length: totalCols }, () => 100 / totalCols);

  tables.forEach((table) => {
    table.style.width = '100%';
    table.style.minWidth = '100%';
    table.style.maxWidth = '100%';
    table.style.tableLayout = 'fixed';
    table.style.borderCollapse = 'collapse';
    table.style.height = 'auto';
    table.style.minHeight = '';

    table.querySelectorAll('colgroup').forEach((g) => g.remove());
    const colgroup = document.createElement('colgroup');
    widths.forEach((pct) => {
      const col = document.createElement('col');
      col.style.width = `${pct}%`;
      colgroup.appendChild(col);
    });
    table.insertBefore(colgroup, table.firstChild);

    table.querySelectorAll('td, th').forEach((cell) => {
      cell.style.width = '';
      cell.style.minWidth = '';
      cell.style.maxWidth = '';
      cell.removeAttribute('colwidth');
    });
  });
}

function ReportBannerHeader() {
  return (
    <table className="ir-header-banner" aria-label="Report header">
      <tbody>
        <tr>
          <td className="ir-logo-cell">
            <img src={cmtiReportLogo} alt="CMTI" className="ir-report-logo" />
          </td>
          <td className="ir-title-cell">
            <strong>INSPECTION REPORT</strong>
          </td>
        </tr>
      </tbody>
    </table>
  );
}

const ReportSheetEditor = forwardRef(function ReportSheetEditor(
  {
    payload,
    sheetIndex = 0,
    printRootId,
    showPanHandle = true,
    zoom = 1,
    handMode = false,
    onDirtyChange,
    onLayoutChange,
    isStacked = false,
  },
  ref,
) {
  const html = useMemo(() => buildReportDocumentHtml(payload), [payload]);
  const layout = useMemo(() => computeReportLayoutMm(payload), [payload]);
  const contentKey = payload
    ? `${payload.reportNo}-${payload.totalQuantity}-${payload.sheet}-${payload.savedAt || ''}-${sheetIndex}`
    : 'empty';
  const pageRef = useRef(null);
  const skipDirtyRef = useRef(false);
  const onDirtyChangeRef = useRef(onDirtyChange);
  const onLayoutChangeRef = useRef(onLayoutChange);
  const [pageSize, setPageSize] = useState({ w: 0, h: 0 });

  useEffect(() => {
    onDirtyChangeRef.current = onDirtyChange;
  }, [onDirtyChange]);

  useEffect(() => {
    onLayoutChangeRef.current = onLayoutChange;
  }, [onLayoutChange]);

  const editor = useEditor({
    immediatelyRender: false,
    extensions: [
      StarterKit.configure({
        heading: false,
        blockquote: false,
        codeBlock: false,
        horizontalRule: false,
        bulletList: false,
        orderedList: false,
        listItem: false,
        dropcursor: false,
        gapcursor: false,
      }),
      TextAlign.configure({ types: ['paragraph'] }),
      ReportTable.configure({ resizable: false }),
      ReportTableRow,
      ReportTableHeader,
      ReportTableCell,
    ],
    editable: true,
    content: '<p></p>',
    editorProps: {
      attributes: {
        class: 'ir-prosemirror',
        spellcheck: 'false',
      },
    },
    onUpdate: () => {
      if (!skipDirtyRef.current) onDirtyChangeRef.current?.(true);
    },
  });

  useEffect(() => {
    if (!editor) return;
    editor.setEditable(!handMode);
  }, [editor, handMode]);

  useImperativeHandle(ref, () => ({
    getHtml: () => editor?.getHTML?.() || '',
    getQty: () => payload?.totalQuantity || payload?.qty,
    getSheetIndex: () => sheetIndex,
  }), [editor, payload, sheetIndex]);

  useEffect(() => {
    if (!editor || !payload) return;
    skipDirtyRef.current = true;
    editor.commands.setContent(html, false);
    onDirtyChangeRef.current?.(false);
    const resetDirtyFlag = window.setTimeout(() => {
      skipDirtyRef.current = false;
    }, 0);
    return () => window.clearTimeout(resetDirtyFlag);
  }, [editor, html, contentKey]);

  useEffect(() => {
    if (!editor || !payload) return;

    const runLayout = () => {
      const root = pageRef.current;
      if (root) {
        applySheetLayout(root, layout);
        const w = root.offsetWidth;
        const h = root.offsetHeight;
        setPageSize({ w, h });
        onLayoutChangeRef.current?.();
      }
    };

    const id1 = requestAnimationFrame(runLayout);
    const id2 = window.setTimeout(runLayout, 50);
    const id3 = window.setTimeout(runLayout, 200);
    return () => {
      cancelAnimationFrame(id1);
      window.clearTimeout(id2);
      window.clearTimeout(id3);
    };
  }, [editor, layout, contentKey, payload]);

  useEffect(() => {
    const root = pageRef.current;
    if (!root || typeof ResizeObserver === 'undefined') return undefined;
    const ro = new ResizeObserver(() => {
      setPageSize({ w: root.offsetWidth, h: root.offsetHeight });
      onLayoutChangeRef.current?.();
    });
    ro.observe(root);
    return () => ro.disconnect();
  }, [contentKey]);

  const PAN_HANDLE_H = showPanHandle && !isStacked ? 48 : 0;
  const hostW = pageSize.w > 0 ? pageSize.w * zoom : undefined;
  const hostH = pageSize.h > 0 ? pageSize.h * zoom + PAN_HANDLE_H : undefined;

  const pageBody = (
    <div
      ref={pageRef}
      id={printRootId}
      className={`ir-page ir-a4-sheet${isStacked ? ' ir-a4-sheet--stacked' : ''}`}
      style={isStacked ? undefined : {
        transform: `scale(${Number(zoom.toFixed(3))})`,
        transformOrigin: 'top left',
      }}
    >
      <div className="ir-sheet-stack">
        <ReportBannerHeader />
        <EditorContent editor={editor} className="ir-editor-root" />
      </div>
    </div>
  );

  if (isStacked) {
    return pageBody;
  }

  return (
    <div
      className={`ir-zoom-host${handMode ? ' ir-zoom-host--hand' : ''}`}
      style={{
        width: hostW ?? `calc(210mm * ${zoom})`,
        height: hostH ?? `calc(297mm * ${zoom})`,
      }}
    >
      {showPanHandle ? (
        <div
          className="ir-sheet-pan-handle"
          data-ir-pan-handle
          title="Drag to move sheet"
        >
          <HolderOutlined />
          <span>Drag to move</span>
        </div>
      ) : null}
      {pageBody}
    </div>
  );
});

const InspectionReportEditor = forwardRef(function InspectionReportEditor(
  { payload, zoom = 1, handMode = false, onLayoutChange, onDirtyChange },
  ref,
) {
  const sheetRefs = useRef([]);
  const isMultiSheet = Boolean(payload?.sheets?.length);

  useImperativeHandle(ref, () => ({
    getHtml: () => {
      if (isMultiSheet) {
        return sheetRefs.current
          .filter(Boolean)
          .sort((a, b) => (a.getSheetIndex?.() ?? 0) - (b.getSheetIndex?.() ?? 0))
          .map((sheetRef) => {
            const index = sheetRef.getSheetIndex?.() ?? 0;
            const qty = sheetRef.getQty?.() ?? index + 1;
            const inner = sheetRef.getHtml?.() || '';
            return `<div class="ir-consolidated-sheet" data-sheet-index="${index}" data-qty="${qty}">${inner}</div>`;
          })
          .join('');
      }
      return sheetRefs.current[0]?.getHtml?.() || '';
    },
  }), [isMultiSheet]);

  if (isMultiSheet) {
    return (
      <div
        className={`ir-zoom-host ir-zoom-host--stack${handMode ? ' ir-zoom-host--hand' : ''}`}
        style={{ width: `calc(210mm * ${zoom})` }}
      >
        <div
          className="ir-sheet-pan-handle"
          data-ir-pan-handle
          title="Drag to move sheets"
        >
          <HolderOutlined />
          <span>Drag to move</span>
        </div>
        <div
          id="inspection-report-print-root"
          className="ir-print-stack"
          style={{
            transform: `scale(${Number(zoom.toFixed(3))})`,
            transformOrigin: 'top left',
          }}
        >
          {payload.sheets.map((sheet, index) => {
            const sheetPayload = {
              ...payload,
              ...sheet,
              rows: sheet.rows,
              isConsolidated: false,
              footerRows: sheet.footerRows ?? payload.footerRows,
              inspectedBy: sheet.inspectedBy ?? payload.inspectedBy,
              checkedBy: sheet.checkedBy ?? payload.checkedBy,
            };
            return (
              <ReportSheetEditor
                key={`sheet-${sheet.qty}`}
                ref={(el) => {
                  sheetRefs.current[index] = el;
                }}
                payload={sheetPayload}
                sheetIndex={index}
                showPanHandle={false}
                handMode={handMode}
                onDirtyChange={onDirtyChange}
                onLayoutChange={onLayoutChange}
                isStacked
              />
            );
          })}
        </div>
      </div>
    );
  }

  return (
    <ReportSheetEditor
      ref={(el) => {
        sheetRefs.current[0] = el;
      }}
      payload={payload}
      printRootId="inspection-report-print-root"
      zoom={zoom}
      handMode={handMode}
      onDirtyChange={onDirtyChange}
      onLayoutChange={onLayoutChange}
    />
  );
});

export default InspectionReportEditor;
