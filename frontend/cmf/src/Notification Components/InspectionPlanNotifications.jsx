import React, { useState, useEffect, useCallback, useMemo } from 'react';
import { Table, Button, message, Spin, Empty, Tag, Input, Space } from 'antd';
import { CheckCircleOutlined, LinkOutlined } from '@ant-design/icons';
import { useLocation, useNavigate } from 'react-router-dom';
import dayjs from 'dayjs';
import axios from 'axios';
import { QUALITY_API_BASE_URL } from '../Config/qualityconfig';

const InspectionPlanNotifications = ({ dateRange, onCount }) => {
  const location = useLocation();
  const navigate = useNavigate();
  const isSupervisor = location.pathname.startsWith('/supervisor');
  const inspectorBase = isSupervisor ? '/supervisor/qms-inspector' : '/admin/qms-inspector';

  const [notifications, setNotifications] = useState([]);
  const [loading, setLoading] = useState(true);
  const [openingId, setOpeningId] = useState(null);
  const [currentPage, setCurrentPage] = useState(1);
  const [pageSize, setPageSize] = useState(10);
  const [query, setQuery] = useState('');

  const fetchNotifications = useCallback(async () => {
    setLoading(true);
    try {
      const res = await axios.get(`${QUALITY_API_BASE_URL}/operator/inspection-plan-notifications`);
      const data = Array.isArray(res.data) ? res.data : [];
      setNotifications(data);
      if (onCount) onCount(data.filter((n) => !n.is_ack).length);
    } catch (error) {
      console.error(error);
      message.error(error.response?.data?.detail || error.message || 'Failed to load notifications');
    } finally {
      setLoading(false);
    }
  }, [onCount]);

  useEffect(() => {
    fetchNotifications();
  }, [fetchNotifications]);

  const filtered = useMemo(() => {
    let rows = notifications;
    const q = query.trim().toLowerCase();
    if (q) {
      rows = rows.filter(
        (n) =>
          String(n.sale_order_number || '')
            .toLowerCase()
            .includes(q) ||
          String(n.part_number || '')
            .toLowerCase()
            .includes(q) ||
          String(n.requested_by_username || '')
            .toLowerCase()
            .includes(q),
      );
    }
    if (dateRange?.[0]) {
      const start = dayjs(dateRange[0]).startOf('day');
      rows = rows.filter((n) => n.created_at && !dayjs(n.created_at).isBefore(start));
    }
    if (dateRange?.[1]) {
      const end = dayjs(dateRange[1]).endOf('day');
      rows = rows.filter((n) => n.created_at && !dayjs(n.created_at).isAfter(end));
    }
    return rows;
  }, [notifications, query, dateRange]);

  const handleAcknowledge = async (id) => {
    let ackBy = '';
    try {
      const u = JSON.parse(localStorage.getItem('user') || '{}');
      ackBy = (u.user_name || u.username || '').trim();
    } catch {
      /* ignore */
    }
    if (!ackBy) {
      message.error('Could not read your username. Please log in again.');
      return;
    }
    try {
      await axios.put(`${QUALITY_API_BASE_URL}/operator/inspection-plan-notifications/${id}/ack`, {
        ack_by: ackBy,
      });
      message.success('Acknowledged.');
      fetchNotifications();
    } catch (error) {
      console.error(error);
      message.error(error.response?.data?.detail || error.message || 'Failed to acknowledge');
    }
  };

  /** Open QMS Inspector for this notification’s part + operation (same context as Quality Management → Inspect). */
  const openInspectorForRecord = async (record) => {
    const opId = record.operation_id;
    if (opId == null) {
      message.error('This request is missing operation context.');
      return;
    }
    setOpeningId(record.id);
    try {
      const [opRes, orderRes, docsRes] = await Promise.all([
        axios.get(`${QUALITY_API_BASE_URL}/operations/${opId}`),
        axios.get(`${QUALITY_API_BASE_URL}/orders/${record.order_id}`),
        axios.get(`${QUALITY_API_BASE_URL}/operation-documents/operation/${opId}`),
      ]);
      const op = opRes.data;
      const order = orderRes.data;
      const docs = Array.isArray(docsRes.data) ? docsRes.data : [];
      const partId = op.part_id;
      if (partId == null) {
        message.error('This operation has no part linked.');
        return;
      }
      const partRes = await axios.get(`${QUALITY_API_BASE_URL}/parts/${partId}`);
      const part = partRes.data;

      const doc = docs[0];
      const apiDocumentId = doc?.id;
      const fileName = doc?.document_name || 'Drawing.pdf';
      const drawingUrl = apiDocumentId
        ? `${QUALITY_API_BASE_URL}/operation-documents/${apiDocumentId}/preview`
        : '';
      const nameLower = (fileName || '').toLowerCase();
      const isPdf = nameLower.endsWith('.pdf') || nameLower.includes('pdf') || !apiDocumentId;

      const opParts = [];
      if (op.operation_number != null && op.operation_number !== '') opParts.push(String(op.operation_number));
      if (op.operation_name) opParts.push(op.operation_name);
      const operationLabel = opParts.join(': ') || `OP ${record.op_no ?? '—'}`;

      const qs = new URLSearchParams({
        drawingUrl: drawingUrl || '',
        isPdf: String(isPdf),
        fileName: fileName || '',
        projectName: order?.product_name || '',
        partName: part?.part_name || part?.part_number || '',
        operationName: operationLabel,
        partId: String(partId),
        partNumber: part?.part_number || record.part_number || '',
        operationNumber: String(op.operation_number ?? record.op_no ?? ''),
        operationId: String(opId),
        orderId: String(record.order_id),
        mode: 'PLAN',
      });
      if (apiDocumentId != null) qs.set('documentId', String(apiDocumentId));

      navigate(`${inspectorBase}?${qs.toString()}`);
    } catch (e) {
      console.error(e);
      message.error(
        typeof e.response?.data?.detail === 'string'
          ? e.response.data.detail
          : e.message || 'Could not open inspector',
      );
    } finally {
      setOpeningId(null);
    }
  };

  const columns = [
    {
      title: 'Sl No',
      key: 'sl_no',
      width: 72,
      render: (_, __, index) => (currentPage - 1) * pageSize + index + 1,
    },
    {
      title: 'Order',
      dataIndex: 'sale_order_number',
      key: 'sale_order_number',
      render: (text, record) => text || `ID ${record.order_id}`,
    },
    {
      title: 'Part',
      dataIndex: 'part_number',
      key: 'part_number',
    },
    {
      title: 'OP',
      dataIndex: 'op_no',
      key: 'op_no',
      width: 72,
    },
    {
      title: 'Requested by',
      dataIndex: 'requested_by_username',
      key: 'requested_by_username',
      render: (t) => t || '—',
    },
    {
      title: 'Created',
      dataIndex: 'created_at',
      key: 'created_at',
      render: (text) => (text ? dayjs(text).format('DD/MM/YYYY HH:mm') : '—'),
    },
    {
      title: 'Status',
      dataIndex: 'is_ack',
      key: 'is_ack',
      render: (is_ack) => (
        <Tag color={is_ack ? 'green' : 'orange'}>{is_ack ? 'Acknowledged' : 'Pending'}</Tag>
      ),
    },
    {
      title: 'Actions',
      key: 'actions',
      width: 300,
      render: (_, record) => (
        <Space wrap>
          {!record.is_ack ? (
            <Button
              type="primary"
              icon={<CheckCircleOutlined />}
              onClick={() => void handleAcknowledge(record.id)}
            >
              Acknowledge
            </Button>
          ) : null}
          <Button
            icon={<LinkOutlined />}
            type={record.is_ack ? 'primary' : 'default'}
            loading={openingId === record.id}
            onClick={() => void openInspectorForRecord(record)}
          >
            Open inspector
          </Button>
        </Space>
      ),
    },
  ];

  return (
    <div>
      <div style={{ marginBottom: 12, maxWidth: 360 }}>
        <Input.Search
          allowClear
          placeholder="Search order, part, operator…"
          onSearch={setQuery}
          onChange={(e) => setQuery(e.target.value)}
        />
      </div>
      <Spin spinning={loading}>
        <Table
          rowKey="id"
          dataSource={filtered}
          columns={columns}
          pagination={{
            current: currentPage,
            pageSize,
            onChange: (p, ps) => {
              setCurrentPage(p);
              setPageSize(ps);
            },
            showSizeChanger: true,
          }}
          locale={{ emptyText: <Empty description="No inspection plan requests" /> }}
        />
      </Spin>
    </div>
  );
};

export default InspectionPlanNotifications;
