import React, { useCallback, useEffect, useMemo, useRef } from 'react';
import { Table, Tag, Typography, Space, Button, Empty, Popover, Select, Divider, Input, message } from 'antd';
import { FilterOutlined, UnorderedListOutlined, EditOutlined, LeftOutlined, RightOutlined } from '@ant-design/icons';

const { Text } = Typography;

// Removed hardcoded M_FIELDS and API_M constants for dynamic measurements

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
function formatMean(vals) {
  if (!Array.isArray(vals) || !vals.length) return null;
  const numVals = vals.map(v => parseMeasurementNum(v)).filter(v => v != null);
  if (!numVals.length) return null;
  const sum = numVals.reduce((acc, v) => acc + v, 0);
  const mean = sum / numVals.length;
  if (!Number.isFinite(mean)) return null;
  // User requested 2 decimal values
  const s = mean.toFixed(2);
  return s;
}

function computeMeanFromStrings(strings) {
  return formatMean(strings);
}

function checkPassFail(value, record) {
  if (value == null || String(value).trim() === '') return null;
  const actual = parseMeasurementNum(value);
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

function focusMeasureInput(rowId, index) {
  setTimeout(() => {
    const el = document.querySelector(`.measure-cell-${rowId}-${index} input`);
    el?.focus();
    el?.select?.();
  }, 10);
}

function readMeasureInputs(stageId) {
  if (!stageId) return [];
  const inputs = [];
  for (let i = 0; i < 50; i++) {
    const el = document.querySelector(`.measure-cell-stage-${stageId}-${i} input`);
    if (el) {
      const val = el.value ?? '';
      inputs.push(val);
    } else {
      // Stop at first missing column
      break;
    }
  }
  return inputs;
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
  onPlanPatch,
  onQuantityChange,
  quantityLocked = false,
  /** Hide plan editing actions (e.g. after plan is confirmed) */
  planEditLocked = false,
  quantityOptions = [],
  quantityNo = 1,
}) => {
  const [qtyInput, setQtyInput] = React.useState('');

  useEffect(() => {
    setQtyInput(quantityNo === 'consolidated' ? 'ALL' : String(quantityNo));
  }, [quantityNo]);

  const handleQtySubmit = () => {
    const val = (qtyInput || '').trim().toUpperCase();
    if (!val) {
      setQtyInput(quantityNo === 'consolidated' ? 'ALL' : String(quantityNo));
      return;
    }
    if (val === 'ALL' || val === 'CONSOLIDATED') {
      onQuantityChange?.('consolidated');
      return;
    }
    const n = parseInt(val, 10);
    const max = quantityOptions.filter(o => typeof o.value === 'number').length;
    if (Number.isNaN(n) || n < 1 || n > max) {
      message.warning(`Quantity ${val} does not exist (Max: ${max})`);
      setQtyInput(quantityNo === 'consolidated' ? 'ALL' : String(quantityNo));
      return;
    }
    onQuantityChange?.(n);
  };
  const rangeAnchorIndexRef = useRef(null);
  const tableScrollRef = useRef(null);
  const suppressRowClickRef = useRef(false);
  const dragStateRef = useRef({ down: false, moved: false, startX: 0, startY: 0, scrollL: 0, scrollT: 0 });
  const [editingInstrumentRowId, setEditingInstrumentRowId] = React.useState(null);
  const [localColCount, setLocalColCount] = React.useState(null);

  useEffect(() => {
    rangeAnchorIndexRef.current = null;
  }, [dataSource]);

  const measurementCount = useMemo(() => {
    let dataMax = 0;
    dataSource.forEach(r => {
      if (r.measurements && r.measurements.length > dataMax) dataMax = r.measurements.length;
    });
    const base = Math.max(3, dataMax);
    if (localColCount === null || localColCount < base) return base;
    return localColCount;
  }, [dataSource, localColCount]);

  useEffect(() => {
    // Reset local count when data changes significantly or quantity changes
    setLocalColCount(null);
  }, [quantityNo]);

  const handleAddColumn = () => {
    setLocalColCount(measurementCount + 1);
  };

  const handleRemoveColumn = () => {
    if (measurementCount > 1) {
      const newCount = measurementCount - 1;
      setLocalColCount(newCount);
      
      // If we remove a column that might have data, we should ideally notify the parent to truncate.
      // For now, we'll let the user know it's a UI removal, but we'll also trigger a patch 
      // if they want to "save" the removal.
      // But the requirement says "the last column added should be removed and all these changes should be saved".
      // This implies we should actually update the backend.
      
      dataSource.forEach(record => {
        if (record.stageInspectionId && record.measurements && record.measurements.length > newCount) {
          const newList = record.measurements.slice(0, newCount);
          const meanStr = computeMeanFromStrings(newList);
          onMeasurePatch?.(record.stageInspectionId, {
            measurements: newList,
            measured_mean: meanStr
          });
        }
      });
    }
  };

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
      const mList = readMeasureInputs(record.id);
      const meanStr = computeMeanFromStrings(mList);
      if (meanStr == null) return;
      await onMeasurePatch(record.stageInspectionId, { measured_mean: meanStr });
    },
    [onMeasurePatch],
  );

  const handleMeasureKeyDown = useCallback(
    (e, record, rowIndex, index, maxIndex) => {
      const stageId = record.stageInspectionId;
      if (!stageId) return;

      const saveCurrentRow = async () => {
        const mList = readMeasureInputs(stageId);
        const meanStr = computeMeanFromStrings(mList);
        console.log(`[InspectorBOCTable] Calculated mean for stage row ${stageId}:`, meanStr, 'from inputs:', mList);
        const numVals = mList.map((v) => parseMeasurementNum(v));
        const allFilled = numVals.length > 0 && numVals.every((v) => v != null);
        const payload = {
          measurements: mList,
          measured_mean: meanStr || '',
          is_done: allFilled,
        };
        await onMeasurePatch?.(stageId, payload);
      };

      if (e.key === 'ArrowRight') {
        e.preventDefault();
        void saveCurrentRow();
        if (index < maxIndex) focusMeasureInput(rowId, index + 1);
      } else if (e.key === 'ArrowLeft') {
        e.preventDefault();
        void saveCurrentRow();
        if (index > 0) focusMeasureInput(rowId, index - 1);
      } else if (e.key === 'Enter') {
        e.preventDefault();
        void saveCurrentRow();
        if (index < maxIndex) {
          focusMeasureInput(rowId, index + 1);
          return;
        }
        // If at end of row, move to next row first column
        const next = dataSource[rowIndex + 1];
        if (next?.stageInspectionId) {
          requestAnimationFrame(() => focusMeasureInput(next.id, 0));
        }
      }
    },
    [dataSource, onMeasurePatch],
  );

  const renderMInput = useCallback(
    (index, width, maxIndex) => (v, record, rowIndexArg) => {
      const showInput = measureMode;
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
      const locked = Boolean(record.measureLocked);
      return (
        <div
          style={cellCenter}
          className={`measure-cell-stage-${record.stageInspectionId}-${index}`}
        >
          <Input
            key={`m-${record.id}-${record.stageInspectionId}-${index}`}
            size="small"
            defaultValue={v ?? ''}
            disabled={locked}
            onBlur={(e) => {
              const stageId = record.stageInspectionId;
              if (!stageId || locked) return;

              const mList = readMeasureInputs(stageId);
              const meanStr = computeMeanFromStrings(mList);
              console.log(`[InspectorBOCTable] onBlur mean for stage row ${stageId}:`, meanStr, 'from inputs:', mList);
              const numVals = mList.map((v) => parseMeasurementNum(v));
              const allFilled = numVals.length > 0 && numVals.every((v) => v != null);
              
              const payload = {
                measurements: mList,
                measured_mean: meanStr || '',
                is_done: allFilled
              };
              onMeasurePatch?.(stageId, payload);
            }}
            onKeyDown={(e) => handleMeasureKeyDown(e, record, rowIndex, index, maxIndex)}
            style={{ width, fontSize: 11, paddingInline: 6 }}
          />
        </div>
      );
    },
    [measureMode, dataSource, onMeasurePatch, maybePatchMean, handleMeasureKeyDown],
  );

  const renderActualDisplay = useCallback(
    (v, record) => {
      const display = v != null && String(v).trim() !== '' ? String(v) : '—';
      const status = checkPassFail(v, record);
      
      const content = (
        <div 
          style={{ ...cellCenter }}
        >
          {status === 'pass' ? (
            <Tag 
              color="success" 
              bordered={false}
              style={{ 
                margin: 0, 
                borderRadius: '4px', 
                fontWeight: 800, 
                fontSize: '10px',
                minWidth: '42px',
                backgroundColor: '#f0fdf4',
                color: '#15803d',
                border: '1px solid #bcf0da'
              }}
            >
              {display}
            </Tag>
          ) : status === 'fail' ? (
            <Tag 
              color="error" 
              bordered={false}
              style={{ 
                margin: 0, 
                borderRadius: '4px', 
                fontWeight: 800, 
                fontSize: '10px',
                minWidth: '42px',
                backgroundColor: '#fef2f2',
                color: '#dc2626',
                border: '1px solid #fecaca'
              }}
            >
              {display}
            </Tag>
          ) : (
            <Text style={{ fontSize: '11px', color: '#8c8c8c' }}>
              {display}
            </Text>
          )}
        </div>
      );

      return content;
    },
    [],
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
    ];

    const actualCol = {
      title: 'ACTUAL',
      dataIndex: 'actualValue',
      key: 'actualValue',
      width: 64,
      align: 'center',
      render: renderActualDisplay,
    };

    const meanValueCol = {
      title: 'MEAN VALUE',
      dataIndex: 'meanValue',
      key: 'meanValue',
      width: 90,
      align: 'center',
      render: renderActualDisplay,
    };

    const mCols = [];
    for (let i = 0; i < measurementCount; i++) {
      mCols.push({
        title: `M${i + 1}`,
        dataIndex: ['measurements', i],
        key: `m${i}`,
        width: 58,
        align: 'center',
        render: (v, record, idx) => renderMInput(i, 52, measurementCount - 1)(v, record, idx),
      });
    }

    const instrumentCol = {
      title: 'INSTRUMENT',
      dataIndex: 'instrument',
      key: 'instrument',
      width: 120,
      align: 'center',
      render: (instr, record) => {
        const isEditing = measureMode && editingInstrumentRowId === record.id;
        const displayVal = instr && instr !== 'default' ? instr : '';
        const placeholder = 'default';

        if (isEditing) {
          return (
            <Input
              size="small"
              autoFocus
              defaultValue={displayVal}
              placeholder={placeholder}
              style={{ fontSize: 11, width: '100%' }}
              onBlur={(e) => {
                const val = e.target.value.trim() || 'default';
                if (record.stageInspectionId) {
                  onMeasurePatch?.(record.stageInspectionId, { measured_instrument: val });
                }
                setEditingInstrumentRowId(null);
              }}
              onKeyDown={(e) => {
                if (e.key === 'Enter') e.target.blur();
                if (e.key === 'Escape') setEditingInstrumentRowId(null);
              }}
            />
          );
        }

        if (measureMode) {
          return (
            <div
              title="Click to set instrument name"
              style={{ cursor: 'pointer', width: '100%', display: 'flex', alignItems: 'center', justifyContent: 'center', gap: 4, minHeight: 22 }}
              onClick={(e) => {
                e.stopPropagation();
                setEditingInstrumentRowId(record.id);
              }}
            >
              <Text style={{ fontSize: '11px', color: displayVal ? '#262626' : '#bfbfbf' }}>
                {displayVal || placeholder}
              </Text>
              <EditOutlined style={{ fontSize: 10, color: '#1890ff', flexShrink: 0 }} />
            </div>
          );
        }

        // Plan mode: read-only
        return (
          <Text style={{ fontSize: '11px', color: displayVal ? '#262626' : '#bfbfbf' }}>
            {displayVal || placeholder}
          </Text>
        );
      },
    };

    if (measureMode) {
      const result = [
        baseCols[0], // ID
        baseCols[5], // ZONE
        baseCols[1], // NOMINAL
        baseCols[2], // UTOL
        baseCols[3], // LTOL
        baseCols[4], // DIM TYPE
        actualCol,   // ACTUAL
      ];
      result.push(...mCols);
      result.push(instrumentCol);
      return result;
    }
    // Plan mode: [ID, ZONE, NOMINAL, UTOL, LTOL, DIM TYPE, INSTRUMENT]
    return [
      baseCols[0],
      baseCols[5],
      baseCols[1],
      baseCols[2],
      baseCols[3],
      baseCols[4],
      instrumentCol,
    ];
  }, [measureMode, renderMInput, renderActualDisplay, editingInstrumentRowId, setEditingInstrumentRowId, onMeasurePatch, measurementCount]);

  const countTotal = totalCount ?? dataSource.length;
  const badge = filterActive ? `${dataSource.length} / ${countTotal}` : String(dataSource.length);

  const selectedSet = useMemo(() => new Set(selectedIds), [selectedIds]);

  const handleRowClick = useCallback(
    (record, index, e) => {
      if (suppressRowClickRef.current) return;
      if (e.target?.closest?.('input, textarea, button, .ant-select, .ant-input, .anticon')) {
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
          {measureMode && (
            <Space size={4}>
              <Button 
                size="small" 
                type="dashed" 
                onClick={handleAddColumn}
                style={{ fontSize: 10, height: 22, padding: '0 8px' }}
              >
                + Add Column
              </Button>
              <Button 
                size="small" 
                type="dashed" 
                danger
                onClick={handleRemoveColumn}
                disabled={measurementCount <= 1}
                style={{ fontSize: 10, height: 22, padding: '0 8px' }}
              >
                - Remove Column
              </Button>
            </Space>
          )}
        </Space>
        <Space wrap>
          {measureMode && (
            <div style={{
              display: 'flex',
              alignItems: 'center',
              background: '#f8fafc',
              border: '1px solid #e2e8f0',
              borderRadius: '6px',
              padding: '1px 4px',
              gap: 6
            }}>
              <Button
                size="small"
                type="text"
                icon={<LeftOutlined style={{ fontSize: 10 }} />}
                disabled={quantityNo === 1 || quantityOptions.length <= 1}
                onClick={() => {
                  const idx = quantityOptions.findIndex(o => o.value === quantityNo);
                  if (idx > 0) onQuantityChange?.(quantityOptions[idx - 1].value);
                }}
                style={{ width: 22, height: 22, padding: 0 }}
              />
              <div style={{
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'center',
                minWidth: 50,
                gap: 2
              }}>
                <Input
                  size="small"
                  variant="borderless"
                  value={qtyInput}
                  onChange={(e) => setQtyInput(e.target.value)}
                  onPressEnter={handleQtySubmit}
                  onBlur={handleQtySubmit}
                  style={{
                    width: qtyInput === 'ALL' ? 32 : 24,
                    textAlign: qtyInput === 'ALL' ? 'center' : 'right',
                    fontSize: '11px',
                    fontWeight: 700,
                    color: '#334155',
                    padding: 0,
                    height: '22px',
                    fontFamily: '"JetBrains Mono", monospace',
                  }}
                />
                {quantityNo !== 'consolidated' && (
                  <Text style={{ fontSize: '11px', color: '#94a3b8', fontWeight: 600, userSelect: 'none' }}>
                    / {quantityOptions.filter(o => typeof o.value === 'number').length}
                  </Text>
                )}
              </div>
              <Button
                size="small"
                type="text"
                icon={<RightOutlined style={{ fontSize: 10 }} />}
                disabled={quantityNo === 'consolidated' || (quantityNo === quantityOptions.filter(o => typeof o.value === 'number').length && !quantityOptions.some(o => o.value === 'consolidated'))}
                onClick={() => {
                  const idx = quantityOptions.findIndex(o => o.value === quantityNo);
                  if (idx >= 0 && idx < quantityOptions.length - 1) {
                    onQuantityChange?.(quantityOptions[idx + 1].value);
                  }
                }}
                style={{ width: 22, height: 22, padding: 0 }}
              />
            </div>
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
              const pf = measureMode ? checkPassFail(record.actualValue, record) : null;
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
