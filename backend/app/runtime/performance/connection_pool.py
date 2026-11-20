"""W35-36 Performance Optimization — 连接池优化器

ConnectionPoolOptimizer 提供数据库连接池的配置优化和运行时监控：
- 连接池参数推荐（基于并发目标）
- 连接池统计信息收集
- 健康检查（连接泄漏检测、等待时间监控）

使用方式：
    optimizer = ConnectionPoolOptimizer()
    config = optimizer.recommend_config(concurrency_target=100)
    stats = optimizer.get_pool_stats(engine)
"""

import asyncio
import time
from typing import Optional, Any

from .models import ConnectionPoolConfig, PoolStats


class ConnectionPoolOptimizer:
    """连接池优化器

    根据并发目标推荐连接池配置，并监控连接池运行状态。
    """

    def __init__(self):
        self._config: Optional[ConnectionPoolConfig] = None
        self._checkout_history: list[float] = []  # 每次 checkout 的时间戳
        self._wait_history: list[float] = []       # 等待连接的时间
        self._leak_threshold_sec: float = 60.0     # 连接泄漏判定阈值

    # ------------------------------------------------------------------
    # 配置推荐
    # ------------------------------------------------------------------

    def recommend_config(self, concurrency_target: int = 100,
                         db_type: str = "postgresql") -> ConnectionPoolConfig:
        """根据并发目标推荐连接池配置

        Args:
            concurrency_target: 目标并发数
            db_type: 数据库类型 (sqlite/postgresql/mysql)

        Returns:
            ConnectionPoolConfig: 推荐配置
        """
        if db_type == "sqlite":
            # SQLite 不支持高并发连接池
            pool_size = min(5, concurrency_target)
            max_overflow = 0
            pool_timeout = 5.0
        elif db_type == "postgresql":
            # PostgreSQL 经验公式：pool_size = 2 * sqrt(concurrency)
            pool_size = max(5, int(2 * (concurrency_target ** 0.5)))
            max_overflow = max(2, pool_size // 2)
            pool_timeout = 30.0
        elif db_type == "mysql":
            pool_size = max(5, int(1.5 * (concurrency_target ** 0.5)))
            max_overflow = max(2, pool_size // 3)
            pool_timeout = 30.0
        else:
            pool_size = 20
            max_overflow = 10
            pool_timeout = 30.0

        self._config = ConnectionPoolConfig(
            pool_size=pool_size,
            max_overflow=max_overflow,
            pool_timeout=pool_timeout,
            pool_recycle=3600.0,
            pool_pre_ping=True,
        )
        return self._config

    def apply_to_engine_kwargs(self, concurrency_target: int = 100,
                               db_type: str = "postgresql") -> dict:
        """生成 SQLAlchemy create_async_engine 的参数

        Returns:
            dict: 可直接传入 create_async_engine() 的参数
        """
        cfg = self.recommend_config(concurrency_target, db_type)
        return {
            "pool_size": cfg.pool_size,
            "max_overflow": cfg.max_overflow,
            "pool_timeout": cfg.pool_timeout,
            "pool_recycle": int(cfg.pool_recycle),
            "pool_pre_ping": cfg.pool_pre_ping,
            "echo_pool": cfg.echo_pool,
        }

    # ------------------------------------------------------------------
    # 运行时统计
    # ------------------------------------------------------------------

    def get_pool_stats(self, engine: Any) -> PoolStats:
        """获取连接池统计（从 SQLAlchemy engine）

        Args:
            engine: SQLAlchemy AsyncEngine 实例

        Returns:
            PoolStats: 连接池统计
        """
        pool = engine.pool
        size = getattr(pool, 'size', lambda: 0)() if callable(getattr(pool, 'size', None)) else getattr(pool, 'size', 0)
        checked_in = getattr(pool, 'checkedin', lambda: 0)() if callable(getattr(pool, 'checkedin', None)) else getattr(pool, 'checkedin', 0)
        checked_out = size - checked_in
        overflow = getattr(pool, 'overflow', lambda: 0)() if callable(getattr(pool, 'overflow', None)) else getattr(pool, 'overflow', 0)

        max_conn = size + overflow
        total = checked_in + checked_out
        utilization = checked_out / max(1, max_conn)

        return PoolStats(
            pool_size=size,
            checked_in=checked_in,
            checked_out=checked_out,
            overflow=overflow,
            total_connections=total,
            max_connections=max_conn,
            utilization=round(utilization, 4),
            total_checked_out=self._record_checkout(),
            total_wait_count=len(self._wait_history),
        )

    def record_checkout(self, wait_time: float = 0.0) -> None:
        """记录一次连接 checkout"""
        self._checkout_history.append(time.monotonic())
        if wait_time > 0:
            self._wait_history.append(wait_time)
        # 只保留最近 1000 条
        if len(self._checkout_history) > 1000:
            self._checkout_history = self._checkout_history[-1000:]
        if len(self._wait_history) > 1000:
            self._wait_history = self._wait_history[-1000:]

    def _record_checkout(self) -> int:
        """获取历史总 checkout 次数"""
        return len(self._checkout_history)

    # ------------------------------------------------------------------
    # 健康检查
    # ------------------------------------------------------------------

    def check_connection_leaks(self, engine: Any,
                                threshold_sec: Optional[float] = None) -> list[str]:
        """检查连接泄漏

        Args:
            engine: SQLAlchemy AsyncEngine
            threshold_sec: 连接持有超过此时间视为泄漏

        Returns:
            list[str]: 警告消息列表
        """
        warnings = []
        threshold = threshold_sec or self._leak_threshold_sec

        pool = engine.pool
        checked_out = getattr(pool, 'checkedout', lambda: 0)() if callable(getattr(pool, 'checkedout', None)) else getattr(pool, 'checkedout', 0)

        if checked_out > 0:
            now = time.monotonic()
            recent_checkouts = [t for t in self._checkout_history if now - t < threshold]
            long_held = len(self._checkout_history) - len(recent_checkouts)

            if checked_out > 10:
                warnings.append(f"High connection checkout: {checked_out} connections in use")

            if long_held > 0:
                warnings.append(f"Potential connection leak: {long_held} connections held > {threshold}s")

        # 检查等待时间
        if self._wait_history:
            avg_wait = sum(self._wait_history) / len(self._wait_history)
            if avg_wait > 5.0:  # 超过 5 秒平均等待
                warnings.append(f"High connection wait time: avg {avg_wait:.1f}s")

        return warnings

    def get_health_report(self, engine: Any) -> dict:
        """获取连接池健康报告"""
        stats = self.get_pool_stats(engine)
        leaks = self.check_connection_leaks(engine)

        return {
            "pool_stats": {
                "size": stats.pool_size,
                "checked_in": stats.checked_in,
                "checked_out": stats.checked_out,
                "overflow": stats.overflow,
                "utilization": stats.utilization,
            },
            "warnings": leaks,
            "recommendation": self._generate_recommendation(stats),
        }

    def _generate_recommendation(self, stats: PoolStats) -> Optional[str]:
        """生成优化建议"""
        if stats.utilization > 0.8:
            return "Connection pool utilization high (>80%). Consider increasing pool_size or max_overflow."
        if stats.overflow > 0 and stats.overflow > stats.pool_size * 0.5:
            return "High overflow connections. Consider increasing base pool_size."
        if stats.utilization < 0.3 and stats.pool_size > 10:
            return "Connection pool under-utilized. Consider reducing pool_size."
        return None

    def update_config(self, config: ConnectionPoolConfig) -> None:
        """更新配置"""
        self._config = config

    def get_config(self) -> Optional[ConnectionPoolConfig]:
        """获取当前配置"""
        return self._config
