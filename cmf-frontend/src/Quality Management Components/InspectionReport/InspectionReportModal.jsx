import React, { useCallback, useEffect, useRef, useState } from 'react';
import { Button, Modal, Select, Spin, Tag, Typography, message } from 'antd';
import {
  ArrowLeftOutlined,
  CloseOutlined,
  CloudDownloadOutlined,
  CompressOutlined,
  DragOutlined,
  EditOutlined,
  FilePdfOutlined,
  FileTextOutlined,
  PrinterOutlined,
  ReloadOutlined,
  SaveOutlined,
  ZoomInOutlined,
  ZoomOutOutlined,
} from '@ant-design/icons';
import InspectionReportEditor from './InspectionReportEditor';
import { downloadInspectionReportPdf } from './downloadReportPdf';
import {
  mergeReportEditsFromHtml,
} from './reportEdits';
import { useInspectionReport } from './useInspectionReport';
import './inspectionReport.css';

const { Text, Title } = Typography;

const A4_WIDTH_PX = (210 / 25.4) * 96;
const A4_HEIGHT_PX = (297 / 25.4) * 96;
const ZOOM_STEPS = [0.45, 0.55, 0.65, 0.75, 0.85, 0.95, 1];

function clampZoom(value) {
  return Math.min(1, Math.max(0.4, value));
}

function isPanBlockedTarget(target) {
  return Boolean(target?.closest?.('button, a, input, textarea, select, .ant-btn, .ant-select'));
}

/**
 * Self-contained inspection report viewer: PDF-like editable page (Tiptap) + Word export.
 */
