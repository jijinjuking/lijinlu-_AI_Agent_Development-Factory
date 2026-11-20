// ============================================================
// components/event_replay/ReplayController.tsx
//
// 回放控制器：播放 / 暂停 / 停止 / 步进 / 步退 / 速度切换
// 以及进度条（Slider）显示当前回放位置
// ============================================================

import React from 'react';
import { Button, Slider, Space, Select, Typography, Tooltip } from 'antd';
import {
  PlayCircleOutlined,
  PauseOutlined,
  StepBackwardOutlined,
  StepForwardOutlined,
  StopOutlined,
} from '@ant-design/icons';
import type { ReplayStatus } from '../../types/event';

const { Text } = Typography;

const SPEED_OPTIONS = [
  { label: '0.5×', value: 0.5 },
  { label: '1×',   value: 1   },
  { label: '2×',   value: 2   },
  { label: '4×',   value: 4   },
];

interface ReplayControllerProps {
  status: ReplayStatus;
  currentIndex: number;
  totalEvents: number;
  speed: number;
  onPlay: () => void;
  onPause: () => void;
  onStop: () => void;
  onStepForward: () => void;
  onStepBackward: () => void;
  onSeek: (index: number) => void;
  onSpeedChange: (speed: number) => void;
}

const ReplayController: React.FC<ReplayControllerProps> = ({
  status,
  currentIndex,
  totalEvents,
  speed,
  onPlay,
  onPause,
  onStop,
  onStepForward,
  onStepBackward,
  onSeek,
  onSpeedChange,
}) => {
  const isPlaying = status === 'playing';
  const isIdle = status === 'idle';
  const isFinished = status === 'finished';
  const canPlay = totalEvents > 0 && (status === 'idle' || status === 'paused' || isFinished);
  const canPause = isPlaying;
  const displayIndex = totalEvents > 0 ? currentIndex + 1 : 0;

  return (
    <div style={{ padding: '12px 16px', borderTop: '1px solid #f0f0f0', background: '#fafafa' }}>
      {/* 进度条 */}
      <div style={{ marginBottom: 10 }}>
        <Slider
          min={0}
          max={Math.max(0, totalEvents - 1)}
          value={currentIndex >= 0 ? currentIndex : 0}
          onChange={onSeek}
          disabled={totalEvents === 0}
          tooltip={{
            formatter: (val) => val !== undefined ? `第 ${val + 1} 步 / 共 ${totalEvents} 步` : '',
          }}
          style={{ margin: '0 8px' }}
        />
      </div>

      {/* 控制按钮区 */}
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
        <Space size="small">
          {/* 步退 */}
          <Tooltip title="步退">
            <Button
              icon={<StepBackwardOutlined />}
              size="small"
              onClick={onStepBackward}
              disabled={totalEvents === 0 || currentIndex <= 0}
            />
          </Tooltip>

          {/* 播放 / 暂停 */}
          {isPlaying ? (
            <Tooltip title="暂停">
              <Button
                type="primary"
                icon={<PauseOutlined />}
                size="small"
                onClick={onPause}
              />
            </Tooltip>
          ) : (
            <Tooltip title={isFinished ? '重新播放' : '播放'}>
              <Button
                type="primary"
                icon={<PlayCircleOutlined />}
                size="small"
                onClick={onPlay}
                disabled={!canPlay}
              />
            </Tooltip>
          )}

          {/* 停止 */}
          <Tooltip title="停止并重置">
            <Button
              icon={<StopOutlined />}
              size="small"
              onClick={onStop}
              disabled={isIdle || totalEvents === 0}
            />
          </Tooltip>

          {/* 步进 */}
          <Tooltip title="步进">
            <Button
              icon={<StepForwardOutlined />}
              size="small"
              onClick={onStepForward}
              disabled={totalEvents === 0 || currentIndex >= totalEvents - 1}
            />
          </Tooltip>
        </Space>

        {/* 右侧：进度 + 速度 */}
        <Space size="middle">
          <Text type="secondary" style={{ fontSize: 12 }}>
            {displayIndex} / {totalEvents}
          </Text>

          <Select
            size="small"
            value={speed}
            onChange={onSpeedChange}
            options={SPEED_OPTIONS}
            style={{ width: 70 }}
            title="播放速度"
          />
        </Space>
      </div>
    </div>
  );
};

export default ReplayController;
