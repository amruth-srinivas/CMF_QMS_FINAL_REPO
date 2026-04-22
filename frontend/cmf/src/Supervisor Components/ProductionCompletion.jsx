import React, { useState, useEffect, useCallback } from 'react';
import {Table, Card, Typography, Tag, message, Button, Space,Tooltip, Empty, Grid, Modal, Input} from 'antd';
import {CheckCircleOutlined,ClockCircleOutlined,SyncOutlined,ReloadOutlined,EditOutlined,CheckSquareOutlined,} from '@ant-design/icons';
import dayjs from 'dayjs';
import config from '../Config/config';

const { Title, Text } = Typography;
const { TextArea } = Input;
const { useBreakpoint } = Grid;

const ProductionCompletion = () => {
  const [logs, setLogs] = useState([]);
  const [loading, setLoading] = useState(false);
  const [refreshing, setRefreshing] = useState(false);

  // ── Remark modal state ────────────────────────────────────────────────────
  const [remarkModal, setRemarkModal] = useState({
    visible: false,
    log: null,
    newStatus: '',
    remark: '',
    approvedQuantity: 0,
  });

  const screens = useBreakpoint();
  const isMobile = !screens.md;

  const getSupervisorId = () => {
    const storedUser = localStorage.getItem('user');
    if (storedUser) {
      try {
        const user = JSON.parse(storedUser);
        return user.id;
      } catch (e) {
        console.error('Error parsing user from localStorage', e);
      }
    }
    return null;
  };

  const supervisorId = getSupervisorId();

  const fetchLogs = useCallback(async () => {
    if (!supervisorId) {
      message.error('Supervisor ID not found in session. Please log in again.');
      return;
    }

    setLoading(true);
    try {
      const response = await fetch(`${config.API_BASE_URL}/production-logs/`);
      if (!response.ok) throw new Error('Failed to fetch production logs');

      const allLogs = await response.json();

      const supervisorLogs = allLogs.filter(
        (log) =>
          log.supervisor_id === null ||
          String(log.supervisor_id) === String(supervisorId)
      );

      if (supervisorLogs.length === 0) {
        setLogs([]);
        return;
      }

      const enrichedLogs = supervisorLogs.map((log) => {
        const operationName = log.operation?.operation_name || log.operation?.name || 'N/A';
        const operationNumber = log.operation?.operation_number || log.operation?.number || 'N/A';
        const machineName = log.machine?.make && log.machine?.model
          ? `(${log.machine.make}) ${log.machine.model}`
          : log.machine?.make || log.machine?.model || log.machine?.name || 'N/A';

        return {
          ...log,
          planned_schedule_item: {
            ...log.planned_schedule_item,
            machine_name: machineName,
            operation_name: operationName,
            operation_number: operationNumber,
          },
          operator_name: log.operator?.user_name || `Operator #${log.operator_id}`,
        };
      });

      setLogs(enrichedLogs);
    } catch (error) {
      console.error('Error fetching production logs:', error);
      message.error('Failed to load production logs. Please try again.');
    } finally {
      setLoading(false);
      setRefreshing(false);
    }
  }, [supervisorId]);

  useEffect(() => {
    fetchLogs();
  }, [fetchLogs]);

  const handleRefresh = () => {
    setRefreshing(true);
    fetchLogs();
  };

  // ── Open the remark modal ─────────────────────────────────────────────────
  const openRemarkModal = (log, newStatus) => {
    setRemarkModal({ visible: true, log, newStatus, remark: '', approvedQuantity: 0 });
  };

  const closeRemarkModal = () => {
    setRemarkModal({ visible: false, log: null, newStatus: '', remark: '', approvedQuantity: 0 });
  };

  // ── Submit status + remark ────────────────────────────────────────────────
  const handleUpdateStatus = async () => {
    const { log, newStatus, remark } = remarkModal;
    setLoading(true);

    const payload = {
      operation_id: log.operation_id,
      operator_id: log.operator_id,
      supervisor_id: supervisorId,
      notes: log.notes,
      remarks: remark || null,
      from_date: log.from_date,
      from_time: log.from_time,
      to_date: log.to_date,
      to_time: log.to_time,
      status: newStatus,
      approved_quantity: parseInt(remarkModal.approvedQuantity) || 0,
    };

    try {
      const response = await fetch(
        `${config.API_BASE_URL}/production-logs/${log.id}/status`,
        {
          method: 'PUT',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(payload),
        }
      );

      if (response.ok) {
        message.success(`Status updated to '${newStatus}'.`);
        setLogs((prev) =>
          prev.map((l) =>
            l.id === log.id ? { ...l, status: newStatus, remarks: remark || null } : l
          )
        );
        closeRemarkModal();
      } else {
        const errorData = await response.json();
        message.error(`Failed to update status: ${errorData.detail || 'Unknown error'}`);
      }
    } catch (error) {
      console.error('Error updating status:', error);
      message.error('An error occurred while updating the status.');
    } finally {
      setLoading(false);
    }
  };

  const getStatusTag = (status) => {
    switch (status?.toLowerCase()) {
      case 'completed':
        return <Tag color="success" icon={<CheckCircleOutlined />}>Completed</Tag>;
      case 'pending':
        return <Tag color="processing" icon={<SyncOutlined spin />}>Pending</Tag>;
      case 'rework':
        return <Tag color="warning" icon={<ClockCircleOutlined />}>Rework</Tag>;
      default:
        return <Tag color="default">{status || 'Unknown'}</Tag>;
    }
  };

  // ── Action buttons (labeled, like image 1) ────────────────────────────────
  const ActionButtons = ({ record }) => (
    <Space>
      <Tooltip title="Mark as Completed">
        <Button
          type="primary"
          style={{ backgroundColor: '#52c41a', borderColor: '#52c41a' }}
          icon={<CheckSquareOutlined />}
          onClick={() => openRemarkModal(record, 'completed')}
        >
          Complete
        </Button>
      </Tooltip>
      <Tooltip title="Mark as Rework">
        <Button
          type="primary"
          danger
          icon={<EditOutlined />}
          onClick={() => openRemarkModal(record, 'rework')}
        >
          Rework
        </Button>
      </Tooltip>
    </Space>
  );

  // ── Mobile: stacked cards ─────────────────────────────────────────────────
  const MobileList = () => {
    if (logs.length === 0) {
      return <Empty description="No production logs found for this supervisor" />;
    }

    return (
      <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
        {logs.map((record) => (
          <Card
            key={record.id}
            size="small"
            style={{ borderRadius: 8, boxShadow: '0 1px 4px rgba(0,0,0,0.08)' }}
            bodyStyle={{ padding: '12px 14px' }}
          >
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', marginBottom: 10 }}>
              <div>
                <Text strong style={{ fontSize: 14 }}>
                  {record.planned_schedule_item?.operation_name || 'N/A'}
                </Text>
                <br />
                <Text type="secondary" style={{ fontSize: 12 }}>
                  Op No: {record.planned_schedule_item?.operation_number || 'N/A'}
                </Text>
              </div>
              {getStatusTag(record.status)}
            </div>

            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '8px 12px', marginBottom: 10 }}>
              <div>
                <Text type="secondary" style={{ fontSize: 11 }}>Machine</Text>
                <br />
                <Text style={{ fontSize: 13 }}>{record.planned_schedule_item?.machine_name || 'N/A'}</Text>
              </div>
              <div>
                <Text type="secondary" style={{ fontSize: 11 }}>Operator</Text>
                <br />
                <Text style={{ fontSize: 13 }}>{record.operator?.user_name || 'N/A'}</Text>
              </div>
              <div>
                <Text type="secondary" style={{ fontSize: 11 }}>From</Text>
                <br />
                <Text style={{ fontSize: 13 }}>
                  {record.from_date ? dayjs(record.from_date).format('DD-MM-YYYY') : 'N/A'}
                  <br />{record.from_time || ''}
                </Text>
              </div>
              <div>
                <Text type="secondary" style={{ fontSize: 11 }}>To</Text>
                <br />
                <Text style={{ fontSize: 13 }}>
                  {record.to_date ? dayjs(record.to_date).format('DD-MM-YYYY') : 'N/A'}
                  <br />{record.to_time || ''}
                </Text>
              </div>
              <div style={{ gridColumn: '1 / -1' }}>
                <Text type="secondary" style={{ fontSize: 11 }}>Created At</Text>
                <br />
                <Text style={{ fontSize: 13 }}>
                  {record.created_at ? dayjs(record.created_at).format('DD-MM-YYYY, HH:mm:ss') : 'N/A'}
                </Text>
              </div>
              <div style={{ gridColumn: '1 / -1' }}>
                <Text type="secondary" style={{ fontSize: 11 }}>Notes</Text>
                <br />
                <Text style={{ fontSize: 13 }} title={record.notes}>
                  {record.notes && record.notes.length > 50
                    ? `${record.notes.substring(0, 50)}...`
                    : record.notes || 'N/A'}
                </Text>
              </div>
            </div>

            <div style={{ display: 'flex', justifyContent: 'flex-end', borderTop: '1px solid #f0f0f0', paddingTop: 8 }}>
              <ActionButtons record={record} />
            </div>
          </Card>
        ))}
      </div>
    );
  };

  // ── Desktop table columns ─────────────────────────────────────────────────
  const columns = [
    {
      title: 'Operation',
      key: 'operation',
      render: (_, record) => (
        <Space direction="vertical" size={0}>
          <Text strong>{record.planned_schedule_item?.operation_name || 'N/A'}</Text>
          <Text type="secondary" style={{ fontSize: '12px' }}>
            Op No: {record.planned_schedule_item?.operation_number || 'N/A'}
          </Text>
        </Space>
      ),
    },
    {
      title: 'Machine Name',
      key: 'machine',
      render: (_, record) => <Text>{record.planned_schedule_item?.machine_name || 'N/A'}</Text>,
    },
    {
      title: 'Operator',
      key: 'operator',
      render: (_, record) => <Text>{record.operator?.user_name || 'N/A'}</Text>,
    },
    {
      title: 'Notes',
      dataIndex: 'notes',
      key: 'notes',
      render: (notes) => (
        <Text style={{ fontSize: '12px' }} title={notes}>
          {notes && notes.length > 20 ? `${notes.substring(0, 20)}...` : notes || '-'}
        </Text>
      ),
    },
    {
      title: 'From Time',
      key: 'from',
      render: (_, record) => (
        <Space direction="vertical" size={0}>
          <Text style={{ fontSize: '12px' }}>
            {record.from_date ? dayjs(record.from_date).format('DD-MM-YYYY') : 'N/A'}
          </Text>
          <Text style={{ fontSize: '12px' }}>{record.from_time || 'N/A'}</Text>
        </Space>
      ),
    },
    {
      title: 'To Time',
      key: 'to',
      render: (_, record) => (
        <Space direction="vertical" size={0}>
          <Text style={{ fontSize: '12px' }}>
            {record.to_date ? dayjs(record.to_date).format('DD-MM-YYYY,') : 'N/A'}
          </Text>
          <Text style={{ fontSize: '12px' }}>{record.to_time || 'N/A'}</Text>
        </Space>
      ),
    },
    {
      title: 'Submitted At',
      dataIndex: 'created_at',
      key: 'created_at',
      render: (date) => (
        <Text style={{ fontSize: '12px' }}>
          {date ? dayjs(date).format('DD-MM-YYYY, HH:mm:ss') : 'N/A'}
        </Text>
      ),
    },
    {
      title: 'Produced Quantity',
      dataIndex: 'produced_quantity',
      key: 'produced_quantity',
      render: (quantity) => (
        <Text style={{ fontSize: '12px' }}>
          {quantity !== null && quantity !== undefined ? quantity : '-'}
        </Text>
      ),
    },
    {
      title: 'Remarks',
      dataIndex: 'remarks',
      key: 'remarks',
      render: (remarks) => (
        // <Tooltip title={remarks || ''}>
          <Text style={{ fontSize: '12px' }}>
            {remarks && remarks.length > 25 ? `${remarks.substring(0, 25)}...` : remarks || '-'}
          </Text>
        // </Tooltip>
      ),
    },
    {
      title: 'Status',
      dataIndex: 'status',
      key: 'status',
      filters: [
        { text: 'Pending', value: 'pending' },
        { text: 'Completed', value: 'completed' },
        { text: 'Rework', value: 'rework' },
      ],
      onFilter: (value, record) => record.status?.toLowerCase() === value,
      render: (status) => getStatusTag(status),
    },
    {
      title: 'Actions',
      key: 'actions',
      render: (_, record) => <ActionButtons record={record} />,
    },
  ];

  // ── Derived modal config based on action type ─────────────────────────────
  const isComplete = remarkModal.newStatus === 'completed';
  const modalTitle = isComplete ? 'Confirm Completion' : 'Confirm Rework';
  const modalOkText = isComplete ? 'Yes, Complete' : 'Yes, Rework';
  const modalOkStyle = isComplete
    ? { backgroundColor: '#52c41a', borderColor: '#52c41a' }
    : {};
  const modalIcon = isComplete
    ? <CheckSquareOutlined style={{ color: '#52c41a', fontSize: 18, marginRight: 8 }} />
    : <EditOutlined style={{ color: '#ff4d4f', fontSize: 18, marginRight: 8 }} />;
  const modalDesc = isComplete
    ? 'Are you sure you want to mark this production log as completed?'
    : 'Are you sure you want to mark this production log for rework?';

  return (
    <div style={{ padding: isMobile ? '12px' : '24px' }}>
      <Card
        title={
          <Space>
            <Title level={4} style={{ margin: 0, fontSize: isMobile ? 15 : 20 }}>
              Production Completion Monitor
            </Title>
            {refreshing && <SyncOutlined spin />}
          </Space>
        }
        extra={
          <Button
            type="default"
            icon={<ReloadOutlined />}
            onClick={handleRefresh}
            loading={refreshing}
            size={isMobile ? 'small' : 'middle'}
          >
            {!isMobile && 'Refresh'}
          </Button>
        }
        className="shadow-sm"
        bodyStyle={{ padding: isMobile ? '8px' : '24px' }}
      >
        {isMobile ? (
          loading ? (
            <div style={{ textAlign: 'center', padding: 32 }}>
              <SyncOutlined spin style={{ fontSize: 24, color: '#1677ff' }} />
            </div>
          ) : (
            <MobileList />
          )
        ) : (
          <Table
            columns={columns}
            dataSource={logs}
            rowKey="id"
            loading={loading}
            locale={{
              emptyText: (
                <Empty description="No production logs found for this supervisor" />
              ),
            }}
            pagination={{ pageSize: 10 }}
            scroll={{ x: 'max-content' }}
          />
        )}
      </Card>

      {/* ── Remark Modal ───────────────────────────────────────────────────── */}
      <Modal
        open={remarkModal.visible}
        onCancel={closeRemarkModal}
        onOk={handleUpdateStatus}
        okText={modalOkText}
        okButtonProps={{
          style: isComplete ? modalOkStyle : {},
          danger: !isComplete,
          loading: loading,
        }}
        cancelText="Cancel"
        title={
          <Space align="center">
            {modalIcon}
            <span>{modalTitle}</span>
          </Space>
        }
        destroyOnClose
      >
        <p style={{ marginBottom: 16, color: '#595959' }}>{modalDesc}</p>

        <div>
          <Text strong style={{ display: 'block', marginBottom: 6, marginTop: 12 }}>
            Approved Quantity <Text type="danger" style={{ fontWeight: 400 }}>*</Text>
          </Text>
          <Input
            type="number"
            placeholder="Enter approved quantity"
            value={remarkModal.approvedQuantity}
            onChange={(e) =>
              setRemarkModal((prev) => ({ ...prev, approvedQuantity: e.target.value }))
            }
            min={0}
            style={{ marginBottom: 8 }}
          />
          <Text strong style={{ display: 'block', marginBottom: 6 }}>
            Remark <Text type="secondary" style={{ fontWeight: 400 }}>(optional)</Text>
          </Text>
          <TextArea
            rows={4}
            placeholder="Enter your remark here..."
            value={remarkModal.remark}
            onChange={(e) =>
              setRemarkModal((prev) => ({ ...prev, remark: e.target.value }))
            }
            maxLength={500}
            showCount
          />
          
        </div>
      </Modal>
    </div>
  );
};

export default ProductionCompletion;