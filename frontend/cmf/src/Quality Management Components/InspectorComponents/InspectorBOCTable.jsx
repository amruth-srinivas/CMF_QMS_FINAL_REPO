import React, { useCallback, useEffect, useMemo, useRef } from 'react';
import { Table, Tag, Typography, Space, Button, Empty, Popover, Select, Divider, Input } from 'antd';
import { FilterOutlined, UnorderedListOutlined } from '@ant-design/icons';

const { Text } = Typography;

const M_FIELDS = ['m1', 'm2', 'm3'];
const API_M = { m1: 'measured_1', m2: 'measured_2', m3: 'measured_3' };

function dimTypeColor(type) {
  const s = (type || '').toString();
  if (!s || s === '—') return '#8c8c8c';
  const u = s.toUpperCase();
  const compact = u.replace(/[^A-Z0-9]/g, '');
  if (compact.includes('GDT') || u.includes('GD&T')) return '#722ed1';
  if (u.includes('SURFACE') || u.includes('ROUGH')) return '#faad14';
  if (u.includes('MATERIAL') || u.includes('NOTE')) return '#8c8c8c';
  // Diameter / ⌀ — distinct from generic DIM (blue) and GDT (purple)
  if (u.includes('DIAMETER') || u.includes('∅') || u.includes('⌀') || /\bDIA\b/i.test(s)) return '#db6f21';
  return '#1890ff';
}

function parseMeasurementNum(s) {
  if (s == null || s === '') return null;
  const t = String(s).trim();
  if (t === '—' || t === '-') return null;
  const n = parseFloat(t.replace(',', '.'));
  return Number.isFinite(n) ? n : null;
}

/** Format mean for API / display (trim trailing zeros). */
function formatMean(a, b, c) {
  const mean = (a + b + c) / 3;
  if (!Number.isFinite(mean)) return null;
  const s = mean.toFixed(6).replace(/\.?0+$/, '');
  return s === '-0' ? '0' : s;
}

function computeMeanFromStrings(m1, m2, m3) {
  const a = parseMeasurementNum(m1);
  const b = parseMeasurementNum(m2);
  const c = parseMeasurementNum(m3);
  const vals = [a, b, c].filter((v) => v != null);
  if (!vals.length) return null;
  const sum = vals.reduce((acc, v) => acc + v, 0);
  const mean = sum / vals.length;
  if (!Number.isFinite(mean)) return null;
  const s = mean.toFixed(6).replace(/\.?0+$/, '');
  return s === '-0' ? '0' : s;
}

function measurePassFail(record) {
  if (!record.stageInspectionId) return null;
  const raw = record.actualValue;
  if (raw == null || String(raw).trim() === '') return null;
  const actual = parseMeasurementNum(raw);
  const nominal = parseMeasurementNum(record.nominal);
  if (actual == null || nominal == null) return null;
  // Tolerance magnitude is what matters for bounds; LTOL can be stored/displayed with a minus sign.
  const ut = Math.abs(Number(record.uppertolNum) || 0);
  const lt = Math.abs(Number(record.lowertolNum) || 0);
  const hi = nominal + ut;
  const lo = nominal - lt;
  if (actual > hi || actual < lo) return 'fail';
  return 'pass';
}

const cellCenter = { textAlign: 'center' };

/** MEASURE: keep width compact to reduce horizontal scrolling */
const MEASURE_SCROLL_X = 820;

function focusMeasureInput(rowId, field) {
  const el = document.querySelector(
    `input[data-measure-row="${rowId}"][data-measure-field="${field}"]`,
  );
  el?.focus();
  el?.select?.();
}

function readMeasureInputs(rowId) {
  const out = { m1: '', m2: '', m3: '' };
  for (const f of M_FIELDS) {
    const el = document.querySelector(`input[data-measure-row="${rowId}"][data-measure-field="${f}"]`);
    out[f] = el?.value ?? '';
  }
  return out;
}