export default function InspectionReportModal({
  open,
  target,
  projectName,
  assemblyName,
  autoDownload = false,
  onAutoDownloadDone,
  onClose,
}) {
  const viewportRef = useRef(null);
  const panRef = useRef({ x: 0, y: 0 });
  const panDragRef = useRef({
    pending: false,
    active: false,
    startX: 0,
    startY: 0,
    originX: 0,
    originY: 0,
  });
  const [fitZoom, setFitZoom] = useState(0.75);
  const [manualZoom, setManualZoom] = useState(null);
  const [downloadingWord, setDownloadingWord] = useState(false);
  const [downloadingPdf, setDownloadingPdf] = useState(false);
  const [saving, setSaving] = useState(false);
  const [isDirty, setIsDirty] = useState(false);
  const editorRef = useRef(null);
  const [pan, setPan] = useState({ x: 0, y: 0 });
  const [isPanning, setIsPanning] = useState(false);
  const [handMode, setHandMode] = useState(false);
  const hasCenteredRef = useRef(false);

  useEffect(() => {
    panRef.current = pan;
  }, [pan]);

  const applyPan = useCallback((next) => {
    panRef.current = next;
    setPan(next);
    const stage = viewportRef.current?.querySelector('.ir-canvas-stage');
    if (stage) {
      stage.style.transform = `translate(${next.x}px, ${next.y}px)`;
    }
  }, []);

  const {
    loading,
    payload,
    reportQty,
    setReportQty,
    qtyOptions,
    downloadDocx,
    saveEdits,
    reload,
  } = useInspectionReport({
    target,
    projectName,
    assemblyName,
    enabled: open && !!target,
  });

  const displayPayload = payload;

  useEffect(() => {
    if (!open) {
      setIsDirty(false);
    }
  }, [open]);

  useEffect(() => {
    if (!payload || loading) return;
    setIsDirty(false);
  }, [payload, loading, reportQty]);

  const recomputeFitZoom = useCallback(() => {
    const el = viewportRef.current;
    if (!el) return;
    const { width, height } = el.getBoundingClientRect();
    if (width < 80 || height < 80) return;
    const pad = 32;
    const page = el.querySelector('#inspection-report-print-root');
    const neededH = page?.offsetHeight || A4_HEIGHT_PX;
    const scaleW = (width - pad) / A4_WIDTH_PX;
    const scaleH = (height - pad) / neededH;
    setFitZoom(clampZoom(Math.min(scaleW, scaleH) * 0.98));
  }, []);

  const centerSheet = useCallback(() => {
    const viewport = viewportRef.current;
    if (!viewport) return;
    const host = viewport.querySelector('.ir-zoom-host');
    if (!host) return;
    const vw = viewport.clientWidth;
    const vh = viewport.clientHeight;
    const pw = host.offsetWidth;
    const ph = host.offsetHeight;
    applyPan({
      x: Math.max(24, (vw - pw) / 2),
      y: Math.max(24, (vh - ph) / 2),
    });
    hasCenteredRef.current = true;
  }, [applyPan]);

  useEffect(() => {
    if (!open) {
      setManualZoom(null);
      setHandMode(false);
      hasCenteredRef.current = false;
      applyPan({ x: 0, y: 0 });
      return undefined;
    }
    const id = requestAnimationFrame(recomputeFitZoom);
    window.addEventListener('resize', recomputeFitZoom);
    return () => {
      cancelAnimationFrame(id);
      window.removeEventListener('resize', recomputeFitZoom);
    };
  }, [open, applyPan, payload, loading, reportQty, recomputeFitZoom]);

  useEffect(() => {
    if (!open || !payload || loading) return undefined;
    hasCenteredRef.current = false;
    const t = window.setTimeout(() => {
      recomputeFitZoom();
      centerSheet();
    }, 150);
    return () => window.clearTimeout(t);
  }, [open, payload, loading, reportQty, recomputeFitZoom, centerSheet]);

  useEffect(() => {
    if (!open || !payload || loading) return undefined;
    hasCenteredRef.current = false;
    const t = window.setTimeout(centerSheet, 220);
    return () => window.clearTimeout(t);
  }, [open, payload, loading, manualZoom, fitZoom, centerSheet]);

  useEffect(() => {
    if (!autoDownload || !displayPayload || loading) return;
    (async () => {
      try {
        setDownloadingWord(true);
        await downloadDocx(displayPayload, { useSavedEdits: Boolean(displayPayload.savedAt) });
      } finally {
        setDownloadingWord(false);
        onAutoDownloadDone?.();
      }
    })();
  }, [autoDownload, displayPayload, loading, downloadDocx, onAutoDownloadDone]);

  const zoom = manualZoom ?? fitZoom;
  const zoomPct = Math.round(zoom * 100);
  const isFitMode = manualZoom == null;

  const nudgeZoom = (delta) => {
    const base = manualZoom ?? fitZoom;
    const idx = ZOOM_STEPS.findIndex((s) => s >= base - 0.001);
    const next = ZOOM_STEPS[Math.min(ZOOM_STEPS.length - 1, Math.max(0, (idx < 0 ? 0 : idx) + delta))];
    setManualZoom(next ?? clampZoom(base + delta * 0.1));
  };

  const handleFit = () => {
    setManualZoom(null);
    window.setTimeout(() => {
      recomputeFitZoom();
      centerSheet();
    }, 0);
  };

  useEffect(() => {
    if (!open) return undefined;

    const viewport = () => viewportRef.current;

    const onMouseDown = (event) => {
      const root = viewport();
      if (!root || loading) return;
      if (!root.contains(event.target)) return;
      if (event.button !== 0 && event.button !== 1) return;
      if (isPanBlockedTarget(event.target)) return;

      const onHandle = Boolean(event.target.closest('[data-ir-pan-handle]'));
      const handActive = handMode || event.button === 1;

      // Only pan from grip bar, hand tool, or middle-click — never from normal sheet clicks.
      if (!handActive && !onHandle) return;

      panDragRef.current = {
        pending: false,
        active: true,
        startX: event.clientX,
        startY: event.clientY,
        originX: panRef.current.x,
        originY: panRef.current.y,
      };

      setIsPanning(true);
      event.preventDefault();
      event.stopPropagation();
    };

    const onMouseMove = (event) => {
      const drag = panDragRef.current;
      if (!drag.active) return;

      const dx = event.clientX - drag.startX;
      const dy = event.clientY - drag.startY;

      event.preventDefault();
      applyPan({
        x: drag.originX + dx,
        y: drag.originY + dy,
      });
    };

    const endPan = (event) => {
      const drag = panDragRef.current;
      if (!drag.active) return;
      if (drag.active) event.preventDefault();
      drag.pending = false;
      drag.active = false;
      setIsPanning(false);
    };

    document.addEventListener('mousedown', onMouseDown, true);
    document.addEventListener('mousemove', onMouseMove, { passive: false });
    document.addEventListener('mouseup', endPan);
    return () => {
      document.removeEventListener('mousedown', onMouseDown, true);
      document.removeEventListener('mousemove', onMouseMove);
      document.removeEventListener('mouseup', endPan);
    };
  }, [open, loading, handMode, applyPan]);

  const handlePrint = () => {
    if (!displayPayload) return;
    window.print();
  };

  const handleSave = async () => {
    const html = editorRef.current?.getHtml?.();
    if (!html || !payload) {
      message.warning('Report preview is not ready.');
      return;
    }
    try {
      setSaving(true);
      const merged = mergeReportEditsFromHtml(html, payload);
      await saveEdits(merged);
      setIsDirty(false);
      message.success('Report saved to database. Downloads will include your edits.');
    } catch (err) {
      console.error(err);
      message.error(err.response?.data?.detail || err.message || 'Could not save report edits.');
    } finally {
      setSaving(false);
    }
  };

  const handleReload = async () => {
    setIsDirty(false);
    await reload();
  };

  const handleDownloadWord = async () => {
    if (isDirty) {
      message.warning('Save your changes before downloading Word.');
      return;
    }
    try {
      setDownloadingWord(true);
      await downloadDocx(displayPayload, { useSavedEdits: Boolean(displayPayload?.savedAt) });
    } catch (err) {
      console.error(err);
      message.error(err.response?.data?.detail || err.message || 'Word download failed');
    } finally {
      setDownloadingWord(false);
    }
  };

  const handleDownloadPdf = async () => {
    if (isDirty) {
      message.warning('Save your changes before downloading PDF.');
      return;
    }
    const root = document.getElementById('inspection-report-print-root');
    if (!root || !displayPayload) {
      message.warning('Report preview is not ready.');
      return;
    }
    try {
      setDownloadingPdf(true);
      await downloadInspectionReportPdf(root, `Inspection_Report_${displayPayload.reportNo}.pdf`);
      message.success('PDF report downloaded.');
    } catch (err) {
      console.error(err);
      message.error(err.message || 'PDF download failed');
    } finally {
      setDownloadingPdf(false);
    }
  };

  const partLabel = target?.partNumber || '—';
  const opLabel = target?.opNo ?? '—';
  const qtyLabel = reportQty === 'consolidated' ? 'Consolidated' : `Qty ${reportQty}`;

  return (
    <Modal
      className="ir-modal"
      open={open}
      onCancel={onClose}
      width="100%"
      style={{ top: 0, padding: 0, maxWidth: '100vw' }}
      footer={null}
      destroyOnClose
      closable={false}
      title={null}
      maskClosable
    >
      <div className="ir-layout">
        <aside className="ir-sidebar">
          <div className="ir-sidebar-header">
            <Button
              type="text"
              icon={<ArrowLeftOutlined />}
              className="ir-back-btn"
              onClick={onClose}
            >
              Back
            </Button>
            <Button
              type="text"
              icon={<CloseOutlined />}
              className="ir-close-btn"
              aria-label="Close"
              onClick={onClose}
            />
          </div>

          <div className="ir-sidebar-brand">
            <div className="ir-sidebar-brand-icon-wrap">
              <FileTextOutlined className="ir-sidebar-brand-icon" />
            </div>
            <div className="ir-sidebar-brand-text">
              <Title level={5} className="ir-sidebar-title">Inspection Report</Title>
              <Text type="secondary" className="ir-sidebar-subtitle">A4 editable preview</Text>
            </div>
          </div>

          <div className="ir-sidebar-panel">
            <Text className="ir-sidebar-section-title">Part details</Text>
            <div className="ir-meta-grid">
              <div className="ir-meta-item">
                <Text className="ir-sidebar-label">Part</Text>
                <Text strong className="ir-sidebar-value">{partLabel}</Text>
              </div>
              <div className="ir-meta-item">
                <Text className="ir-sidebar-label">Operation</Text>
                <Text strong className="ir-sidebar-value">Op {opLabel}</Text>
              </div>
            </div>
            <div className="ir-meta-qty">
              <Text className="ir-sidebar-label">Quantity</Text>
              <Select
                size="middle"
                className="ir-sidebar-select"
                value={reportQty}
                options={qtyOptions}
                onChange={setReportQty}
                disabled={loading}
              />
            </div>
          </div>

          <div className="ir-sidebar-panel ir-sidebar-panel--actions">
            <div className="ir-sidebar-actions-head">
              <Text className="ir-sidebar-section-title">Actions</Text>
              {isDirty ? (
                <Tag color="orange" className="ir-status-tag">Unsaved</Tag>
              ) : displayPayload?.savedAt ? (
                <Tag color="success" className="ir-status-tag">Saved</Tag>
              ) : null}
            </div>

            <Button
              block
              size="large"
              type="primary"
              icon={<SaveOutlined />}
              className="ir-save-btn"
              loading={saving}
              disabled={!payload || loading || !isDirty}
              onClick={() => void handleSave()}
            >
              Save changes
            </Button>

            <div className="ir-action-row">
              <Button
                icon={<PrinterOutlined />}
                className="ir-sidebar-btn-secondary"
                onClick={handlePrint}
                disabled={!displayPayload || loading}
              >
                Print
              </Button>
              <Button
                icon={<ReloadOutlined />}
                className="ir-sidebar-btn-secondary"
                onClick={() => void handleReload()}
                loading={loading}
              >
                Reload
              </Button>
            </div>

            <Text className="ir-sidebar-export-label">Export</Text>
            <div className="ir-export-grid">
              <Button
                icon={<FilePdfOutlined />}
                className="ir-sidebar-btn-secondary"
                loading={downloadingPdf}
                disabled={!displayPayload || loading || downloadingWord || isDirty}
                onClick={() => void handleDownloadPdf()}
              >
                PDF
              </Button>
              <Button
                icon={<CloudDownloadOutlined />}
                className="ir-sidebar-btn-secondary"
                loading={downloadingWord}
                disabled={!displayPayload || loading || downloadingPdf || isDirty}
                onClick={() => void handleDownloadWord()}
              >
                Word
              </Button>
            </div>
          </div>

          <div className="ir-sidebar-panel ir-sidebar-panel--view">
            <Text className="ir-sidebar-section-title">View</Text>
            <Button
              block
              type={handMode ? 'primary' : 'default'}
              icon={<DragOutlined />}
              className={handMode ? 'ir-hand-btn--active' : 'ir-sidebar-btn-secondary'}
              onClick={() => setHandMode((v) => !v)}
            >
              {handMode ? 'Hand tool on' : 'Hand tool'}
            </Button>
            <div className="ir-zoom-toolbar">
              <Button
                icon={<ZoomOutOutlined />}
                disabled={zoom <= 0.4}
                onClick={() => nudgeZoom(-1)}
              />
              <button
                type="button"
                className={`ir-zoom-readout${isFitMode ? ' ir-zoom-readout--fit' : ''}`}
                onClick={handleFit}
                title="Reset to fit page"
              >
                {isFitMode ? 'Fit' : `${zoomPct}%`}
              </button>
              <Button
                icon={<ZoomInOutlined />}
                disabled={zoom >= 1}
                onClick={() => nudgeZoom(1)}
              />
              <Button
                icon={<CompressOutlined />}
                title="Fit to screen"
                onClick={handleFit}
              />
            </div>
          </div>

          <Text type="secondary" className="ir-sidebar-footer-hint">
            {handMode
              ? 'Turn off Hand tool to edit cells.'
              : 'Click cells to edit · grip bar to drag sheet.'}
          </Text>
        </aside>

        <section className="ir-workspace">
          <div className="ir-workspace-chrome">
            <div className="ir-workspace-meta">
              <span className={`ir-mode-pill${handMode ? ' ir-mode-pill--pan' : ' ir-mode-pill--edit'}`}>
                {handMode ? <DragOutlined /> : <EditOutlined />}
                {handMode ? 'Pan' : 'Edit'}
              </span>
              <Text className="ir-workspace-breadcrumb">
                {partLabel} · Op {opLabel} · {qtyLabel}
              </Text>
              {isDirty ? (
                <Tag color="orange" className="ir-workspace-tag">Unsaved edits</Tag>
              ) : displayPayload?.savedAt ? (
                <Tag color="success" className="ir-workspace-tag">Saved</Tag>
              ) : null}
            </div>
            <div className="ir-workspace-tools">
              <Text className="ir-workspace-zoom">{isFitMode ? 'Fit' : `${zoomPct}%`}</Text>
            </div>
          </div>

          <div
            ref={viewportRef}
            className={`ir-canvas-viewport${isPanning ? ' ir-canvas-viewport--panning' : ''}${handMode ? ' ir-canvas-viewport--hand' : ''}`}
          >
            <div
              className="ir-canvas-stage"
              style={{ transform: `translate(${pan.x}px, ${pan.y}px)` }}
            >
              <Spin spinning={loading} wrapperClassName="ir-canvas-spin">
                {displayPayload ? (
                  <InspectionReportEditor
                    ref={editorRef}
                    payload={displayPayload}
                    zoom={zoom}
                    handMode={handMode}
                    onDirtyChange={setIsDirty}
                    onLayoutChange={() => {
                      recomputeFitZoom();
                      if (!hasCenteredRef.current) centerSheet();
                    }}
                  />
                ) : (
                  <div className="ir-page ir-a4-sheet ir-page-empty">
                    <Text type="secondary">No report data</Text>
                  </div>
                )}
              </Spin>
            </div>
          </div>
        </section>
      </div>
    </Modal>
  );
}
