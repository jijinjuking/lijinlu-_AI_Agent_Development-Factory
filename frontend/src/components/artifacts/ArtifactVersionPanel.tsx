// ============================================================
// components/artifacts/ArtifactVersionPanel.tsx — W23-24
//
// Artifact 版本管理面板：
//   - 版本历史列表（时间线风格）
//   - 相邻版本 Diff 对比（unified diff 渲染）
//   - 一键 Rollback（回滚到指定版本）
// ============================================================

import React, { useState, useCallback, useEffect } from 'react';
import {
  Timeline,
  Tag,
  Button,
  Typography,
  Spin,
  Alert,
  Tooltip,
  Popconfirm,
  Modal,
  Space,
  Divider,
  message,
} from 'antd';
import {
  HistoryOutlined,
  RollbackOutlined,
  DiffOutlined,
  CheckCircleOutlined,
  CopyOutlined,
} from '@ant-design/icons';
import type { ArtifactMeta } from '../../api/artifacts';
import {
  getArtifactVersions,
  diffArtifacts,
  rollbackArtifact,
} from '../../api/artifacts';

const { Text, Title } = Typography;

// ── Diff 渲染 ──────────────────────────────────────────────

function DiffViewer({ diffText }: { diffText: string }) {
  if (!diffText) {
    return <Text type="secondary">无差异（两版本内容相同）</Text>;
  }

  const lines = diffText.split('\n');

  return (
    <div
      style={{
        fontFamily: 'monospace',
        fontSize: 12,
        lineHeight: 1.5,
        background: '#0d1117',
        borderRadius: 6,
        padding: '10px 12px',
        overflow: 'auto',
        maxHeight: 500,
      }}
    >
      {lines.map((line, index) => {
        let color = '#c9d1d9';
        let background = 'transparent';
        if (line.startsWith('+++') || line.startsWith('---')) {
          color = '#8b949e';
        } else if (line.startsWith('+')) {
          color = '#7ee787';
          background = 'rgba(126, 231, 135, 0.1)';
        } else if (line.startsWith('-')) {
          color = '#ff7b72';
          background = 'rgba(255, 123, 114, 0.1)';
        } else if (line.startsWith('@@')) {
          color = '#79c0ff';
          background = 'rgba(121, 192, 255, 0.08)';
        }
        return (
          <div
            key={index}
            style={{ color, background, paddingLeft: 4, whiteSpace: 'pre-wrap', wordBreak: 'break-all' }}
          >
            {line || ' '}
          </div>
        );
      })}
    </div>
  );
}

// ── 主组件 ────────────────────────────────────────────────

interface ArtifactVersionPanelProps {
  artifactId: string;
  onRollbackComplete?: (newArtifactId: string) => void;
}