const InspectorBOCTable = ({
  selectedIds = [],
  onSelectedIdsChange,
  onDeleteSelected,
  dataSource = [],
  totalCount,
  optionSource = [],
  filterDimTypes = [],
  filterZones = [],
  onFilterDimTypesChange,
  onFilterZonesChange,
  measureMode = false,
  onMeasurePatch,
  quantityOptions = [{ value: 1, label: 'Quantity 1' }],
  quantityNo = 1,
  onQuantityChange,
  quantityLocked = false,
  /** Hide plan editing actions (e.g. after plan is confirmed) */
  planEditLocked = false,
}) => {
  const rangeAnchorIndexRef = useRef(null);
  const tableScrollRef = useRef(null);
  const suppressRowClickRef = useRef(false);
  const dragStateRef = useRef({ down: false, moved: false, startX: 0, startY: 0, scrollL: 0, scrollT: 0 });

  useEffect(() => {
    rangeAnchorIndexRef.current = null;
  }, [dataSource]);

  /** MEASURE: click-drag to pan scroll area (not when interacting with inputs). */
  useEffect(() => {
    const el = tableScrollRef.current;
    if (!el || !measureMode) return;

    const onDown = (e) => {
      if (e.button !== 0) return;
      if (e.target.closest?.('input, textarea, button, a, .ant-select, [role="combobox"]')) return;
      dragStateRef.current = {
        down: true,
        moved: false,
        startX: e.clientX,
        startY: e.clientY,
        scrollL: el.scrollLeft,
        scrollT: el.scrollTop,
      };
    };
    const onMove = (e) => {
      const st = dragStateRef.current;
      if (!st.down) return;
      const dx = e.clientX - st.startX;
      const dy = e.clientY - st.startY;
      if (Math.abs(dx) > 4 || Math.abs(dy) > 4) {
        st.moved = true;
        el.scrollLeft = st.scrollL - dx;
        el.scrollTop = st.scrollT - dy;
        e.preventDefault();
      }
    };
    const onUp = () => {
      const st = dragStateRef.current;
      if (st.moved) {
        suppressRowClickRef.current = true;
        window.setTimeout(() => {
          suppressRowClickRef.current = false;
        }, 0);
      }
      st.down = false;
      st.moved = false;
    };

    el.addEventListener('mousedown', onDown);
    window.addEventListener('mousemove', onMove);
    window.addEventListener('mouseup', onUp);
    return () => {
      el.removeEventListener('mousedown', onDown);
      window.removeEventListener('mousemove', onMove);
      window.removeEventListener('mouseup', onUp);
    };
  }, [measureMode]);

  const dimTypeOptions = useMemo(() => {
    const set = new Set();
    optionSource.forEach((r) => {
      if (r.dimType) set.add(r.dimType);
    });
    return [...set].sort().map((v) => ({ value: v, label: v }));
  }, [optionSource]);

  const zoneOptions = useMemo(() => {
    const set = new Set();
    optionSource.forEach((r) => {
      if (r.zone) set.add(r.zone);
    });
    return [...set].sort().map((v) => ({ value: v, label: v }));
  }, [optionSource]);

  const filterActive = filterDimTypes.length > 0 || filterZones.length > 0;

  const filterContent = (
    <div style={{ width: 260 }}>
      <Text type="secondary" style={{ fontSize: 11, display: 'block', marginBottom: 8 }}>
        Dimension type
      </Text>
      <Select
        mode="multiple"
        allowClear
        placeholder="All types"
        style={{ width: '100%', marginBottom: 12 }}
        options={dimTypeOptions}
        value={filterDimTypes}
        onChange={onFilterDimTypesChange}
        maxTagCount="responsive"
      />
      <Text type="secondary" style={{ fontSize: 11, display: 'block', marginBottom: 8 }}>
        Zone
      </Text>
      <Select
        mode="multiple"
        allowClear
        placeholder="All zones"
        style={{ width: '100%', marginBottom: 12 }}
        options={zoneOptions}
        value={filterZones}
        onChange={onFilterZonesChange}
        maxTagCount="responsive"
      />
      <Divider style={{ margin: '8px 0' }} />
      <Button
        size="small"
        type="link"
        onClick={() => {
          onFilterDimTypesChange?.([]);
          onFilterZonesChange?.([]);
        }}
        disabled={!filterActive}
        style={{ padding: 0 }}
      >
        Clear filters
      </Button>
    </div>
  );

  const maybePatchMean = useCallback(
    async (record) => {
      if (!record.stageInspectionId || !onMeasurePatch) return;
      const { m1, m2, m3 } = readMeasureInputs(record.id);
      const meanStr = computeMeanFromStrings(m1, m2, m3);
      if (meanStr == null) return;
      await onMeasurePatch(record.stageInspectionId, { measured_mean: meanStr });
    },
    [onMeasurePatch],
  );

  const handleMeasureKeyDown = useCallback(
    (e, record, rowIndex, field) => {
      if (!record.stageInspectionId || record.measureLocked) return;
      const rowId = record.id;
      const idx = M_FIELDS.indexOf(field);
      if (idx < 0) return;

      if (e.key === 'ArrowRight') {
        e.preventDefault();
        if (idx < 2) focusMeasureInput(rowId, M_FIELDS[idx + 1]);
      } else if (e.key === 'ArrowLeft') {
        e.preventDefault();
        if (idx > 0) focusMeasureInput(rowId, M_FIELDS[idx - 1]);
      } else if (e.key === 'Enter') {
        e.preventDefault();
        if (idx < 2) {
          focusMeasureInput(rowId, M_FIELDS[idx + 1]);
          return;
        }
        const { m1, m2, m3 } = readMeasureInputs(rowId);
        const patch = async () => {
          const meanStr = computeMeanFromStrings(m1, m2, m3);
          const a = parseMeasurementNum(m1);
          const b = parseMeasurementNum(m2);
          const c = parseMeasurementNum(m3);
          const payload = {
            measured_1: m1,
            measured_2: m2,
            measured_3: m3,
          };
          if (meanStr != null) payload.measured_mean = meanStr;
          if (a != null && b != null && c != null) payload.is_done = true;
          await onMeasurePatch?.(record.stageInspectionId, payload);
        };
        void patch().then(() => {
          const next = dataSource[rowIndex + 1];
          if (next?.stageInspectionId) {
            requestAnimationFrame(() => focusMeasureInput(next.id, 'm1'));
          }
        });
      }
    },
    [dataSource, onMeasurePatch],
  );

  const renderMInput = useCallback(
    (field, width) => (v, record, rowIndexArg) => {
      const showInput = measureMode && record.stageInspectionId;
      const rowIndex =
        typeof rowIndexArg === 'number' ? rowIndexArg : dataSource.findIndex((r) => r.id === record.id);
      if (!showInput) {
        const display = v != null && String(v).trim() !== '' ? String(v) : '—';
        return (
          <div style={cellCenter}>
            <Text style={{ fontSize: '11px' }}>{display}</Text>
          </div>
        );
      }
      const apiKey = API_M[field];
      const locked = Boolean(record.measureLocked);
      return (
        <div style={cellCenter}>
          <Input
            key={`m-${record.id}-${record.stageInspectionId}-${field}`}
            data-measure-row={record.id}
            data-measure-field={field}
            size="small"
            defaultValue={v ?? ''}
            disabled={locked}
            onBlur={(e) => {
              if (locked) return;
              const { m1, m2, m3 } = readMeasureInputs(record.id);
              const meanStr = computeMeanFromStrings(m1, m2, m3);
              const a = parseMeasurementNum(m1);
              const b = parseMeasurementNum(m2);
              const c = parseMeasurementNum(m3);
              const payload = {
                measured_1: m1,
                measured_2: m2,
                measured_3: m3,
              };
              if (meanStr != null) payload.measured_mean = meanStr;
              payload.is_done = a != null && b != null && c != null;
              onMeasurePatch?.(record.stageInspectionId, payload);
              if (payload.is_done) {
                void maybePatchMean(record);
              }
            }}
            onKeyDown={(e) => handleMeasureKeyDown(e, record, rowIndex, field)}
            style={{ width, fontSize: 11, paddingInline: 6 }}
          />
        </div>
      );
    },
    [measureMode, dataSource, onMeasurePatch, maybePatchMean, handleMeasureKeyDown],
  );

  const renderActualDisplay = useCallback(
    (v, record) => {
      if (!measureMode || !record.stageInspectionId) {
        const display = v != null && String(v).trim() !== '' ? String(v) : '—';
        return (
          <div style={cellCenter}>
            <Text style={{ fontSize: '11px' }}>{display}</Text>
          </div>
        );
      }
      const display = v != null && String(v).trim() !== '' ? String(v) : '—';
      return (
        <div style={cellCenter}>
          <Text strong style={{ fontSize: '11px', color: '#262626' }}>
            {display}
          </Text>
        </div>
      );
    },
    [measureMode],
  );

  const columns = useMemo(() => {
    const baseCols = [
      {
        title: 'ID',
        dataIndex: 'balloonNo',
        key: 'balloonNo',
        width: 46,
        align: 'center',
        render: (n) => (
          <Text style={{ color: '#595959', fontSize: 11 }}>
            {n}
          </Text>
        ),
      },
      {
        title: 'NOMINAL',
        dataIndex: 'nominal',
        key: 'nominal',
        width: 78,
        align: 'center',
        render: (nominal) => (
          <Text strong style={{ fontSize: '11px' }}>
            {nominal}
          </Text>
        ),
      },
      {
        title: 'UTOL',
        dataIndex: 'tolPlus',
        key: 'tolPlus',
        width: 56,
        align: 'center',
        render: (val) => (
          <Text style={{ color: val !== '-' && val !== '—' ? '#52c41a' : '#bfbfbf', fontSize: 11 }}>{val}</Text>
        ),
      },
      {
        title: 'LTOL',
        dataIndex: 'tolMinus',
        key: 'tolMinus',
        width: 56,
        align: 'center',
        render: (val) => (
          <Text style={{ color: val !== '-' && val !== '—' ? '#ff4d4f' : '#bfbfbf', fontSize: 11 }}>{val}</Text>
        ),
      },
      {
        title: 'DIM TYPE',
        dataIndex: 'dimType',
        key: 'dimType',
        width: 108,
        align: 'left',
        /** Colored left accent: thickness matches dim type (header stays neutral). */
        onHeaderCell: () => ({
          style: { borderLeft: '3px solid #bfbfbf' },
        }),
        onCell: (record) => ({
          style: { borderLeft: `2.8px solid ${dimTypeColor(record.dimType)}` },
        }),
        render: (type) => (
          <Text
            style={{
              fontSize: '11px',
              fontWeight: 800,
              color: dimTypeColor(type),
              letterSpacing: '0.02em',
            }}
          >
            {type}
          </Text>
        ),
      },
      {
        title: 'ZONE',
        dataIndex: 'zone',
        key: 'zone',
        width: 52,
        align: 'center',
        render: (zone) => (
          <Text strong style={{ fontSize: '11px' }}>
            {zone}
          </Text>
        ),
      },
      {
        title: 'INSTRUMENT',
        dataIndex: 'instrument',
        key: 'instrument',
        width: 84,
        align: 'center',
        render: (instr) => <Text style={{ fontSize: '11px' }}>{instr}</Text>,
      },
    ];

    const actualCol = {
      title: 'ACTUAL',
      dataIndex: 'actualValue',
      key: 'actualValue',
      width: 64,
      align: 'center',
      render: renderActualDisplay,
    };
    const m1Col = {
      title: 'M1',
      dataIndex: 'm1',
      key: 'm1',
      width: 58,
      align: 'center',
      render: (v, record, i) => renderMInput('m1', 52)(v, record, i),
    };
    const m2Col = {
      title: 'M2',
      dataIndex: 'm2',
      key: 'm2',
      width: 58,
      align: 'center',
      render: (v, record, i) => renderMInput('m2', 52)(v, record, i),
    };
    const m3Col = {
      title: 'M3',
      dataIndex: 'm3',
      key: 'm3',
      width: 58,
      align: 'center',
      render: (v, record, i) => renderMInput('m3', 52)(v, record, i),
    };

    if (measureMode) {
      return [
        baseCols[0],
        baseCols[1],
        actualCol,
        baseCols[2],
        baseCols[3],
        baseCols[4],
        baseCols[5],
        m1Col,
        m2Col,
        m3Col,
        baseCols[6],
      ];
    }
    return baseCols;
  }, [measureMode, renderMInput, renderActualDisplay]);

  const countTotal = totalCount ?? dataSource.length;
  const badge = filterActive ? `${dataSource.length} / ${countTotal}` : String(dataSource.length);

  const selectedSet = useMemo(() => new Set(selectedIds), [selectedIds]);

  const handleRowClick = useCallback(
    (record, index, e) => {
      if (suppressRowClickRef.current) return;
      if (e.target?.closest?.('input, textarea, button, .ant-select, .ant-input')) {
        return;
      }
      if (e.shiftKey && rangeAnchorIndexRef.current != null) {
        const a = Math.min(rangeAnchorIndexRef.current, index);
        const b = Math.max(rangeAnchorIndexRef.current, index);
        const ids = dataSource.slice(a, b + 1).map((r) => r.id);
        onSelectedIdsChange?.(ids, record.id);
        return;
      }
      rangeAnchorIndexRef.current = index;
      onSelectedIdsChange?.([record.id], record.id);
    },
    [dataSource, onSelectedIdsChange],
  );

  const tableScroll = measureMode ? { x: MEASURE_SCROLL_X, y: '100%' } : { y: '100%' };

  return (
    <div
      style={{
        flex: 1,
        minHeight: 0,
        display: 'flex',
        flexDirection: 'column',
        background: '#fff',
        overflow: 'hidden',
      }}
    >
      <div
        style={{
          padding: '6px 8px',
          borderBottom: '1px solid #f0f0f0',
          display: 'flex',
          justifyContent: 'space-between',
          alignItems: 'center',
          flexWrap: 'wrap',
          gap: 4,
          flexShrink: 0,
        }}
      >
        <Space wrap>
          <UnorderedListOutlined style={{ fontSize: 16, color: '#1890ff' }} />
          <Text strong style={{ fontSize: '12px', textTransform: 'uppercase' }}>
            Characteristics
          </Text>
          <Tag color="blue" bordered={false} style={{ margin: 0, borderRadius: '4px', fontSize: '9px' }}>
            {badge}
          </Tag>
        </Space>
        <Space wrap>
          {measureMode && (
            <Space size={6} align="center">
              <Text style={{ fontSize: 11 }}>Quantity :</Text>
              <Select
                size="small"
                style={{ minWidth: 120 }}
                value={quantityNo}
                options={(quantityOptions || []).map((q) => ({
                  ...q,
                  disabled: quantityLocked && Number(q?.value) > 1,
                }))}
                onChange={onQuantityChange}
                showSearch={false}
              />
            </Space>
          )}
          {typeof onDeleteSelected === 'function' && !planEditLocked && (
            <Button
              size="small"
              danger
              disabled={!selectedIds.length}
              onClick={onDeleteSelected}
              style={{ fontSize: '9px' }}
            >
              Delete
            </Button>
          )}
          <Popover content={filterContent} title="Filter" trigger="click" placement="bottomRight">
            <Button
              size="small"
              type={filterActive ? 'primary' : 'text'}
              icon={
                <FilterOutlined style={{ fontSize: 14, color: filterActive ? undefined : '#64748b' }} />
              }
            />
          </Popover>
        </Space>
      </div>

      <div
        ref={tableScrollRef}
        className="qms-boc-table-wrap"
        style={{
          flex: 1,
          minHeight: 0,
          overflow: 'hidden',
          overscrollBehavior: 'contain',
          cursor: measureMode ? 'grab' : 'default',
        }}
      >
        {dataSource.length === 0 ? (
          <Empty
            image={Empty.PRESENTED_IMAGE_SIMPLE}
            description={countTotal ? 'No rows match filters' : 'Choose Select or Stamp, then use the tools on the drawing'}
            style={{ marginTop: 24 }}
          />
        ) : (
          <Table
            rowKey="id"
            columns={columns}
            dataSource={dataSource}
            size="small"
            bordered
            pagination={false}
            tableLayout="fixed"
            scroll={tableScroll}
            onRow={(record, rowIndex) => {
              const pf = measureMode ? measurePassFail(record) : null;
              const selected = selectedSet.has(record.id);
              let bg;
              if (pf === 'pass') bg = '#f6ffed';
              else if (pf === 'fail') bg = '#fff1f0';
              else if (selected) bg = '#e6f4ff';
              return {
                onClick: (e) => handleRowClick(record, rowIndex, e),
                style: {
                  cursor: 'pointer',
                  background: bg,
                  boxShadow: selected ? 'inset 3px 0 0 #1890ff' : undefined,
                },
              };
            }}
            style={{ fontFamily: '"JetBrains Mono", "Consolas", "Courier New", monospace', fontSize: 11 }}
          />
        )}
      </div>
    </div>
  );
};

export default InspectorBOCTable;
