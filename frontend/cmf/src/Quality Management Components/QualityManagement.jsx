import React, { useState, useEffect, useMemo } from 'react';
import { Layout, Button, Modal, Table, Spin, Drawer, message, Select, Alert, Tooltip, Tabs } from 'antd';
import { useNavigate, useSearchParams, useLocation } from 'react-router-dom';
import { MenuOutlined, AppstoreOutlined, ShoppingCartOutlined, ClusterOutlined, ToolOutlined, InfoCircleOutlined, EyeOutlined, BuildOutlined, CheckCircleOutlined, CloudDownloadOutlined, EditOutlined, FilePdfOutlined } from "@ant-design/icons";
import QualityManagementBOM from './QualityManagementBOM';
import { Card, Tag, Typography, Empty, Space } from 'antd';
import axios from 'axios';
import { QUALITY_API_BASE_URL } from '../Config/qualityconfig';

const { Sider, Content } = Layout;
const { Text, Title } = Typography;

/** Matches new "Balloon document" uploads and legacy BALOON / typo baloon. */
function isBalloonOperationDocument(d) {
  if (!d) return false;
  const t = String(d.document_type || '').trim().toLowerCase();
  return t === 'baloon' || t === 'balloon' || t.includes('balloon');
}

/** PDF iframes in preview/review: hide toolbar and left thumbnail/outline pane (Adobe-style open params). */
function pdfEmbedSrcForReview(url) {
  if (!url) return '';
  const base = url.split('#')[0];
  return `${base}#toolbar=0&navpanes=0&pagemode=none`;
}