const ArtifactVersionPanel: React.FC<ArtifactVersionPanelProps> = ({
  artifactId,
  onRollbackComplete,
}) => {
  const [versions, setVersions] = useState<ArtifactMeta[]>([]);
  const [isLoading, setIsLoading] = useState(false);
  const [loadError, setLoadError] = useState<string | null>(null);

  // Diff 弹窗
  const [diffModalOpen, setDiffModalOpen] = useState(false);
  const [diffText, setDiffText] = useState('');
  const [isDiffLoading, setIsDiffLoading] = useState(false);
  const [diffLabel, setDiffLabel] = useState('');

  // Rollback 状态
  const [rollingBackId, setRollingBackId] = useState<string | null>(null);

  const [messageApi, contextHolder] = message.useMessage();

  // 加载版本链
  const loadVersions = useCallback(async () => {
    setIsLoading(true);
    setLoadError(null);
    try {
      const resp = await getArtifactVersions(artifactId);
      setVersions(resp.versions);
    } catch (err: unknown) {
      setLoadError(err instanceof Error ? err.message : '加载版本历史失败');
    } finally {
      setIsLoading(false);
    }
  }, [artifactId]);

  useEffect(() => {
    loadVersions();
  }, [loadVersions]);

  // 打开 Diff 视图（当前版本 vs 指定版本）
  const handleOpenDiff = useCallback(async (baseId: string, targetId: string, label: string) => {
    setIsDiffLoading(true);
    setDiffModalOpen(true);
    setDiffLabel(label);
    setDiffText('');
    try {
      const resp = await diffArtifacts(targetId, baseId);
      setDiffText(resp.diff);
    } catch (err: unknown) {
      setDiffText(`# 加载 Diff 失败: ${err instanceof Error ? err.message : '未知错误'}`);
    } finally {
      setIsDiffLoading(false);
    }
  }, []);

  // 回滚到指定版本
  const handleRollback = useCallback(async (targetVersionId: string, targetVersion: number) => {
    setRollingBackId(targetVersionId);
    try {
      const resp = await rollbackArtifact(artifactId, targetVersionId);
      messageApi.success(`已回滚到 v${targetVersion}，新版本 ID: ${resp.artifact_id.slice(0, 8)}...`);
      await loadVersions();
      onRollbackComplete?.(resp.artifact_id);
    } catch (err: unknown) {
      messageApi.error(err instanceof Error ? err.message : '回滚失败');
    } finally {
      setRollingBackId(null);
    }
  }, [artifactId, loadVersions, onRollbackComplete, messageApi]);

  if (isLoading) {
    return <Spin tip="加载版本历史..." style={{ padding: 24 }} />;
  }

  if (loadError) {
    return <Alert type="error" message={loadError} />;
  }

  const latestVersion = versions[versions.length - 1];

  return (
    <div>
      {contextHolder}

      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 12 }}>
        <Text strong>版本历史（{versions.length} 个版本）</Text>
        <Button size="small" icon={<HistoryOutlined />} onClick={loadVersions}>
          刷新
        </Button>
      </div>

      {versions.length === 0 && (
        <Text type="secondary">暂无版本历史</Text>
      )}

      <Timeline
        items={versions.map((ver, index) => {
          const isLatest = ver.id === latestVersion?.id;
          const prevVer = versions[index - 1];
          const isRollingBack = rollingBackId === ver.id;

          return {
            color: isLatest ? 'green' : 'blue',
            dot: isLatest ? <CheckCircleOutlined style={{ color: '#52c41a' }} /> : undefined,
            children: (
              <div
                style={{
                  background: isLatest ? 'rgba(82, 196, 26, 0.05)' : 'transparent',
                  border: isLatest ? '1px solid rgba(82, 196, 26, 0.2)' : 'none',
                  borderRadius: 6,
                  padding: isLatest ? '8px 10px' : '4px 0',
                }}
              >
                <div style={{ display: 'flex', alignItems: 'center', gap: 6, flexWrap: 'wrap' }}>
                  <Tag color={isLatest ? 'green' : 'blue'}>v{ver.version}</Tag>
                  {isLatest && <Tag color="success">当前最新</Tag>}
                  {(ver.metadata as any)?.rollback_from && (
                    <Tag color="orange">回滚版本</Tag>
                  )}
                  <Text type="secondary" style={{ fontSize: 11 }}>
                    {ver.created_at ? new Date(ver.created_at).toLocaleString('zh-CN') : '—'}
                  </Text>
                  {ver.created_by_agent && (
                    <Text type="secondary" style={{ fontSize: 11, fontStyle: 'italic' }}>
                      by {ver.created_by_agent}
                    </Text>
                  )}
                </div>

                <Text
                  copyable
                  style={{ fontSize: 10, color: '#8c8c8c', fontFamily: 'monospace' }}
                >
                  {ver.id}
                </Text>

                {/* 操作按钮 */}
                <div style={{ marginTop: 6 }}>
                  <Space size={6}>
                    {prevVer && (
                      <Tooltip title={`对比 v${prevVer.version} → v${ver.version}`}>
                        <Button
                          size="small"
                          icon={<DiffOutlined />}
                          onClick={() => handleOpenDiff(
                            prevVer.id,
                            ver.id,
                            `v${prevVer.version} → v${ver.version}`,
                          )}
                        >
                          与上版对比
                        </Button>
                      </Tooltip>
                    )}

                    {!isLatest && (
                      <Tooltip title={`将内容恢复到 v${ver.version} 并创建新版本`}>
                        <Popconfirm
                          title={`确认回滚到 v${ver.version}？`}
                          description="将以该版本内容创建新版本，当前版本不会被删除。"
                          onConfirm={() => handleRollback(ver.id, ver.version)}
                          okText="确认回滚"
                          cancelText="取消"
                        >
                          <Button
                            size="small"
                            icon={<RollbackOutlined />}
                            loading={isRollingBack}
                            type="primary"
                            ghost
                            danger
                          >
                            回滚到此版本
                          </Button>
                        </Popconfirm>
                      </Tooltip>
                    )}
                  </Space>
                </div>
              </div>
            ),
          };
        })}
      />

      {/* Diff 弹窗 */}
      <Modal
        title={<><DiffOutlined /> 版本对比：{diffLabel}</>}
        open={diffModalOpen}
        onCancel={() => setDiffModalOpen(false)}
        footer={null}
        width={900}
        destroyOnHidden
      >
        {isDiffLoading ? (
          <Spin tip="生成 Diff..." />
        ) : (
          <DiffViewer diffText={diffText} />
        )}
      </Modal>
    </div>
  );
};

export default ArtifactVersionPanel;
