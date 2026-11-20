"""W35-36 Performance Optimization — REST API

性能优化模块的 API 端点：
- POST /benchmark/run — 执行基准测试
- GET /benchmark/results — 历史结果列表
- GET /benchmark/results/{id} — 单次结果详情
- GET /metrics — 当前性能指标
- GET /metrics/history — 历史快照
- GET /concurrency/stats — 并发控制统计
- PUT /concurrency/config — 更新并发配置
- GET /rate-limits — 限流规则列表
- POST /rate-limits — 添加限流规则
- PUT /rate-limits/{id} — 更新限流规则
- DELETE /rate-limits/{id} — 删除限流规则
- GET /rate-limits/stats — 限流桶统计
- GET /llm-limits — LLM 限流状态
- POST /llm-limits/reset — 重置 LLM 限流
- GET /backpressure — 背压统计
- POST /backpressure/clear — 清空背压队列
- GET /pool/health — 连接池健康报告
- POST /metrics/reset — 重置指标

挂载到 /api/v1/performance
"""

from fastapi import APIRouter, HTTPException, Query
from typing import Optional

from app.runtime.performance import (
    BenchmarkRunner, MetricsCollector, ConcurrencyController,
    RateLimiter, LLMRateLimiter, BackpressureManager, ConnectionPoolOptimizer,
    BenchmarkConfig, ConcurrencyConfig, RateLimitRule,
    LLMRateLimitConfig, BackpressureConfig, ConnectionPoolConfig,
    BenchmarkResult, PerformanceMetrics, ConcurrencyStats,
    RateLimitResult, BackpressureStats, PoolStats, LLMRateLimitState,
    RateLimitAlgorithm, LimitScope, BackpressureStrategy, ConcurrencyMode,
    PRESET_RULES,
)

router = APIRouter(prefix="/performance", tags=["Performance"])

# 全局实例（模块级单例）
benchmark_runner = BenchmarkRunner()
metrics_collector = MetricsCollector()
rate_limiter = RateLimiter()
llm_rate_limiter = LLMRateLimiter()
backpressure_manager = BackpressureManager()
pool_optimizer = ConnectionPoolOptimizer()
concurrency_controller: Optional[ConcurrencyController] = None

# 初始化默认限流规则
for rule in PRESET_RULES.values():
    rate_limiter.add_rule(rule)

# 初始化背压控制器
backpressure_manager.register(BackpressureConfig(
    target="sse", max_queue_size=1000,
    strategy=BackpressureStrategy.DROP_OLDEST,
))
backpressure_manager.register(BackpressureConfig(
    target="eventbus", max_queue_size=5000,
    strategy=BackpressureStrategy.DROP_OLDEST,
))
backpressure_manager.register(BackpressureConfig(
    target="task_queue", max_queue_size=2000,
    strategy=BackpressureStrategy.DROP_NEWEST,
))


# ============================================================================
# Benchmark
# ============================================================================

@router.post("/benchmark/run", response_model=BenchmarkResult)
async def run_benchmark(config: BenchmarkConfig):
    """执行基准测试（异步后台）"""
    # 创建一个简单的 task_factory 用于测试
    import asyncio

    async def sample_task():
        await asyncio.sleep(0.01)
        return {"status": "ok"}

    result = await benchmark_runner.run(config, sample_task)
    return result


@router.get("/benchmark/results")
async def list_benchmarks():
    """列出历史基准测试结果（示例）"""
    return {"benchmarks": []}


@router.get("/benchmark/results/{benchmark_id}")
async def get_benchmark_result(benchmark_id: str):
    """获取单次基准测试结果"""
    raise HTTPException(404, "Not found")


# ============================================================================
# Metrics
# ============================================================================

@router.get("/metrics", response_model=PerformanceMetrics)
async def get_metrics():
    """获取当前性能指标"""
    return metrics_collector.get_snapshot()


@router.get("/metrics/history")
async def get_metrics_history(limit: int = Query(20, ge=1, le=200)):
    """获取历史指标快照"""
    snapshots = metrics_collector.get_snapshots(limit)
    return {"snapshots": snapshots, "count": len(snapshots)}


@router.post("/metrics/reset")
async def reset_metrics():
    """重置性能指标"""
    metrics_collector.reset()
    return {"status": "reset"}


# ============================================================================
# Concurrency Control
# ============================================================================

@router.get("/concurrency/stats", response_model=ConcurrencyStats)
async def get_concurrency_stats():
    """获取并发控制统计"""
    if concurrency_controller:
        return concurrency_controller.get_stats()
    return ConcurrencyStats(max_allowed=0, mode="uninitialized")