const QualityManagement = ({ initialProductId, initialOrderId, fromOms }) => {
  const navigate = useNavigate();
  const location = useLocation();
  const [searchParams] = useSearchParams();
  const orderIdFromQuery = searchParams.get('orderId');
  const productIdFromQuery = searchParams.get('productId');
  const qmsInspectorBase = location.pathname.startsWith('/supervisor')
    ? '/supervisor/qms-inspector'
    : '/admin/qms-inspector';
  const isSupervisorView = location.pathname.startsWith('/supervisor');
  const effectiveOrderId =
    initialOrderId && String(initialOrderId) !== 'null' && String(initialOrderId) !== ''
      ? initialOrderId
      : orderIdFromQuery || undefined;
  const effectiveProductId =
    initialProductId != null &&
    String(initialProductId) !== '' &&
    String(initialProductId) !== 'null'
      ? initialProductId
      : productIdFromQuery && String(productIdFromQuery) !== 'null'
        ? Number(productIdFromQuery)
        : null;
  const [selectedItem, setSelectedItem] = useState(null);
  const [isMobile, setIsMobile] = useState(window.innerWidth < 768);
  const [mobileDrawerOpen, setMobileDrawerOpen] = useState(false);
  const [productHierarchies, setProductHierarchies] = useState({});
  const [operations, setOperations] = useState([]);
  const [partDocuments, setPartDocuments] = useState([]);
  const [loadingDetails, setLoadingDetails] = useState(false);
   const [previewUrl, setPreviewUrl] = useState(null);
  const [previewIsPdf, setPreviewIsPdf] = useState(false);
  const [previewTitle, setPreviewTitle] = useState("");
  const [previewModalVisible, setPreviewModalVisible] = useState(false);
  const [orderStatus, setOrderStatus] = useState(() => (effectiveOrderId ? 'checking' : 'active'));
  const [isCheckingStatus, setIsCheckingStatus] = useState(() => !!effectiveOrderId);
  /** op_no (int) -> 'draft' | 'confirmed' from quality.inspection_plan_status */
  const [inspectionPlanByOp, setInspectionPlanByOp] = useState({});
  /** op_no -> username who confirmed (when status is confirmed) */
  const [inspectionPlanConfirmedByOp, setInspectionPlanConfirmedByOp] = useState({});
  /** op_no -> ftp_status row status (pending/approved/rejected/null) */
  const [ftpStatusByOp, setFtpStatusByOp] = useState({});
  const [planViewOpen, setPlanViewOpen] = useState(false);
  const [planViewLoading, setPlanViewLoading] = useState(false);
  const [planDrawingUrl, setPlanDrawingUrl] = useState(null);
  const [planDrawingIsPdf, setPlanDrawingIsPdf] = useState(true);
  const [planDrawingFileName, setPlanDrawingFileName] = useState(null);
  const [planTableRows, setPlanTableRows] = useState([]);
  const [planViewTitle, setPlanViewTitle] = useState('');
  const [planViewMeta, setPlanViewMeta] = useState(null);
  /** Confirmed plan with no stage measurements yet — show Edit to open QMS Inspector for BOC changes. */
  const [planViewCanEditBoc, setPlanViewCanEditBoc] = useState(false);
  const [planViewOperationRecord, setPlanViewOperationRecord] = useState(null);
  const [planBalloonDocumentId, setPlanBalloonDocumentId] = useState(null);
  const [measureModalOpen, setMeasureModalOpen] = useState(false);
  const [measureModalLoading, setMeasureModalLoading] = useState(false);
  const [measureRows, setMeasureRows] = useState([]);
  const [measureQtyOptions, setMeasureQtyOptions] = useState([{ value: 1, label: 'Qty 1' }]);
  const [measureQty, setMeasureQty] = useState(1);
  const [measureContext, setMeasureContext] = useState(null);
  /** FTP status for the operation shown in Measurements modal (quality.ftp_status) */
  const [measureFtpStatus, setMeasureFtpStatus] = useState(null);
  /** Bump to reload ensure + rows after supervisor approves FTP while modal is open */
  const [measureLoadNonce, setMeasureLoadNonce] = useState(0);
  /** Supervisor: preview Qty 1 measurements before confirming FTP approval */
  const [ftpApproveModalOpen, setFtpApproveModalOpen] = useState(false);
  const [ftpApproveLoading, setFtpApproveLoading] = useState(false);
  const [ftpApproveRows, setFtpApproveRows] = useState([]);
  const [ftpApproveContext, setFtpApproveContext] = useState(null);
  
  const [partInspectionModalOpen, setPartInspectionModalOpen] = useState(false);
  const [partInspectionLoading, setPartInspectionLoading] = useState(false);
  const [partInspectionSummaryByOp, setPartInspectionSummaryByOp] = useState({});

  const handleOpenPartInspection = async () => {
    if (!selectedItem || !effectiveOrderId || String(effectiveOrderId) === 'null') {
      message.warning('Please select a part and ensure an order is active.');
      return;
    }
    setPartInspectionModalOpen(true);
    setPartInspectionLoading(true);
    const partPk = selectedItem.id;
    const oid = Number(effectiveOrderId);
    const results = {};
    try {
      await Promise.all(
        operations.map(async (op) => {
          const opNo = parseOpNo(op);
          try {
            const res = await axios.get(`${QUALITY_API_BASE_URL}/quality/stage-inspection/measurement-summary`, {
              params: { part_id: partPk, sale_order_id: oid, op_no: opNo },
            });
            results[opNo] = {
              opNo,
              opName: op.operation_name,
              ...res.data
            };
          } catch (err) {
            console.warn(`Summary failed for Op ${opNo}:`, err);
          }
        })
      );
      setPartInspectionSummaryByOp(results);
    } catch (err) {
      console.error(err);
      message.error('Failed to load part inspection summary');
    } finally {
      setPartInspectionLoading(false);
    }
  };

  const handleOpenPartReport = () => {
    message.info('Part Quality Report is being generated as a consolidated PDF summary.');
  };

  const handleGenerateReport = (record) => {
    message.loading(`Generating inspection report for Operation ${record.operation_number}...`, 2);
    setTimeout(() => {
      message.success(`Inspection report for ${record.operation_name} is ready for download.`);
    }, 2000);
  };

  useEffect(() => {
    const oid = effectiveOrderId;
    if (oid && String(oid) !== 'null') {
      const checkOrderStatus = async () => {
        setIsCheckingStatus(true);
        try {
          const res = await axios.get(`${QUALITY_API_BASE_URL}/scheduling/order-status/${oid}`);
          setOrderStatus(res.data.order_status);
        } catch (error) {
          console.error("Error checking order status:", error);
          setOrderStatus('error');
        } finally {
          setIsCheckingStatus(false);
        }
      };
      checkOrderStatus();
    } else {
      setOrderStatus('active'); // No order ID means general access or handled by PDM
      setIsCheckingStatus(false);
    }
  }, [effectiveOrderId]);

  useEffect(() => {
    if (selectedItem && selectedItem.itemType === 'part') {
      fetchDetails(selectedItem);
    } else {
      setOperations([]);
      setPartDocuments([]);
      setInspectionPlanByOp({});
      setInspectionPlanConfirmedByOp({});
      setFtpStatusByOp({});
      setPreviewUrl(null);
      setPreviewModalVisible(false);
    }
  }, [selectedItem, effectiveOrderId]);

  const parseOpNo = (record) => {
    const n = Number(String(record?.operation_number ?? '').trim());
    return Number.isFinite(n) ? n : 10;
  };

  const buildFtpIpid = (partNo, opNo) => {
    const pn = (partNo || 'PART').toString().trim().replace(/[^A-Za-z0-9_-]+/g, '_');
    const op = Number.isFinite(Number(opNo)) ? Number(opNo) : 'NA';
    return `FTP_${pn}_OP_${op}`;
  };

  const fetchDetails = async (item) => {
    const partId = item.id;
    setLoadingDetails(true);
    try {
      const [opsRes, docsRes] = await Promise.all([
        axios.get(`${QUALITY_API_BASE_URL}/operations/part/${partId}`),
        axios.get(`${QUALITY_API_BASE_URL}/documents/part/${partId}`)
      ]);
      const ops = opsRes.data || [];
      const docs = docsRes.data || [];
      setOperations(ops);
      setPartDocuments(docs);

      const oid = effectiveOrderId && String(effectiveOrderId) !== 'null' ? Number(effectiveOrderId) : null;
      const pn = item.part_number;
      if (oid && !Number.isNaN(oid) && pn) {
        try {
          const ps = await axios.get(`${QUALITY_API_BASE_URL}/quality/inspection-plan-status`, {
            params: { part_number: pn, sales_order_id: oid },
          });
          const map = {};
          const byMap = {};
          (Array.isArray(ps.data) ? ps.data : []).forEach((r) => {
            if (r && r.op_no != null) {
              map[r.op_no] = r.status;
              byMap[r.op_no] = r.confirmed_by_username || null;
            }
          });
          setInspectionPlanByOp(map);
          setInspectionPlanConfirmedByOp(byMap);
        } catch {
          setInspectionPlanByOp({});
          setInspectionPlanConfirmedByOp({});
        }
        try {
          const ftpPairs = await Promise.all(
            ops.map(async (op) => {
              const opNo = parseOpNo(op);
              const ipid = buildFtpIpid(pn, opNo);
              try {
                const r = await axios.get(`${QUALITY_API_BASE_URL}/quality/ftp-status`, {
                  params: { order_id: oid, ipid, op_no: opNo },
                });
                return [opNo, r.data?.status || null];
              } catch {
                return [opNo, null];
              }
            }),
          );
          setFtpStatusByOp(Object.fromEntries(ftpPairs));
        } catch {
          setFtpStatusByOp({});
        }
      } else {
        setInspectionPlanByOp({});
        setInspectionPlanConfirmedByOp({});
        setFtpStatusByOp({});
      }
      
      // Auto-set the first part 2D drawing as default preview
      const partDrawing = docs.find(d => d.document_type?.toLowerCase().includes('2d'));
      if (partDrawing) {
        setPreviewUrl(partDrawing.document_url);
        setPreviewIsPdf(partDrawing.document_url?.toLowerCase().endsWith('.pdf'));
      }
    } catch (error) {
      console.error("Error fetching details:", error);
    } finally {
      setLoadingDetails(false);
    }
  };

  const getDrawingInfo = (op) => {
    const isDrawing = (d) => {
      if (!d) return false;
      if (isBalloonOperationDocument(d)) return false;
      const type = (d.document_type || "").toLowerCase();
      const name = (d.document_name || "").toLowerCase();
      const isPdfFile = name.toLowerCase().endsWith('.pdf') || type.includes('pdf');
      return type.includes('2d') || type.includes('drawing') || name.includes('drawing') || isPdfFile || name.includes('.png') || name.includes('.jpg') || name.includes('.jpeg');
    };

    const nonBalloonOpDocs = (op.operation_documents || []).filter((d) => !isBalloonOperationDocument(d));
    const nonBalloonPartDocs = partDocuments.filter((d) => !isBalloonOperationDocument(d));
    const partDrawing = nonBalloonPartDocs.find(isDrawing);
    const opDrawing = nonBalloonOpDocs.find(isDrawing);
    const previewDrawing =
      opDrawing || partDrawing ||
      nonBalloonOpDocs[0] || nonBalloonPartDocs[0] ||
      (op.operation_documents || [])[0] || partDocuments[0];

    if (!previewDrawing) return { url: null, isPdf: false, name: '', apiDocumentId: null };

    const isPdf =
      (previewDrawing.document_name || "").toLowerCase().endsWith('.pdf') ||
      (previewDrawing.document_type || "").toLowerCase().includes('pdf');

    const endpoint = previewDrawing.operation_id != null ? 'operation-documents' : 'documents';

    const apiDocumentId = partDrawing?.id ?? previewDrawing.id;

    return {
      url: `${QUALITY_API_BASE_URL}/${endpoint}/${previewDrawing.id}/preview`,
      isPdf,
      name: previewDrawing.document_name,
      apiDocumentId,
    };
  };

  const handlePreviewOperation = (op) => {
    setPreviewTitle(`Operation ${op.operation_number}: ${op.operation_name}`);
    const { url, isPdf } = getDrawingInfo(op);
    setPreviewUrl(url);
    setPreviewIsPdf(isPdf);
    setPreviewModalVisible(true);
  };

  const closePlanViewModal = () => {
    setPlanViewOpen(false);
    setPlanViewCanEditBoc(false);
    setPlanViewOperationRecord(null);
    setPlanBalloonDocumentId(null);
  };

  const openConfirmedPlanModal = async (record, opNo) => {
    const oid = effectiveOrderId && String(effectiveOrderId) !== 'null' ? Number(effectiveOrderId) : null;
    const partNo = selectedItem?.part_number;
    const partPk = selectedItem?.id;
    if (!oid || !partNo) {
      message.error('Order and part are required to view the confirmed plan.');
      return;
    }
    setPlanViewTitle(`Operation ${record.operation_number}: ${record.operation_name}`);
    setPlanViewMeta({
      opNo: record.operation_number,
      opName: record.operation_name,
      partNo: selectedItem?.part_number || '',
      orderNo: effectiveOrderId ? String(effectiveOrderId) : '',
      operationId: record.id,
    });
    setPlanViewOperationRecord(record);
    setPlanViewCanEditBoc(false);
    setPlanBalloonDocumentId(null);
    setPlanViewOpen(true);
    setPlanViewLoading(true);
    setPlanDrawingFileName(null);
    setPlanDrawingIsPdf(true);
    try {
      const [docsRes, bocRes] = await Promise.all([
        axios.get(`${QUALITY_API_BASE_URL}/operation-documents/operation/${record.id}`),
        axios.get(`${QUALITY_API_BASE_URL}/quality/master-boc`, {
          params: { part_id: partNo, sales_order_id: oid, op_no: opNo },
        }),
      ]);
      const docs = Array.isArray(docsRes.data) ? docsRes.data : [];
      const baloonDoc = docs
        .filter(isBalloonOperationDocument)
        .sort((a, b) => Number(b?.id || 0) - Number(a?.id || 0))[0];
      const name = baloonDoc?.document_name || '';
      const isPdf = /\.pdf$/i.test(name);
      setPlanDrawingIsPdf(isPdf);
      setPlanDrawingFileName(name || null);
      setPlanDrawingUrl(baloonDoc ? `${QUALITY_API_BASE_URL}/operation-documents/${baloonDoc.id}/preview` : null);
      setPlanBalloonDocumentId(baloonDoc?.id ?? null);
      setPlanTableRows(Array.isArray(bocRes.data) ? bocRes.data : []);

      let canEditBoc = false;
      if (partPk) {
        try {
          const sumRes = await axios.get(`${QUALITY_API_BASE_URL}/quality/stage-inspection/measurement-summary`, {
            params: { part_id: partPk, sale_order_id: oid, op_no: opNo },
          });
          canEditBoc = !sumRes.data?.any_recorded;
        } catch {
          canEditBoc = false;
        }
      }
      setPlanViewCanEditBoc(canEditBoc);
    } catch (err) {
      console.error(err);
      const detail = err.response?.data?.detail;
      message.error(typeof detail === 'string' ? detail : err.message || 'Failed to load confirmed plan');
      setPlanDrawingUrl(null);
      setPlanDrawingFileName(null);
      setPlanDrawingIsPdf(true);
      setPlanTableRows([]);
      setPlanViewCanEditBoc(false);
      setPlanBalloonDocumentId(null);
    } finally {
      setPlanViewLoading(false);
    }
  };

  const handleEditPlanFromViewModal = async () => {
    const record = planViewOperationRecord;
    if (!record || !selectedItem || !effectiveOrderId || String(effectiveOrderId) === 'null') {
      message.error('Missing context to open the inspector.');
      return;
    }
    const opNo = parseOpNo(record);
    const oid = Number(effectiveOrderId);
    try {
      await axios.put(`${QUALITY_API_BASE_URL}/quality/inspection-plan-status`, {
        part_number: selectedItem.part_number,
        sales_order_id: oid,
        op_no: opNo,
        status: 'draft',
      });
      setInspectionPlanByOp((prev) => ({ ...prev, [opNo]: 'draft' }));
      setInspectionPlanConfirmedByOp((prev) => ({ ...prev, [opNo]: null }));
    } catch (err) {
      console.error(err);
      const detail = err.response?.data?.detail;
      message.error(typeof detail === 'string' ? detail : err.message || 'Could not reopen the plan for editing');
      return;
    }

    const hierarchy = productHierarchies[selectedItem.productId];
    const projectName = hierarchy?.product?.product_name || '';
    const partName = selectedItem.part_name || '';
    const opParts = [];
    if (record.operation_number != null && record.operation_number !== '') opParts.push(String(record.operation_number));
    if (record.operation_name) opParts.push(record.operation_name);
    const opLabel = opParts.join(': ');
    const fallback = getDrawingInfo(record);
    const finalUrl = planDrawingUrl || fallback.url || '';
    const finalIsPdf = planDrawingUrl ? planDrawingIsPdf : fallback.isPdf;
    const finalName = planDrawingFileName || fallback.name || '';
    const finalDocId = planBalloonDocumentId != null ? planBalloonDocumentId : fallback.apiDocumentId;

    const qs = new URLSearchParams({
      drawingUrl: finalUrl || '',
      isPdf: String(!!finalIsPdf),
      fileName: finalName || '',
      projectName,
      partName,
      operationName: opLabel,
      partId: String(selectedItem.id),
      partNumber: selectedItem.part_number || '',
      operationNumber: String(record.operation_number ?? ''),
      operationId: String(record.id),
      orderId: String(effectiveOrderId),
    });
    if (finalDocId != null) qs.set('documentId', String(finalDocId));
    closePlanViewModal();
    navigate(`${qmsInspectorBase}?${qs.toString()}`);
  };

  const handleDownloadPlanDrawing = () => {
    if (!planDrawingUrl) return;
    const id = planDrawingUrl.match(/operation-documents\/(\d+)\//)?.[1];
    if (!id) return;
    const a = document.createElement('a');
    a.href = `${QUALITY_API_BASE_URL}/operation-documents/${id}/download`;
    a.target = '_blank';
    a.rel = 'noopener noreferrer';
    a.download = planDrawingFileName || `operation_${planViewMeta?.opNo || 'plan'}_balloon.pdf`;
    a.click();
  };

  /** Empty string must not become 0 — `Number('') === 0` in JavaScript. */
  const parseNum = (value) => {
    if (value == null) return null;
    const s = String(value).replace(',', '.').trim();
    if (s === '' || s === '—' || s === '-') return null;
    const n = Number(s);
    return Number.isFinite(n) ? n : null;
  };

  /** At least one of #1–#3 has a numeric reading (empty strings do not count). */
  const rowHasMeasured123 = (r) => {
    const a = parseNum(r.measured_1);
    const b = parseNum(r.measured_2);
    const c = parseNum(r.measured_3);
    return a != null || b != null || c != null;
  };

  /** Prefer mean from #1–#3 only; if all empty, no mean (avoids bogus 0 from stored measured_mean). */
  const computeMeanFromMeasurements = (r) => {
    const a = parseNum(r.measured_1);
    const b = parseNum(r.measured_2);
    const c = parseNum(r.measured_3);
    const vals = [a, b, c].filter((v) => v != null);
    if (!vals.length) return null;
    const m = vals.reduce((x, y) => x + y, 0) / vals.length;
    return Number.isFinite(m) ? m : null;
  };

  const fmt4 = (value) => {
    const n = parseNum(value);
    return n == null ? '—' : n.toFixed(4);
  };

  const measureDecoratedRows = useMemo(() => {
    return (measureRows || []).map((r) => {
      const nominal = parseNum(r.nominal_value);
      const upper = parseNum(r.uppertol);
      const lower = parseNum(r.lowertol);
      const mean = computeMeanFromMeasurements(r);
      const upperLimit = nominal != null && upper != null ? nominal + upper : null;
      const lowerLimit = nominal != null && lower != null ? nominal + lower : null;
      const hasTolerance = Math.abs(upper || 0) > 1e-12 || Math.abs(lower || 0) > 1e-12;
      const withinTolerance =
        hasTolerance &&
        mean != null &&
        upperLimit != null &&
        lowerLimit != null &&
        mean <= upperLimit &&
        mean >= lowerLimit;
      const outOfTolerance = hasTolerance && mean != null && !withinTolerance;
      const status = !hasTolerance ? 'no_tolerance' : withinTolerance ? 'within' : outOfTolerance ? 'out' : 'pending';
      return { ...r, _upperLimit: upperLimit, _lowerLimit: lowerLimit, _computedMean: mean, _status: status };
    });
  }, [measureRows]);

  /** Every BOC row for the selected quantity has #1–#3 empty — no real measurements yet. */
  const measureAllReadingsEmpty = useMemo(() => {
    if (!measureRows?.length) return false;
    return measureRows.every((r) => !rowHasMeasured123(r));
  }, [measureRows]);

  const measureSummary = useMemo(() => {
    const total = measureDecoratedRows.length;
    const within = measureDecoratedRows.filter((r) => r._status === 'within').length;
    const out = measureDecoratedRows.filter((r) => r._status === 'out').length;
    const noTol = measureDecoratedRows.filter((r) => r._status === 'no_tolerance').length;
    const passRate = total ? ((within / total) * 100).toFixed(1) : '0.0';
    return { total, within, out, noTol, passRate };
  }, [measureDecoratedRows]);

  const ftpApproveDecoratedRows = useMemo(() => {
    return (ftpApproveRows || []).map((r) => {
      const nominal = parseNum(r.nominal_value);
      const upper = parseNum(r.uppertol);
      const lower = parseNum(r.lowertol);
      const mean = computeMeanFromMeasurements(r);
      const upperLimit = nominal != null && upper != null ? nominal + upper : null;
      const lowerLimit = nominal != null && lower != null ? nominal + lower : null;
      const hasTolerance = Math.abs(upper || 0) > 1e-12 || Math.abs(lower || 0) > 1e-12;
      const withinTolerance =
        hasTolerance &&
        mean != null &&
        upperLimit != null &&
        lowerLimit != null &&
        mean <= upperLimit &&
        mean >= lowerLimit;
      const outOfTolerance = hasTolerance && mean != null && !withinTolerance;
      const status = !hasTolerance ? 'no_tolerance' : withinTolerance ? 'within' : outOfTolerance ? 'out' : 'pending';
      return { ...r, _upperLimit: upperLimit, _lowerLimit: lowerLimit, _computedMean: mean, _status: status };
    });
  }, [ftpApproveRows]);

  const ftpApproveAllReadingsEmpty = useMemo(() => {
    if (!ftpApproveRows?.length) return false;
    return ftpApproveRows.every((r) => !rowHasMeasured123(r));
  }, [ftpApproveRows]);

  const ftpApproveSummary = useMemo(() => {
    const total = ftpApproveDecoratedRows.length;
    const within = ftpApproveDecoratedRows.filter((r) => r._status === 'within').length;
    const out = ftpApproveDecoratedRows.filter((r) => r._status === 'out').length;
    const noTol = ftpApproveDecoratedRows.filter((r) => r._status === 'no_tolerance').length;
    const passRate = total ? ((within / total) * 100).toFixed(1) : '0.0';
    return { total, within, out, noTol, passRate };
  }, [ftpApproveDecoratedRows]);

  const openFtpApproveModal = async (record) => {
    const oid = effectiveOrderId && String(effectiveOrderId) !== 'null' ? Number(effectiveOrderId) : null;
    if (!oid || !selectedItem?.part_number || !selectedItem?.id) {
      message.error('Order and part are required to review FTP.');
      return;
    }
    const opNo = parseOpNo(record);
    setFtpApproveContext({
      opNo,
      opName: record?.operation_name || '',
      partNo: selectedItem.part_number,
      partId: selectedItem.id,
      orderId: oid,
    });
    setFtpApproveModalOpen(true);
    setFtpApproveRows([]);
    setFtpApproveLoading(true);

    // Prepare for drawing view
    setPlanDrawingUrl(null);
    setPlanDrawingFileName(null);
    setPlanDrawingIsPdf(true);

    const ipid = buildFtpIpid(selectedItem.part_number, opNo);
    try {
      // Ensure records exist
      try {
        await axios.post(`${QUALITY_API_BASE_URL}/quality/stage-inspection/ensure`, null, {
          params: {
            part_id: selectedItem.id,
            part_number: selectedItem.part_number,
            sale_order_id: oid,
            op_no: opNo,
            quantity_no: 1,
            ipid,
            user_id: 1,
          },
        });
      } catch (ensureErr) {
        console.warn('stage-inspection/ensure', ensureErr);
      }

      // Fetch measurements and balloon documents in parallel
      const [res, docsRes] = await Promise.all([
        axios.get(`${QUALITY_API_BASE_URL}/quality/stage-inspection`, {
          params: {
            part_id: selectedItem.id,
            sale_order_id: oid,
            op_no: opNo,
            quantity_no: 1,
          },
        }),
        axios.get(`${QUALITY_API_BASE_URL}/operation-documents/operation/${record.id}`),
      ]);

      setFtpApproveRows(Array.isArray(res.data) ? res.data : []);

      // Handle ballooned drawing
      const docs = Array.isArray(docsRes.data) ? docsRes.data : [];
      const baloonDoc = docs
        .filter(isBalloonOperationDocument)
        .sort((a, b) => Number(b?.id || 0) - Number(a?.id || 0))[0];

      if (baloonDoc) {
        const name = baloonDoc.document_name || '';
        setPlanDrawingIsPdf(/\.pdf$/i.test(name));
        setPlanDrawingFileName(name || null);
        setPlanDrawingUrl(`${QUALITY_API_BASE_URL}/operation-documents/${baloonDoc.id}/preview`);
      }
    } catch (err) {
      console.error(err);
      const detail = err.response?.data?.detail;
      message.error(typeof detail === 'string' ? detail : err.message || 'Failed to load quantity 1 measurements/drawing');
      setFtpApproveRows([]);
    } finally {
      setFtpApproveLoading(false);
    }
  };

  const runFtpApprovalApi = async (opNo) => {
    const oid = effectiveOrderId && String(effectiveOrderId) !== 'null' ? Number(effectiveOrderId) : null;
    const partNo = selectedItem?.part_number;
    if (!oid || !partNo) {
      message.error('Missing order/part for FTP approval.');
      return;
    }
    await axios.put(`${QUALITY_API_BASE_URL}/quality/ftp-status`, {
      order_id: oid,
      ipid: buildFtpIpid(partNo, opNo),
      status: 'approved',
      is_completed: true,
    });
    setFtpStatusByOp((prev) => ({ ...prev, [opNo]: 'approved' }));
    message.success(`FTP approved for operation ${opNo}.`);
    if (measureModalOpen && measureContext?.opNo === opNo) {
      setMeasureFtpStatus('approved');
      setMeasureLoadNonce((n) => n + 1);
    }
  };

  const confirmAndApproveFtp = () => {
    const opNo = ftpApproveContext?.opNo;
    if (opNo == null) return;
    Modal.confirm({
      title: 'Confirm FTP approval',
      content:
        'You are approving first-time pass (FTP) for this operation based on quantity 1 measurements. Operators will be allowed to record quantity 2 and above. This action should match your shop-floor sign-off.',
      okText: 'Yes, approve FTP',
      cancelText: 'Back',
      okButtonProps: { type: 'primary' },
      onOk: async () => {
        try {
          await runFtpApprovalApi(opNo);
          setFtpApproveModalOpen(false);
          setFtpApproveContext(null);
          setFtpApproveRows([]);
          setPlanDrawingUrl(null);
          setPlanDrawingFileName(null);
        } catch (err) {
          console.error(err);
          const detail = err.response?.data?.detail;
          message.error(typeof detail === 'string' ? detail : err.message || 'Failed to approve FTP');
          throw err;
        }
      },
    });
  };

  const openMeasurementsModal = async (record) => {
    const oid = effectiveOrderId && String(effectiveOrderId) !== 'null' ? Number(effectiveOrderId) : null;
    if (!oid) {
      message.error('Order is required to view measurements.');
      return;
    }
    const opNo = parseOpNo(record);
    setMeasureContext({
      opNo,
      opName: record?.operation_name || '',
      opId: record?.id,
      partId: selectedItem?.id,
      partNo: selectedItem?.part_number || '',
      orderId: oid,
    });
    setMeasureFtpStatus(ftpStatusByOp[opNo] || null);
    setMeasureModalOpen(true);
    setMeasureRows([]);
    setMeasureQty(1);
    setMeasureModalLoading(true);
    try {
      let qtyMax = 1;
      try {
        const p = await axios.get(`${QUALITY_API_BASE_URL}/parts/${selectedItem.id}`);
        const q = Number(p.data?.qty);
        if (Number.isFinite(q) && q >= 1) qtyMax = Math.min(999, Math.floor(q));
      } catch {
        qtyMax = 1;
      }
      const qOpts = Array.from({ length: qtyMax }, (_, i) => ({ value: i + 1, label: `Qty ${i + 1}` }));
      setMeasureQtyOptions(qOpts);
      setMeasureQty(1);
      const ipid = buildFtpIpid(selectedItem.part_number, opNo);
      try {
        await axios.post(`${QUALITY_API_BASE_URL}/quality/stage-inspection/ensure`, null, {
          params: {
            part_id: selectedItem.id,
            part_number: selectedItem.part_number,
            sale_order_id: oid,
            op_no: opNo,
            quantity_no: 1,
            ipid,
            user_id: 1,
          },
        });
      } catch (ensureErr) {
        console.warn('stage-inspection/ensure', ensureErr);
      }
      const res = await axios.get(`${QUALITY_API_BASE_URL}/quality/stage-inspection`, {
        params: { part_id: selectedItem.id, sale_order_id: oid, op_no: opNo, quantity_no: 1 },
      });
      setMeasureRows(Array.isArray(res.data) ? res.data : []);
      try {
        const fr = await axios.get(`${QUALITY_API_BASE_URL}/quality/ftp-status`, {
          params: { order_id: oid, ipid, op_no: opNo },
        });
        setMeasureFtpStatus(fr.data?.status || null);
      } catch {
        setMeasureFtpStatus(null);
      }
    } catch (err) {
      console.error(err);
      const detail = err.response?.data?.detail;
      message.error(typeof detail === 'string' ? detail : err.message || 'Failed to load measurements');
      setMeasureRows([]);
    } finally {
      setMeasureModalLoading(false);
    }
  };

  useEffect(() => {
    if (!measureModalOpen || !measureContext?.partId || !measureContext?.orderId || !measureContext?.opNo) return;
    let cancelled = false;
    (async () => {
      try {
        setMeasureModalLoading(true);
        const ipid = buildFtpIpid(measureContext.partNo, measureContext.opNo);
        try {
          await axios.post(`${QUALITY_API_BASE_URL}/quality/stage-inspection/ensure`, null, {
            params: {
              part_id: measureContext.partId,
              part_number: measureContext.partNo,
              sale_order_id: measureContext.orderId,
              op_no: measureContext.opNo,
              quantity_no: measureQty,
              ipid,
              user_id: 1,
            },
          });
        } catch (ensureErr) {
          if (ensureErr?.response?.status === 403) {
            if (!cancelled) {
              message.warning(
                measureQty > 1
                  ? 'FTP is not approved yet — quantity 2+ stage rows cannot be created until approval.'
                  : 'Could not ensure stage rows.',
              );
            }
          } else {
            console.warn('stage-inspection/ensure', ensureErr);
          }
        }
        const res = await axios.get(`${QUALITY_API_BASE_URL}/quality/stage-inspection`, {
          params: {
            part_id: measureContext.partId,
            sale_order_id: measureContext.orderId,
            op_no: measureContext.opNo,
            quantity_no: measureQty,
          },
        });
        if (!cancelled) setMeasureRows(Array.isArray(res.data) ? res.data : []);
        try {
          const fr = await axios.get(`${QUALITY_API_BASE_URL}/quality/ftp-status`, {
            params: { order_id: measureContext.orderId, ipid, op_no: measureContext.opNo },
          });
          if (!cancelled) setMeasureFtpStatus(fr.data?.status || null);
        } catch {
          if (!cancelled) setMeasureFtpStatus(null);
        }
      } catch (err) {
        if (cancelled) return;
        console.error(err);
        const detail = err.response?.data?.detail;
        message.error(typeof detail === 'string' ? detail : err.message || 'Failed to load quantity measurements');
        setMeasureRows([]);
      } finally {
        if (!cancelled) setMeasureModalLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [measureModalOpen, measureContext, measureQty, measureLoadNonce]);

  /** Ant Design Tag `color` for dimension_type — Length (blue) vs Diameter (orange) vs GDT (purple). */
  const dimensionTypeTagColor = (value) => {
    const s = String(value || '').trim();
    if (!s) return 'default';
    const u = s.toUpperCase();
    if (u.startsWith('GDT') || u.includes('GD&T')) return 'purple';
    if (u.includes('DIAMETER') || u.includes('∅') || u.includes('⌀') || /\bDIA\b/i.test(s)) return 'orange';
    if (u.includes('LENGTH') || /^length$/i.test(s)) return 'blue';
    return 'cyan';
  };
  const fmtTol = (value) => {
    const n = Number(value);
    if (!Number.isFinite(n)) return '0';
    if (Math.abs(n) < 1e-9) return '0';
    return String(n);
  };

  const handlePreviewPart = () => {
    setPreviewTitle(`Part Drawing: ${selectedItem.part_name}`);
    
    const isDrawing = (d) => {
      const type = (d.document_type || "").toLowerCase();
      const name = (d.document_name || "").toLowerCase();
      return type.includes('2d') || type.includes('drawing') || name.includes('drawing') || name.includes('.pdf') || name.includes('.png') || name.includes('.jpg') || name.includes('.jpeg');
    };

    let drawing = partDocuments.find(isDrawing);

    // Final fallback for part drawing
    if (!drawing && partDocuments.length > 0) {
      drawing = partDocuments[0];
    }

    setPreviewUrl(drawing?.document_url || null);
    setPreviewIsPdf(drawing?.document_url?.toLowerCase().endsWith('.pdf') || false);
    setPreviewModalVisible(true);
  };

  useEffect(() => {
    const handleResize = () => {
      const mobile = window.innerWidth < 768;
      setIsMobile(mobile);
      if (!mobile) setMobileDrawerOpen(false);
    };
    window.addEventListener('resize', handleResize);
    return () => window.removeEventListener('resize', handleResize);
  }, []);

  const handleItemSelected = (item) => {
    setSelectedItem(item);
    if (isMobile) setMobileDrawerOpen(false);
  };

  const handleHierarchyLoaded = (productId, hierarchy) => {
    setProductHierarchies(prev => ({ ...prev, [productId]: hierarchy }));
  };

  const calculateStats = (productId) => {
    const hierarchy = productHierarchies[productId];
    if (!hierarchy) return { total: 0, inhouse: 0, outsource: 0 };

    const parts = [];
    const directParts = hierarchy.direct_parts || hierarchy.parts || [];
    parts.push(...directParts);
    
    const walkAssemblies = (assemblies) => {
      (assemblies || []).forEach((asm) => {
        if (asm?.parts) parts.push(...asm.parts);
        if (asm?.subassemblies) walkAssemblies(asm.subassemblies);
      });
    };
    walkAssemblies(hierarchy.assemblies || []);

    const inhouse = parts.filter(p => !String(p.part?.type_name || p.type_name || "").toLowerCase().includes("out")).length;
    const outsource = parts.length - inhouse;

    return { total: parts.length, inhouse, outsource };
  };

  const StatCard = ({ icon, label, value, color }) => (
    <Card size="small" style={{ border: '1px solid #f0f0f0', borderRadius: '8px' }}>
      <Space align="center">
        <div style={{ fontSize: '20px', color: color, display: 'flex' }}>{icon}</div>
        <div>
          <div style={{ fontSize: '12px', color: '#8c8c8c' }}>{label}</div>
          <div style={{ fontSize: '16px', fontWeight: 'bold' }}>{value}</div>
        </div>
      </Space>
    </Card>
  );

  if (isCheckingStatus) {
    return (
      <div style={{ height: 'calc(100vh - 180px)', display: 'flex', alignItems: 'center', justifyContent: 'center', background: '#fff' }}>
        <Space direction="vertical" align="center">
          <Spin size="large" />
          <Text type="secondary">Checking order status...</Text>
        </Space>
      </div>
    );
  }

  if (orderStatus !== 'active' && effectiveOrderId && String(effectiveOrderId) !== 'null') {
    return (
      <div style={{ height: 'calc(100vh - 180px)', display: 'flex', alignItems: 'center', justifyContent: 'center', background: '#fff', borderRadius: '12px', border: '1px solid #f0f0f0', margin: '20px' }}>
        <Empty
          image={Empty.PRESENTED_IMAGE_SIMPLE}
          description={
            <div style={{ textAlign: 'center' }}>
              <Title level={4} style={{ color: '#ff4d4f' }}>Order Inactive</Title>
              <Text type="secondary">
                This order is currently inactive and not available for Quality Management.<br />
                Please ensure the order is scheduled and activated in the PPS module.
              </Text>
            </div>
          }
        />
      </div>
    );
  }

  return (
    <div style={{ height: 'calc(100vh - 180px)', overflow: 'hidden' }}>
      <Layout style={{ height: "100%", background: "transparent" }}>
        {/* Mobile Toggle */}
        {isMobile && (
          <Button
            type="text"
            icon={<MenuOutlined />}
            onClick={() => setMobileDrawerOpen(true)}
            style={{ position: 'fixed', top: 120, left: 16, zIndex: 1001, background: 'white', boxShadow: '0 2px 8px rgba(0,0,0,0.15)' }}
          />
        )}

        {/* Sidebar/BOM */}
        {!isMobile && (
          <Sider
            width="33%"
            theme="light"
            style={{
              borderRight: "1px solid #f0f0f0",
              overflow: 'auto',
              minWidth: 300,
              maxWidth: 500,
              height: '100%',
              borderRadius: '8px 0 0 8px'
            }}
          >
            <QualityManagementBOM
              onItemSelected={handleItemSelected}
              onHierarchyLoaded={handleHierarchyLoaded}
              initialProductId={effectiveProductId}
            />
          </Sider>
        )}

        {/* Mobile Drawer for BOM */}
        {isMobile && (
          <Drawer
            placement="left"
            onClose={() => setMobileDrawerOpen(false)}
            open={mobileDrawerOpen}
            width="85%"
            styles={{ body: { padding: 0 } }}
          >
            <QualityManagementBOM
              onItemSelected={handleItemSelected}
              onHierarchyLoaded={handleHierarchyLoaded}
              initialProductId={effectiveProductId}
            />
          </Drawer>
        )}

        {/* Main Content Area */}
        <Content style={{ 
          background: '#f8fafc', 
          padding: '24px', 
          overflow: 'auto',
          borderRadius: isMobile ? '8px' : '0 8px 8px 0'
        }}>
          {selectedItem ? (
            <div>
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '16px', flexWrap: 'wrap', gap: '12px' }}>
                <Title level={3} style={{ margin: 0 }}>
                  {selectedItem.itemType === 'product' ? selectedItem.product_name : 
                   selectedItem.itemType === 'assembly' ? selectedItem.assembly_name : 
                   selectedItem.part_name}
                  {selectedItem.itemType === 'part' && (
                    <Space size={0}>
                      <Button 
                        type="link" 
                        icon={<EyeOutlined />} 
                        onClick={handlePreviewPart}
                        style={{ marginLeft: '12px' }}
                      >
                        View Part Drawing
                      </Button>
                      <Button 
                        type="link" 
                        icon={<CheckCircleOutlined />} 
                        onClick={() => handleOpenPartInspection()}
                      >
                        Part Inspection
                      </Button>
                      <Button 
                        type="link" 
                        icon={<CloudDownloadOutlined />} 
                        onClick={() => handleOpenPartReport()}
                      >
                        Part Report
                      </Button>
                    </Space>
                  )}
                </Title>
                <Space>
                  <Tag color="blue">{selectedItem.itemType.toUpperCase()}</Tag>
                </Space>
              </div>

              {selectedItem.itemType === 'product' && (
                <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(180px, 1fr))', gap: '16px', marginBottom: '24px' }}>
                  {(() => {
                    const stats = calculateStats(selectedItem.id);
                    return (
                      <>
                        <StatCard icon={<ClusterOutlined />} label="Total Parts" value={stats.total} color="#1890ff" />
                        <StatCard icon={<ToolOutlined />} label="In-house Parts" value={stats.inhouse} color="#52c41a" />
                        <StatCard icon={<ShoppingCartOutlined />} label="Outsource Parts" value={stats.outsource} color="#faad14" />
                      </>
                    );
                  })()}
                </div>
              )}

              {selectedItem.itemType === 'part' && (
                <div style={{ background: '#fff', padding: '20px', borderRadius: '12px', border: '1px solid #f0f0f0', boxShadow: '0 2px 12px rgba(0,0,0,0.03)' }}>
                  <Tabs
                    defaultActiveKey="1"
                    items={[
                      {
                        key: '1',
                        label: 'Inspection Details',
                        children: (
                          <Table 
                            loading={loadingDetails}
                            dataSource={operations}
                            rowKey="id"
                            pagination={false}
                            scroll={{ x: 'max-content' }}
                            columns={[
                              {
                                title: 'Op #',
                                dataIndex: 'operation_number',
                                key: 'operation_number',
                                width: 80,
                                render: val => <Text strong style={{ color: '#1890ff' }}>{val}</Text>
                              },
                              {
                                title: 'Operation Name',
                                dataIndex: 'operation_name',
                                key: 'operation_name',
                                render: val => <Text style={{ fontWeight: 500 }}>{val}</Text>
                              },
                              {
                                title: 'Plan status',
                                key: 'inspection_plan_status',
                                width: 120,
                                render: (_, record) => {
                                  const opNo = parseOpNo(record);
                                  const st = inspectionPlanByOp[opNo];
                                  if (st === 'confirmed') {
                                    return <Tag color="success" style={{ borderRadius: '12px' }}>Confirmed</Tag>;
                                  }
                                  if (st === 'draft') {
                                    return <Tag color="processing" style={{ borderRadius: '12px' }}>Draft</Tag>;
                                  }
                                  return <Tag style={{ borderRadius: '12px' }}>—</Tag>;
                                },
                              },
                              {
                                title: 'Confirmed by',
                                key: 'inspection_plan_confirmed_by',
                                width: 140,
                                render: (_, record) => {
                                  const opNo = parseOpNo(record);
                                  const st = inspectionPlanByOp[opNo];
                                  const who = inspectionPlanConfirmedByOp[opNo];
                                  if (st !== 'confirmed' || !who) {
                                    return <Text type="secondary">—</Text>;
                                  }
                                  return (
                                    <Text style={{ fontSize: 13 }} ellipsis={{ tooltip: who }}>
                                      {who}
                                    </Text>
                                  );
                                },
                              },
                              {
                                title: 'Req qty',
                                dataIndex: 'required_quantity',
                                key: 'required_quantity',
                                align: 'center'
                              },
                              {
                                title: 'Comp qty',
                                dataIndex: 'completed_quantity',
                                key: 'completed_quantity',
                                align: 'center'
                              },
                              {
                                title: 'Acpt qty',
                                dataIndex: 'accepted_quantity',
                                key: 'accepted_quantity',
                                align: 'center'
                              },
                              {
                                title: 'Rej qty',
                                dataIndex: 'rejected_quantity',
                                key: 'rejected_quantity',
                                align: 'center'
                              },
                              {
                                title: 'Yield %',
                                dataIndex: 'yield_percentage',
                                key: 'yield_percentage',
                                align: 'center',
                                render: val => (
                                  <Text style={{ color: val >= 95 ? '#52c41a' : val < 80 ? '#f5222d' : '#faad14', fontWeight: 'bold' }}>
                                    {val ? `${val}%` : '0%'}
                                  </Text>
                                )
                              },
                              {
                                title: 'Actions',
                                key: 'actions',
                                fixed: 'right',
                                render: (_, record) => {
                                  const opNo = parseOpNo(record);
                                  const st = inspectionPlanByOp[opNo];
                                  const ftpStatus = ftpStatusByOp[opNo] || null;
                                  const planLabel = st === 'confirmed' ? 'View Plan' : st === 'draft' ? 'Continue Plan' : 'Create Plan';
                                  const PlanIcon = st === 'confirmed' ? EyeOutlined : BuildOutlined;
                                  return (
                                  <Space size="middle">
                                    <Button 
                                      size="small" 
                                      type="primary" 
                                      ghost 
                                      icon={<PlanIcon />}
                                      onClick={async () => {
                                        if (st === 'confirmed') {
                                          await openConfirmedPlanModal(record, opNo);
                                          return;
                                        }
                                        const { url, isPdf, name, apiDocumentId } = getDrawingInfo(record);
                                        const hierarchy = productHierarchies[selectedItem.productId];
                                        const projectName = hierarchy?.product?.product_name || '';
                                        const partName = selectedItem.part_name || '';
                                        const opParts = [];
                                        if (record.operation_number != null && record.operation_number !== '') opParts.push(String(record.operation_number));
                                        if (record.operation_name) opParts.push(record.operation_name);
                                        const opLabel = opParts.join(': ');
                                        if (effectiveOrderId && String(effectiveOrderId) !== 'null' && selectedItem.part_number) {
                                          if (st !== 'confirmed') {
                                            try {
                                              await axios.put(`${QUALITY_API_BASE_URL}/quality/inspection-plan-status`, {
                                                part_number: selectedItem.part_number,
                                                sales_order_id: Number(effectiveOrderId),
                                                op_no: opNo,
                                                status: 'draft',
                                              });
                                              setInspectionPlanByOp((prev) => ({ ...prev, [opNo]: 'draft' }));
                                              setInspectionPlanConfirmedByOp((prev) => ({ ...prev, [opNo]: null }));
                                            } catch (err) {
                                              console.error(err);
                                              const detail = err.response?.data?.detail;
                                              message.error(typeof detail === 'string' ? detail : err.message || 'Could not start inspection plan');
                                              return;
                                            }
                                          }
                                        }
                                        const qs = new URLSearchParams({
                                          drawingUrl: url || '',
                                          isPdf: String(!!isPdf),
                                          fileName: name || '',
                                          projectName,
                                          partName,
                                          operationName: opLabel,
                                          partId: String(selectedItem.id),
                                          partNumber: selectedItem.part_number || '',
                                          operationNumber: String(record.operation_number ?? ''),
                                          operationId: String(record.id),
                                        });
                                        if (apiDocumentId != null) qs.set('documentId', String(apiDocumentId));
                                        if (effectiveOrderId && String(effectiveOrderId) !== 'null') {
                                          qs.set('orderId', String(effectiveOrderId));
                                        }
                                        navigate(`${qmsInspectorBase}?${qs.toString()}`);
                                      }}
                                    >
                                      {planLabel}
                                    </Button>
                                    <Button 
                                      size="small" 
                                      icon={<CheckCircleOutlined />} 
                                      style={{ color: '#52c41a', borderColor: '#52c41a' }}
                                      onClick={() => openMeasurementsModal(record)}
                                    >
                                      Measurements
                                    </Button>

                                    <Button 
                                      size="small" 
                                      icon={<EyeOutlined />} 
                                      onClick={() => handlePreviewOperation(record)}
                                      title="View Drawing"
                                    >
                                      View Drawing
                                    </Button>
                                  </Space>
                                  );
                                },
                              },
                            ]}
                          />
                        ),
                      },
                      {
                        key: '2',
                        label: 'Inspection Report',
                        children: (
                          <div style={{ maxWidth: '800px' }}>
                            <Table 
                              loading={loadingDetails}
                              dataSource={operations}
                              rowKey="id"
                              pagination={false}
                              columns={[
                                {
                                  title: 'Op #',
                                  dataIndex: 'operation_number',
                                  key: 'operation_number',
                                  width: 80,
                                  render: val => <Text strong style={{ color: '#1890ff' }}>{val}</Text>
                                },
                                {
                                  title: 'Operation Name',
                                  dataIndex: 'operation_name',
                                  key: 'operation_name',
                                },
                                {
                                  title: 'Approved by',
                                  key: 'approved_by',
                                  render: (_, record) => {
                                    const opNo = parseOpNo(record);
                                    const who = inspectionPlanConfirmedByOp[opNo];
                                    return who ? <Text>{who}</Text> : <Text type="secondary">—</Text>;
                                  },
                                },
                                {
                                  title: 'Actions',
                                  key: 'report_actions',
                                  align: 'center',
                                  render: (_, record) => (
                                    <Button 
                                      type="primary" 
                                      ghost 
                                      icon={<FilePdfOutlined />} 
                                      onClick={() => handleGenerateReport(record)}
                                      style={{ borderRadius: '6px' }}
                                    >
                                      Generate Report
                                    </Button>
                                  ),
                                },
                              ]}
                            />
                          </div>
                        ),
                      },
                    ]}
                  />
                </div>
              )}

              <Modal
                title={planViewTitle || 'Operation Details'}
                centered
                footer={null}
                width="95%"
                onCancel={closePlanViewModal}
                open={planViewOpen}
                styles={{ body: { padding: 12, height: '80vh', background: '#f7f8fa' } }}
              >
                <div style={{ display: 'grid', gridTemplateColumns: '1.45fr 1fr', gap: 14, height: '100%', fontFamily: '"JetBrains Mono", "Consolas", "Courier New", monospace' }}>
                  <div style={{ border: '1px solid #dfe4ea', borderRadius: 10, overflow: 'hidden', background: '#fff', display: 'flex', flexDirection: 'column', boxShadow: '0 2px 10px rgba(15,23,42,0.04)' }}>
                    <div style={{ padding: '14px 16px', borderBottom: '1px solid #eef0f3', background: '#fafbfc', display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between', gap: 12 }}>
                      <div style={{ flex: 1, minWidth: 0 }}>
                      <Text strong style={{ color: '#111827', fontSize: 22, lineHeight: 1.2, fontFamily: '"JetBrains Mono", "Consolas", "Courier New", monospace' }}>Inspection Details</Text>
                      <div style={{ marginTop: 10, fontSize: 16, color: '#374151' }}>
                        <Text style={{ fontSize: 16, fontFamily: '"JetBrains Mono", "Consolas", "Courier New", monospace' }}><b>Order:</b> {planViewMeta?.orderNo || '—'}</Text>
                        <Text style={{ fontSize: 16, marginLeft: 18, fontFamily: '"JetBrains Mono", "Consolas", "Courier New", monospace' }}><b>Part:</b> {planViewMeta?.partNo || '—'}</Text>
                        <Text style={{ fontSize: 16, marginLeft: 18, fontFamily: '"JetBrains Mono", "Consolas", "Courier New", monospace' }}><b>Operation:</b> {planViewMeta?.opNo || '—'}</Text>
                      </div>
                      </div>
                      {planViewCanEditBoc && !planViewLoading && (
                        <Button type="primary" icon={<EditOutlined />} onClick={handleEditPlanFromViewModal} style={{ flexShrink: 0 }}>
                          Edit plan (BOC)
                        </Button>
                      )}
                    </div>
                    <div style={{ padding: '0 10px 10px', flex: 1, minHeight: 0 }}>
                      <Table
                        size="small"
                        loading={planViewLoading}
                        dataSource={planTableRows}
                        rowKey="id"
                        pagination={{ pageSize: 14, showSizeChanger: false }}
                        scroll={{ x: 'max-content', y: 520 }}
                        rowClassName={(_, idx) => (idx % 2 === 0 ? 'plan-row-even' : 'plan-row-odd')}
                        columns={[
                          { title: 'S.No', key: 'sno', width: 82, render: (_, __, idx) => <Text style={{ fontFamily: '"JetBrains Mono", "Consolas", "Courier New", monospace', fontSize: 13 }}>{idx + 1}</Text> },
                          { title: 'Zone', dataIndex: 'zone', key: 'zone', width: 90, render: (z) => <Tag color="geekblue" style={{ margin: 0, borderRadius: 10, fontFamily: '"JetBrains Mono", "Consolas", "Courier New", monospace' }}>{z || '—'}</Tag> },
                          {
                            title: 'Description',
                            dataIndex: 'dimension_type',
                            key: 'dimension_type',
                            width: 280,
                            render: (val) => (
                              <Tag
                                color={dimensionTypeTagColor(val)}
                                style={{ margin: 0, borderRadius: 10, fontFamily: '"JetBrains Mono", "Consolas", "Courier New", monospace' }}
                              >
                                {val || '—'}
                              </Tag>
                            ),
                          },
                          { title: 'Nominal', dataIndex: 'nominal', key: 'nominal', width: 130, render: (v) => <Text style={{ fontFamily: '"JetBrains Mono", "Consolas", "Courier New", monospace', color: '#1f2937', fontSize: 13 }}>{v ?? '—'}</Text> },
                          { title: 'Upper Tol', dataIndex: 'uppertol', key: 'uppertol', width: 130, render: (v) => <Text style={{ fontFamily: '"JetBrains Mono", "Consolas", "Courier New", monospace', color: Number(v) > 0 ? '#15803d' : '#6b7280', fontSize: 13 }}>{fmtTol(v)}</Text> },
                          { title: 'Lower Tol', dataIndex: 'lowertol', key: 'lowertol', width: 130, render: (v) => <Text style={{ fontFamily: '"JetBrains Mono", "Consolas", "Courier New", monospace', color: Number(v) < 0 ? '#b91c1c' : '#6b7280', fontSize: 13 }}>{fmtTol(v)}</Text> },
                        ]}
                      />
                    </div>
                  </div>
                  <div style={{ border: '1px solid #dfe4ea', borderRadius: 10, overflow: 'hidden', background: '#fff', display: 'flex', flexDirection: 'column', boxShadow: '0 2px 10px rgba(15,23,42,0.04)' }}>
                    <div style={{ padding: '10px 14px', borderBottom: '1px solid #eef0f3', background: '#fafbfc', display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
                      <Text strong style={{ color: '#111827', fontFamily: '"JetBrains Mono", "Consolas", "Courier New", monospace' }}>Drawing View</Text>
                      <Button size="small" icon={<CloudDownloadOutlined />} onClick={handleDownloadPlanDrawing} disabled={!planDrawingUrl}>
                        Download Drawing
                      </Button>
                    </div>
                    <div style={{ flex: 1, minHeight: 0, padding: 10, display: 'flex', alignItems: 'center', justifyContent: 'center', background: '#f8fafc' }}>
                      {planViewLoading ? (
                        <div style={{ height: '100%', display: 'flex', alignItems: 'center', justifyContent: 'center' }}><Spin /></div>
                      ) : planDrawingUrl ? (
                        planDrawingIsPdf ? (
                          <iframe
                            title="Balloon document"
                            src={pdfEmbedSrcForReview(planDrawingUrl)}
                            style={{
                              width: '100%',
                              minHeight: 480,
                              height: 'min(72vh, 900px)',
                              border: '1px solid #e5e7eb',
                              borderRadius: 10,
                              background: '#fff',
                              boxShadow: '0 2px 10px rgba(15,23,42,0.08)',
                            }}
                          />
                        ) : (
                          <img
                            src={planDrawingUrl}
                            alt="Ballooned drawing"
                            style={{
                              maxWidth: '100%',
                              maxHeight: '100%',
                              objectFit: 'contain',
                              border: '1px solid #e5e7eb',
                              borderRadius: 10,
                              background: '#fff',
                              boxShadow: '0 2px 10px rgba(15,23,42,0.08)',
                            }}
                          />
                        )
                      ) : (
                        <div style={{ height: '100%', display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
                          <Empty description="No balloon document found for this operation" />
                        </div>
                      )}
                    </div>
                  </div>
                </div>
              </Modal>

              {/* Modal for 2D Drawing Preview */}
              <Modal
                title={`Measured Inspection Data${measureContext?.opNo != null ? ` - OP ${measureContext.opNo}` : ''}`}
                centered
                footer={null}
                width="96%"
                onCancel={() => setMeasureModalOpen(false)}
                open={measureModalOpen}
                styles={{ body: { padding: 12, maxHeight: '78vh', background: '#f7f8fa', fontFamily: '"JetBrains Mono", "Consolas", "Courier New", monospace', overflow: 'auto' } }}
              >
                <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
                  <div style={{ border: '1px solid #e5e7eb', borderRadius: 8, background: '#fff', padding: '10px 12px', display: 'flex', justifyContent: 'space-between', alignItems: 'center', flexWrap: 'wrap', gap: 10 }}>
                    <div style={{ display: 'flex', gap: 16, flexWrap: 'wrap', alignItems: 'center' }}>
                      <Text style={{ fontFamily: '"JetBrains Mono", "Consolas", "Courier New", monospace' }}><b>Production Order:</b> {measureContext?.orderId || '—'}</Text>
                      <Text style={{ fontFamily: '"JetBrains Mono", "Consolas", "Courier New", monospace' }}><b>Part Number:</b> {measureContext?.partNo || '—'}</Text>
                      <Text style={{ fontFamily: '"JetBrains Mono", "Consolas", "Courier New", monospace' }}><b>Operation:</b> {measureContext?.opName ? `OP ${measureContext?.opNo} (${measureContext.opName})` : `OP ${measureContext?.opNo ?? '—'}`}</Text>
                      <Tooltip title="FTP (first-time pass) applies to this order and operation. Operators request approval after quantity 1; quantity 2+ stays locked until approved.">
                        <Tag
                          color={
                            measureFtpStatus === 'approved'
                              ? 'success'
                              : measureFtpStatus === 'pending'
                                ? 'processing'
                                : measureFtpStatus === 'rejected'
                                  ? 'error'
                                  : 'default'
                          }
                          style={{ margin: 0, fontFamily: '"JetBrains Mono", "Consolas", "Courier New", monospace' }}
                        >
                          FTP: {(measureFtpStatus || 'not requested').toString().toUpperCase()}
                        </Tag>
                      </Tooltip>
                      {measureQty > 1 ? (
                        <Tag color={measureFtpStatus === 'approved' ? 'success' : 'warning'} style={{ margin: 0 }}>
                          Selected Qty {measureQty}: {measureFtpStatus === 'approved' ? 'FTP approved — plan + measurements can load' : 'FTP not approved — operators cannot record this quantity yet'}
                        </Tag>
                      ) : (
                        <Tag color="blue" style={{ margin: 0 }}>
                          Qty 1: complete measurements, then request FTP approval
                        </Tag>
                      )}
                    </div>
                    <Space align="center">
                      <Text style={{ fontFamily: '"JetBrains Mono", "Consolas", "Courier New", monospace' }}><b>Qty:</b></Text>
                      <Select
                        size="small"
                        style={{ width: 110 }}
                        value={measureQty}
                        options={measureQtyOptions}
                        onChange={setMeasureQty}
                      />
                    </Space>
                  </div>
                  {measureQty > 1 && measureFtpStatus !== 'approved' ? (
                    <Alert
                      type="warning"
                      showIcon
                      message="Quantity 2 and above require FTP approval."
                      description="After you click Approve FTP in the operations list, stage rows are created and this table shows both the plan (nominal / limits) and actual readings for the selected quantity."
                    />
                  ) : null}
                  <div style={{ border: '1px solid #e5e7eb', borderRadius: 8, background: '#fff', overflow: 'hidden' }}>
                    {measureAllReadingsEmpty && !measureModalLoading ? (
                      <div style={{ padding: 40 }}>
                        <Empty description="No measurements found" />
                      </div>
                    ) : (
                      <>
                        <div style={{ padding: '8px 12px', borderBottom: '1px solid #eef0f3', background: '#fafbfc', display: 'flex', gap: 8, alignItems: 'center', flexWrap: 'wrap' }}>
                          <Tag color="default" style={{ margin: 0, borderRadius: 12 }}>Total: {measureSummary.total}</Tag>
                          <Tag color="success" style={{ margin: 0, borderRadius: 12 }}>Within Tol: {measureSummary.within}</Tag>
                          <Tag color="error" style={{ margin: 0, borderRadius: 12 }}>Out Tol: {measureSummary.out}</Tag>
                          <Tag color="processing" style={{ margin: 0, borderRadius: 12 }}>No Tol: {measureSummary.noTol}</Tag>
                          <Tag color="blue" style={{ margin: 0, borderRadius: 12 }}>Pass Rate: {measureSummary.passRate}%</Tag>
                        </div>
                        <Table
                          size="small"
                          loading={measureModalLoading}
                          dataSource={measureDecoratedRows}
                          rowKey="id"
                          pagination={{ pageSize: 10, showSizeChanger: false, hideOnSinglePage: true }}
                          scroll={{ x: 'max-content', y: Math.min(480, Math.max(160, measureDecoratedRows.length * 44 + 70)) }}
                          columns={[
                            { title: 'S.No', key: 'sno', width: 70, render: (_, __, idx) => idx + 1 },
                            { title: 'Zone', dataIndex: 'zone', key: 'zone', width: 90, render: (z) => <Tag color="geekblue" style={{ margin: 0, borderRadius: 10 }}>{z || '—'}</Tag> },
                            {
                              title: 'Type',
                              dataIndex: 'dimension_type',
                              key: 'dimension_type',
                              width: 170,
                              render: (v) => (
                                <Tag color={dimensionTypeTagColor(v)} style={{ margin: 0, borderRadius: 10 }}>
                                  {v || '—'}
                                </Tag>
                              ),
                            },
                            {
                              title: 'Plan (from inspection plan)',
                              key: 'plan_group',
                              children: [
                                { title: 'Nominal', dataIndex: 'nominal_value', key: 'nominal_value', width: 110, render: (v) => <Text strong>{v ?? '—'}</Text> },
                                { title: 'Upper', dataIndex: 'uppertol', key: 'uppertol', width: 90, render: (v) => <Text style={{ color: Number(v) > 0 ? '#15803d' : '#6b7280' }}>{fmtTol(v)}</Text> },
                                { title: 'Lower', dataIndex: 'lowertol', key: 'lowertol', width: 90, render: (v) => <Text style={{ color: Number(v) < 0 ? '#b91c1c' : '#6b7280' }}>{fmtTol(v)}</Text> },
                                {
                                  title: 'Upper Limit',
                                  key: 'upper_limit',
                                  width: 120,
                                  render: (_, r) => <Text style={{ color: '#166534' }}>{fmt4(r._upperLimit)}</Text>,
                                },
                                {
                                  title: 'Lower Limit',
                                  key: 'lower_limit',
                                  width: 120,
                                  render: (_, r) => <Text style={{ color: '#991b1b' }}>{fmt4(r._lowerLimit)}</Text>,
                                },
                              ],
                            },
                            {
                              title: 'Actual (measurements)',
                              key: 'actual_group',
                              children: [
                                { title: '#1', dataIndex: 'measured_1', key: 'measured_1', width: 90 },
                                { title: '#2', dataIndex: 'measured_2', key: 'measured_2', width: 90 },
                                { title: '#3', dataIndex: 'measured_3', key: 'measured_3', width: 90 },
                                {
                                  title: 'Mean',
                                  key: 'mean_computed',
                                  width: 110,
                                  render: (_, r) => {
                                    const m = r._computedMean;
                                    const display = m == null ? '—' : fmt4(m);
                                    if (r._status === 'within') return <Text strong style={{ color: '#15803d' }}>{display}</Text>;
                                    if (r._status === 'out') return <Text strong style={{ color: '#dc2626' }}>{display}</Text>;
                                    return <Text style={{ color: '#4b5563' }}>{display}</Text>;
                                  },
                                },
                                {
                                  title: 'Status',
                                  key: 'status',
                                  width: 130,
                                  render: (_, r) => {
                                    if (r._status === 'within') return <Tag color="success" style={{ margin: 0, borderRadius: 10 }}>Within Tol</Tag>;
                                    if (r._status === 'out') return <Tag color="error" style={{ margin: 0, borderRadius: 10 }}>Out Tol</Tag>;
                                    if (r._status === 'no_tolerance') return <Tag color="processing" style={{ margin: 0, borderRadius: 10 }}>No Tol</Tag>;
                                    return <Tag style={{ margin: 0, borderRadius: 10 }}>Pending</Tag>;
                                  },
                                },
                              ],
                            },
                          ]}
                        />
                      </>
                    )}
                  </div>
                </div>
              </Modal>

              <Modal
                title={
                  ftpApproveContext
                    ? `Review FTP — Quantity 1 · OP ${ftpApproveContext.opNo}${ftpApproveContext.opName ? ` (${ftpApproveContext.opName})` : ''}`
                    : 'Review FTP'
                }
                centered
                width="98%"
                open={ftpApproveModalOpen}
                onCancel={() => {
                  setFtpApproveModalOpen(false);
                  setFtpApproveContext(null);
                  setFtpApproveRows([]);
                  setPlanDrawingUrl(null);
                  setPlanDrawingFileName(null);
                }}
                destroyOnClose
                footer={
                  <Space>
                    <Button
                      onClick={() => {
                        setFtpApproveModalOpen(false);
                        setFtpApproveContext(null);
                        setFtpApproveRows([]);
                        setPlanDrawingUrl(null);
                        setPlanDrawingFileName(null);
                      }}
                    >
                      Cancel
                    </Button>
                    <Button
                      type="primary"
                      disabled={
                        ftpApproveLoading ||
                        !ftpApproveContext ||
                        ftpApproveDecoratedRows.length === 0 ||
                        ftpApproveAllReadingsEmpty
                      }
                      onClick={() => confirmAndApproveFtp()}
                    >
                      Approve FTP…
                    </Button>
                  </Space>
                }
                styles={{ body: { padding: 12, height: '80vh', background: '#f7f8fa' } }}
              >
                <div style={{ display: 'grid', gridTemplateColumns: '1.45fr 1fr', gap: 14, height: '100%', fontFamily: '"JetBrains Mono", "Consolas", "Courier New", monospace' }}>
                  <div style={{ border: '1px solid #dfe4ea', borderRadius: 10, overflow: 'hidden', background: '#fff', display: 'flex', flexDirection: 'column', boxShadow: '0 2px 10px rgba(15,23,42,0.04)' }}>
                    <div style={{ padding: '14px 16px', borderBottom: '1px solid #eef0f3', background: '#fafbfc' }}>
                      <Text strong style={{ color: '#111827', fontSize: 22, lineHeight: 1.2, fontFamily: '"JetBrains Mono", "Consolas", "Courier New", monospace' }}>Inspection Details</Text>
                      {ftpApproveContext && (
                        <div style={{ marginTop: 10, fontSize: 16, color: '#374151' }}>
                          <Text style={{ fontSize: 16, fontFamily: '"JetBrains Mono", "Consolas", "Courier New", monospace' }}><b>Order:</b> {ftpApproveContext.orderId}</Text>
                          <Text style={{ fontSize: 16, marginLeft: 18, fontFamily: '"JetBrains Mono", "Consolas", "Courier New", monospace' }}><b>Part:</b> {ftpApproveContext.partNo}</Text>
                          <Text style={{ fontSize: 16, marginLeft: 18, fontFamily: '"JetBrains Mono", "Consolas", "Courier New", monospace' }}><b>Operation:</b> {ftpApproveContext.opNo}</Text>
                        </div>
                      )}
                    </div>

                    <div style={{ padding: '10px 14px', flex: 1, minHeight: 0, overflow: 'auto' }}>
                      <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
                        {!ftpApproveLoading && ftpApproveDecoratedRows.length === 0 ? (
                          <Alert
                            type="warning"
                            showIcon
                            message="No quantity 1 measurement rows found."
                            description="Ensure the operator has completed quantity 1 in the inspector and requested FTP."
                          />
                        ) : null}
                        {ftpApproveDecoratedRows.some((r) => r._status === 'out') ? (
                          <Alert
                            type="warning"
                            showIcon
                            message="Some characteristics are out of tolerance on quantity 1."
                            description="You can still approve FTP if this is acceptable for your process; otherwise reject with the operator and re-measure."
                          />
                        ) : null}

                        <div style={{ border: '1px solid #e5e7eb', borderRadius: 8, background: '#fff', overflow: 'hidden' }}>
                          {ftpApproveAllReadingsEmpty && !ftpApproveLoading ? (
                            <div style={{ padding: 40 }}>
                              <Empty description="No measurements found or incomplete data" />
                            </div>
                          ) : (
                            <>
                              <div style={{ padding: '8px 12px', borderBottom: '1px solid #eef0f3', background: '#fafbfc', display: 'flex', gap: 8, alignItems: 'center', flexWrap: 'wrap' }}>
                                <Tag color="default" style={{ margin: 0, borderRadius: 12 }}>Total: {ftpApproveSummary.total}</Tag>
                                <Tag color="success" style={{ margin: 0, borderRadius: 12 }}>Within Tol: {ftpApproveSummary.within}</Tag>
                                <Tag color="error" style={{ margin: 0, borderRadius: 12 }}>Out Tol: {ftpApproveSummary.out}</Tag>
                                <Tag color="processing" style={{ margin: 0, borderRadius: 12 }}>No Tol: {ftpApproveSummary.noTol}</Tag>
                                <Tag color="blue" style={{ margin: 0, borderRadius: 12 }}>Pass Rate: {ftpApproveSummary.passRate}%</Tag>
                              </div>
                              <Table
                                size="small"
                                loading={ftpApproveLoading}
                                dataSource={ftpApproveDecoratedRows}
                                rowKey="id"
                                pagination={false}
                                scroll={{ x: 'max-content', y: 460 }}
                                columns={[
                                  { title: 'S.No', key: 'sno', width: 64, render: (_, __, idx) => idx + 1 },
                                  { title: 'Zone', dataIndex: 'zone', key: 'zone', width: 82, render: (z) => <Tag color="geekblue" style={{ margin: 0, borderRadius: 10 }}>{z || '—'}</Tag> },
                                  {
                                    title: 'Type',
                                    dataIndex: 'dimension_type',
                                    key: 'dimension_type',
                                    width: 160,
                                    render: (v) => (
                                      <Tag color={dimensionTypeTagColor(v)} style={{ margin: 0, borderRadius: 10 }}>
                                        {v || '—'}
                                      </Tag>
                                    ),
                                  },
                                  {
                                    title: 'Plan (from inspection plan)',
                                    key: 'plan_group_ftp',
                                    children: [
                                      { title: 'Nominal', dataIndex: 'nominal_value', key: 'nominal_value', width: 100, render: (v) => <Text strong>{v ?? '—'}</Text> },
                                      { title: 'Upper', dataIndex: 'uppertol', key: 'uppertol', width: 80, render: (v) => <Text style={{ color: Number(v) > 0 ? '#15803d' : '#6b7280' }}>{fmtTol(v)}</Text> },
                                      { title: 'Lower', dataIndex: 'lowertol', key: 'lowertol', width: 80, render: (v) => <Text style={{ color: Number(v) < 0 ? '#b91c1c' : '#6b7280' }}>{fmtTol(v)}</Text> },
                                    ],
                                  },
                                  {
                                    title: 'Actual (Qty 1)',
                                    key: 'actual_group_ftp',
                                    children: [
                                      { title: '#1', dataIndex: 'measured_1', key: 'measured_1', width: 72 },
                                      { title: '#2', dataIndex: 'measured_2', key: 'measured_2', width: 72 },
                                      { title: '#3', dataIndex: 'measured_3', key: 'measured_3', width: 72 },
                                      {
                                        title: 'Mean',
                                        key: 'mean_c',
                                        width: 96,
                                        render: (_, r) => {
                                          const m = r._computedMean;
                                          const display = m == null ? '—' : fmt4(m);
                                          if (r._status === 'within') return <Text strong style={{ color: '#15803d' }}>{display}</Text>;
                                          if (r._status === 'out') return <Text strong style={{ color: '#dc2626' }}>{display}</Text>;
                                          return <Text style={{ color: '#4b5563' }}>{display}</Text>;
                                        },
                                      },
                                      {
                                        title: 'Status',
                                        key: 'st',
                                        width: 118,
                                        render: (_, r) => {
                                          if (r._status === 'within') return <Tag color="success" style={{ margin: 0, borderRadius: 10 }}>Within</Tag>;
                                          if (r._status === 'out') return <Tag color="error" style={{ margin: 0, borderRadius: 10 }}>Out Tol</Tag>;
                                          if (r._status === 'no_tolerance') return <Tag color="processing" style={{ margin: 0, borderRadius: 10 }}>No Tol</Tag>;
                                          return <Tag style={{ margin: 0, borderRadius: 10 }}>Pending</Tag>;
                                        },
                                      },
                                    ],
                                  },
                                ]}
                              />
                            </>
                          )}
                        </div>
                        <Text type="secondary" style={{ fontSize: 12 }}>
                          Approval unlocks quantity 2+ for operators.
                        </Text>
                      </div>
                    </div>
                  </div>

                  <div style={{ border: '1px solid #dfe4ea', borderRadius: 10, overflow: 'hidden', background: '#fff', display: 'flex', flexDirection: 'column', boxShadow: '0 2px 10px rgba(15,23,42,0.04)' }}>
                    <div style={{ padding: '10px 14px', borderBottom: '1px solid #eef0f3', background: '#fafbfc', display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
                      <Text strong style={{ color: '#111827', fontFamily: '"JetBrains Mono", "Consolas", "Courier New", monospace' }}>Drawing View</Text>
                      <Button size="small" icon={<CloudDownloadOutlined />} onClick={handleDownloadPlanDrawing} disabled={!planDrawingUrl}>
                        Download Drawing
                      </Button>
                    </div>
                    <div style={{ flex: 1, minHeight: 0, padding: 10, display: 'flex', alignItems: 'center', justifyContent: 'center', background: '#f8fafc' }}>
                      {ftpApproveLoading ? (
                        <div style={{ height: '100%', display: 'flex', alignItems: 'center', justifyContent: 'center' }}><Spin /></div>
                      ) : planDrawingUrl ? (
                        planDrawingIsPdf ? (
                          <iframe
                            title="Balloon document"
                            src={pdfEmbedSrcForReview(planDrawingUrl)}
                            style={{
                              width: '100%',
                              minHeight: 480,
                              height: 'min(72vh, 900px)',
                              border: '1px solid #e5e7eb',
                              borderRadius: 10,
                              background: '#fff',
                              boxShadow: '0 2px 10px rgba(15,23,42,0.08)',
                            }}
                          />
                        ) : (
                          <img
                            src={planDrawingUrl}
                            alt="Ballooned drawing"
                            style={{
                              maxWidth: '100%',
                              maxHeight: '100%',
                              objectFit: 'contain',
                              border: '1px solid #e5e7eb',
                              borderRadius: 10,
                              background: '#fff',
                              boxShadow: '0 2px 10px rgba(15,23,42,0.08)',
                            }}
                          />
                        )
                      ) : (
                        <div style={{ height: '100%', display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
                          <Empty description="No balloon document found for this operation" />
                        </div>
                      )}
                    </div>
                  </div>
                </div>
              </Modal>

              {/* Modal for 2D Drawing Preview */}
              <Modal
                title={previewTitle || "Drawing Preview"}
                centered
                footer={null}
                width="90%"
                onCancel={() => setPreviewModalVisible(false)}
                open={previewModalVisible}
                styles={{ body: { padding: 0, height: '80vh' } }}
              >
                <div style={{ width: '100%', height: '100%', background: '#fff' }}>
                  {previewUrl ? (
                    previewIsPdf ? (
                      <iframe 
                        src={pdfEmbedSrcForReview(previewUrl)} 
                        width="100%" 
                        height="100%" 
                        style={{ border: 'none' }}
                        title="Drawing PDF"
                      />
                    ) : (
                      <img 
                        src={previewUrl} 
                        alt="Drawing" 
                        style={{ width: '100%', height: '100%', objectFit: 'contain' }}
                      />
                    )
                  ) : (
                    <div style={{ height: '100%', display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
                      <Empty description="No drawing available" />
                    </div>
                  )}
                </div>
              </Modal>

              {/* Part Inspection Overall Summary Modal */}
              <Modal
                title={`Part Inspection Overview: ${selectedItem?.part_name || 'Part'}`}
                centered
                open={partInspectionModalOpen}
                onCancel={() => setPartInspectionModalOpen(false)}
                footer={[
                  <Button key="close" onClick={() => setPartInspectionModalOpen(false)}>Close</Button>
                ]}
                width={1100}
                styles={{ body: { maxHeight: '75vh', overflow: 'auto' } }}
              >
                <Space direction="vertical" style={{ width: '100%' }} size="large">
                  <Alert 
                    message="Consolidated Inspection View" 
                    description="This view shows the quality status of every operation in the manufacturing plan for this part. You can review measurement summaries and drill down into specific recorded data."
                    type="info"
                    showIcon
                  />
                  <Table
                    size="small"
                    loading={partInspectionLoading}
                    dataSource={Object.values(partInspectionSummaryByOp).sort((a, b) => a.opNo - b.opNo)}
                    rowKey="opNo"
                    pagination={false}
                    columns={[
                      { 
                        title: 'Op #', 
                        dataIndex: 'opNo', 
                        width: 90,
                        render: (v) => <Text strong>{v}</Text>
                      },
                      { title: 'Operation Name', dataIndex: 'opName' },
                      { 
                        title: 'Measurement Status', 
                        key: 'progress',
                        render: (_, r) => (
                          <Space wrap>
                            <Tag color="blue">{r.total} Features</Tag>
                            {r.total > 0 && <Tag color="green">{r.within} Passed</Tag>}
                            {r.out > 0 && <Tag color="red">{r.out} Failed</Tag>}
                            {!r.any_recorded && <Tag color="warning">Pending Shopfloor</Tag>}
                          </Space>
                        )
                      },
                      {
                        title: 'Yield',
                        key: 'passRate',
                        width: 100,
                        align: 'center',
                        render: (_, r) => {
                          const rate = r.total ? (r.within / r.total * 100).toFixed(1) : '0.0';
                          return (
                            <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center' }}>
                              <Text strong style={{ color: Number(rate) === 100 ? '#52c41a' : Number(rate) > 0 ? '#1890ff' : '#999' }}>
                                {rate}%
                              </Text>
                            </div>
                          );
                        }
                      },
                      {
                        title: 'Actions',
                        key: 'action',
                        width: 180,
                        align: 'center',
                        render: (_, r) => (
                          <Button 
                            size="small" 
                            type="primary"
                            ghost
                            icon={<CheckCircleOutlined />} 
                            onClick={() => {
                              const opRecord = operations.find(o => parseOpNo(o) === r.opNo);
                              if (opRecord) openMeasurementsModal(opRecord);
                            }}
                            disabled={!r.any_recorded}
                          >
                            Inspection Data
                          </Button>
                        )
                      }
                    ]}
                  />
                </Space>
              </Modal>
            </div>
          ) : (
            <div style={{ height: '100%', display: 'flex', alignItems: 'center', justifyContent: 'center', flexDirection: 'column', background: '#fff', borderRadius: '12px', border: '1px solid #f0f0f0' }}>
              <Empty description={
                <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', gap: '8px' }}>
                  <Text type="secondary">No item selected</Text>
                  <Text type="secondary" style={{ fontSize: '12px' }}>Choose a product or part from the sidebar to view quality details</Text>
                </div>
              } image={Empty.PRESENTED_IMAGE_SIMPLE} />
            </div>
          )}
        </Content>
      </Layout>
    </div>
  );
};

export default QualityManagement;
