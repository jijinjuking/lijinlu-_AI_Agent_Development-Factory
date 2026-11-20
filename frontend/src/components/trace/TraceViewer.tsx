// ============================================================
// TraceViewer — Trace 查看器（递归树 + 详情面板）
// ============================================================

import React, { useMemo } from 'react';
import { Spin, Empty } from 'antd';
import { useTraceStore } from '../../stores/traceStore';
import TraceNodeItem from './TraceNodeItem';
import TraceDetail from './TraceDetail';
import type { TraceNode } from '../../types/trace';

/** 递归展开节点树 */
function flattenTree(
  nodes: TraceNode[],
  parentId: string | null,
  depth: number,
): { node: TraceNode; depth: number }[] {
  const result: { node: TraceNode; depth: number }[] = [];
  for (const node of nodes) {
    if (node.parentId === parentId) {
      result.push({ node, depth });
      result.push(...flattenTree(nodes, node.id, depth + 1));
    }
  }
  return result;
}

const TraceViewer: React.FC = () => {
  const { currentTrace, traceNodes, selectedNodeId, isLoading, selectNode, getSelectedNode } =
    useTraceStore();

  const flatNodes = useMemo(
    () => flattenTree(traceNodes, null, 0),
    [traceNodes],
  );

  const selectedNode = getSelectedNode();

  if (isLoading) {
    return (
      <div style={{ textAlign: 'center', padding: 60 }}>
        <Spin size="large" description="加载 Trace 数据..." />
      </div>
    );
  }

  if (!currentTrace || flatNodes.length === 0) {
    return (
      <Empty
        description="请从左侧列表选择一条 Trace 记录"
        style={{ padding: 60 }}
      />
    );
  }

  return (
    <div style={{ display: 'flex', gap: 0, height: 'calc(100vh - 200px)' }}>
      {/* 左侧：节点树 */}
      <div
        style={{
          flex: '0 0 55%',
          overflow: 'auto',
          border: '1px solid var(--ant-color-border-secondary, #30363d)',
          borderRadius: 8,
          background: 'var(--ant-color-bg-container, #161b22)',
        }}
      >
        {flatNodes.map(({ node, depth }) => (
          <TraceNodeItem
            key={node.id}
            node={node}
            depth={depth}
            isSelected={selectedNodeId === node.id}
            onSelect={selectNode}
          />
        ))}
      </div>

      {/* 右侧：详情面板 */}
      <div
        style={{
          flex: '0 0 45%',
          overflow: 'auto',
          marginLeft: 16,
          border: '1px solid var(--ant-color-border-secondary, #30363d)',
          borderRadius: 8,
          background: 'var(--ant-color-bg-container, #161b22)',
        }}
      >
        <TraceDetail node={selectedNode} />
      </div>
    </div>
  );
};

export default TraceViewer;