@router.put("/concurrency/config")
async def update_concurrency_config(config: ConcurrencyConfig):
    """更新并发控制配置"""
    global concurrency_controller
    if concurrency_controller:
        concurrency_controller.update_config(config)
    else:
        concurrency_controller = ConcurrencyController(config)
        await concurrency_controller.initialize()
    return {"status": "updated", "max_concurrent": config.max_concurrent}


# ============================================================================
# Rate Limits
# ============================================================================

@router.get("/rate-limits")
async def list_rate_limits():
    """列出所有限流规则"""
    rules = rate_limiter.list_rules()
    return {"rules": rules, "count": len(rules)}


@router.post("/rate-limits")
async def add_rate_limit(rule: RateLimitRule):
    """添加限流规则"""
    rate_limiter.add_rule(rule)
    return {"status": "added", "rule_id": rule.rule_id}


@router.put("/rate-limits/{rule_id}")
async def update_rate_limit(rule_id: str, updates: dict):
    """更新限流规则"""
    ok = rate_limiter.update_rule(rule_id, **updates)
    if not ok:
        raise HTTPException(404, f"Rule {rule_id} not found")
    return {"status": "updated", "rule_id": rule_id}


@router.delete("/rate-limits/{rule_id}")
async def delete_rate_limit(rule_id: str):
    """删除限流规则"""
    ok = rate_limiter.remove_rule(rule_id)
    if not ok:
        raise HTTPException(404, f"Rule {rule_id} not found")
    return {"status": "deleted", "rule_id": rule_id}


@router.get("/rate-limits/stats")
async def get_rate_limit_stats(rule_id: str = Query(""),
                                scope_value: str = Query("")):
    """获取限流桶/窗口统计"""
    if rule_id:
        bucket = rate_limiter.get_bucket_stats(rule_id, scope_value)
        window = rate_limiter.get_window_stats(rule_id, scope_value)
        return {"rule_id": rule_id, "bucket": bucket, "window": window}
    return {"message": "specify rule_id"}


# ============================================================================
# LLM Rate Limits
# ============================================================================

@router.get("/llm-limits")
async def get_llm_limits():
    """获取 LLM 限流状态"""
    states = llm_rate_limiter.get_all_states()
    return {"states": list(states.values()), "count": len(states)}


@router.post("/llm-limits/configure")
async def configure_llm_limit(config: LLMRateLimitConfig):
    """配置 LLM 限流"""
    llm_rate_limiter.configure(config)
    return {"status": "configured", "provider": config.provider, "model": config.model}


@router.post("/llm-limits/reset")
async def reset_llm_limits(provider: str = "", model: str = ""):
    """重置 LLM 限流状态"""
    llm_rate_limiter.reset(provider, model)
    return {"status": "reset"}


# ============================================================================
# Backpressure
# ============================================================================

@router.get("/backpressure")
async def get_backpressure_stats():
    """获取背压统计"""
    stats = backpressure_manager.get_all_stats()
    return {"targets": stats, "count": len(stats)}


@router.post("/backpressure/clear")
async def clear_backpressure(target: str = Query("")):
    """清空背压队列"""
    if target:
        ctrl = backpressure_manager.get(target)
        if ctrl:
            count = ctrl.clear_queue()
            return {"status": "cleared", "target": target, "count": count}
        raise HTTPException(404, f"Target {target} not found")
    return {"message": "specify target"}


# ============================================================================
# Connection Pool
# ============================================================================

@router.get("/pool/health")
async def get_pool_health():
    """获取连接池健康报告（无 engine 时返回推荐配置）"""
    cfg = pool_optimizer.recommend_config(concurrency_target=100)
    return {
        "recommended_config": {
            "pool_size": cfg.pool_size,
            "max_overflow": cfg.max_overflow,
            "pool_timeout": cfg.pool_timeout,
            "pool_pre_ping": cfg.pool_pre_ping,
        },
        "note": "Connect to engine for real-time stats"
    }


@router.post("/pool/config")
async def update_pool_config(config: ConnectionPoolConfig):
    """更新连接池配置"""
    pool_optimizer.update_config(config)
    return {"status": "updated"}


# ============================================================================
# 慢查询（暂用内存存储）
# ============================================================================

@router.get("/slow-queries")
async def list_slow_queries(
    limit: int = Query(default=50, ge=1, le=200),
):
    """列出慢查询（暂返回空，后续对接 DB Profiler）。"""
    return []
