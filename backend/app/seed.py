"""
Seed 脚本 — 向数据库插入初始开发数据
用法: python -m app.seed
"""
from __future__ import annotations

import asyncio
import uuid
from datetime import datetime, timezone, timedelta

from app.database import async_session_factory, init_db
from app.models.agent import Agent
from app.models.pipeline import PipelineTemplate, PipelineRun
from app.models.skill import Skill
from app.models.memory import MemoryEntry
from app.models.event import LLMCall
from app.models.settings import ModelConfig, ApiKey, AgentPermission


def _dt(s: str) -> datetime:
    """简写：ISO 字符串 → UTC datetime"""
    return datetime.fromisoformat(s.replace("Z", "+00:00"))


async def seed():
    await init_db()
    async with async_session_factory() as db:

        # ---- Agents (8) ----
        agents_data = [
            {"name": "Architect-01", "role": "architect", "status": "running", "model": "gpt-4o",
             "description": "系统架构设计专家", "system_prompt": None,  # 使用角色默认提示词
             "capability_tags": "architecture_design,api_design",
             "max_retries": 3, "timeout_sec": 300, "is_active": True,
             "total_tasks": 24, "completed_tasks": 22, "failed_tasks": 1,
             "avg_duration": 180000, "total_tokens": 125000, "total_cost": 2.50},
            {"name": "Dev-01", "role": "developer", "status": "running", "model": "gpt-4o",
             "description": "后端开发专家",
             "system_prompt": "你是一名资深 Python 后端开发工程师。\n\n核心原则:\n- 优先使用 FastAPI + SQLAlchemy async + Pydantic 技术栈\n- 所有数据库操作必须异步\n- 遵循 SOLID 原则和 Clean Architecture\n- 代码必须包含类型注解\n- 每个函数要有 docstring\n- 错误要抛出有意义的 HTTPException 而非裸异常\n\n输出格式:\n- 代码文件路径开头\n- 修改点标注行号范围\n- 新增依赖列出 pip install 命令",
             "max_retries": 3, "timeout_sec": 300, "is_active": True,
             "total_tasks": 48, "completed_tasks": 44, "failed_tasks": 2,
             "avg_duration": 350000, "total_tokens": 320000, "total_cost": 6.40},
            {"name": "Frontend-01", "role": "developer", "status": "idle", "model": "gpt-4o",
             "description": "前端开发专家", "capability_tags": "code_generation,refactor",
             "max_retries": 3, "timeout_sec": 300, "is_active": True,
             "total_tasks": 36, "completed_tasks": 34, "failed_tasks": 1,
             "avg_duration": 280000, "total_tokens": 280000, "total_cost": 5.60},
            {"name": "Dev-02", "role": "developer", "status": "running", "model": "claude-3.5-sonnet",
             "description": "全栈开发", "capability_tags": "code_generation,deployment",
             "max_retries": 3, "timeout_sec": 300, "is_active": True,
             "total_tasks": 42, "completed_tasks": 38, "failed_tasks": 3,
             "avg_duration": 320000, "total_tokens": 350000, "total_cost": 7.00},
            {"name": "DevOps-01", "role": "deployer", "status": "idle", "model": "gpt-4o",
             "description": "DevOps 专家", "capability_tags": "deployment,monitoring",
             "max_retries": 3, "timeout_sec": 300, "is_active": True,
             "total_tasks": 18, "completed_tasks": 17, "failed_tasks": 0,
             "avg_duration": 150000, "total_tokens": 85000, "total_cost": 1.70},
            {"name": "Reviewer-01", "role": "reviewer", "status": "running", "model": "gpt-4o",
             "description": "代码审查专家", "capability_tags": "code_review,security_audit",
             "max_retries": 3, "timeout_sec": 300, "is_active": True,
             "total_tasks": 56, "completed_tasks": 55, "failed_tasks": 0,
             "avg_duration": 240000, "total_tokens": 420000, "total_cost": 8.40},
            {"name": "Tester-01", "role": "tester", "status": "idle", "model": "gpt-4o",
             "description": "测试工程师", "system_prompt": None,
             "capability_tags": "test_generation,test_execution",
             "max_retries": 3, "timeout_sec": 300, "is_active": True,
             "total_tasks": 32, "completed_tasks": 30, "failed_tasks": 1,
             "avg_duration": 200000, "total_tokens": 180000, "total_cost": 3.60},
            {"name": "Dev-03", "role": "developer", "status": "idle", "model": "claude-3.5-sonnet", "model_mode": "auto",
             "description": "智能路由开发（auto模式）", "capability_tags": "code_generation",
             "max_retries": 3, "timeout_sec": 300, "is_active": True,
             "total_tasks": 15, "completed_tasks": 13, "failed_tasks": 1,
             "avg_duration": 260000, "total_tokens": 95000, "total_cost": 1.90},
        ]
        agent_map: dict[str, uuid.UUID] = {}
        for a in agents_data:
            obj = Agent(**a)
            db.add(obj)
            agent_map[a["name"]] = obj.id
        await db.flush()

        # ---- Pipeline Templates (6) ----
        templates = [
            {"name": "新功能开发全流程", "description": "从需求分析到代码部署的完整开发 Pipeline",
             "icon": "CodeOutlined", "category": "dev", "tags": "开发,全流程,推荐",
             "steps_json": [
                 {"id": "s1", "name": "需求分析", "type": "agent", "agent_role": "architect", "description": "Architect Agent 分析需求", "next_steps": ["s2"]},
                 {"id": "s2", "name": "代码实现", "type": "agent", "agent_role": "developer", "description": "Developer Agent 编写代码", "next_steps": ["s3", "s4"]},
                 {"id": "s3", "name": "单元测试", "type": "agent", "agent_role": "tester", "description": "Tester Agent 执行测试", "next_steps": ["s5"]},
                 {"id": "s4", "name": "代码审查", "type": "review", "agent_role": "", "description": "人工审查代码", "next_steps": ["s5"]},
                 {"id": "s5", "name": "条件检查", "type": "condition", "agent_role": "", "description": "检查通过后部署", "next_steps": ["s6"]},
                 {"id": "s6", "name": "自动部署", "type": "deploy", "agent_role": "", "description": "DevOps Agent 执行部署", "next_steps": ["s7"]},
                 {"id": "s7", "name": "通知", "type": "notify", "agent_role": "", "description": "发送通知", "next_steps": []},
             ], "avg_duration": 720000, "success_rate": 94.5},
            {"name": "API 接口开发", "description": "快速开发 RESTful API",
             "icon": "ApiOutlined", "category": "dev", "tags": "API,后端",
             "steps_json": [
                 {"id": "a1", "name": "接口设计", "type": "agent", "agent_role": "architect", "description": "设计 API", "next_steps": ["a2"]},
                 {"id": "a2", "name": "编码实现", "type": "agent", "agent_role": "developer", "description": "实现 API", "next_steps": ["a3", "a4"]},
                 {"id": "a3", "name": "单元测试", "type": "agent", "agent_role": "tester", "description": "生成测试", "next_steps": ["a5"]},
                 {"id": "a4", "name": "文档生成", "type": "agent", "agent_role": "developer", "description": "生成文档", "next_steps": ["a5"]},
                 {"id": "a5", "name": "审查合并", "type": "review", "agent_role": "", "description": "Review 后合并", "next_steps": []},
             ], "avg_duration": 480000, "success_rate": 97.2},
            {"name": "Bug 修复流程", "description": "快速定位和修复 Bug",
             "icon": "BugOutlined", "category": "dev", "tags": "Bug,修复",
             "steps_json": [
                 {"id": "b1", "name": "Bug 分析", "type": "agent", "agent_role": "developer", "description": "分析根因", "next_steps": ["b2"]},
                 {"id": "b2", "name": "修复实现", "type": "agent", "agent_role": "developer", "description": "编写修复代码", "next_steps": ["b3"]},
                 {"id": "b3", "name": "回归测试", "type": "agent", "agent_role": "tester", "description": "运行测试", "next_steps": ["b4"]},
                 {"id": "b4", "name": "审查部署", "type": "review", "agent_role": "", "description": "审查后部署", "next_steps": []},
             ], "avg_duration": 180000, "success_rate": 92.8},
            {"name": "数据库迁移", "description": "安全的 Schema 变更",
             "icon": "DatabaseOutlined", "category": "ops", "tags": "数据库,运维",
             "steps_json": [
                 {"id": "d1", "name": "迁移方案", "type": "agent", "agent_role": "architect", "description": "生成方案", "next_steps": ["d2"]},
                 {"id": "d2", "name": "数据备份", "type": "agent", "agent_role": "deployer", "description": "全量备份", "next_steps": ["d3"]},
                 {"id": "d3", "name": "执行迁移", "type": "deploy", "agent_role": "", "description": "执行变更", "next_steps": ["d4"]},
                 {"id": "d4", "name": "验证", "type": "agent", "agent_role": "tester", "description": "验证完整性", "next_steps": []},
             ], "avg_duration": 360000, "success_rate": 99.1},
            {"name": "安全审计流程", "description": "全面的代码安全审计",
             "icon": "SafetyOutlined", "category": "review", "tags": "安全,审计",
             "steps_json": [
                 {"id": "se1", "name": "依赖扫描", "type": "agent", "agent_role": "reviewer", "description": "扫描漏洞", "next_steps": ["se3"]},
                 {"id": "se2", "name": "静态分析", "type": "agent", "agent_role": "reviewer", "description": "静态安全分析", "next_steps": ["se3"]},
                 {"id": "se3", "name": "合规检查", "type": "condition", "agent_role": "", "description": "汇总检查", "next_steps": ["se4"]},
                 {"id": "se4", "name": "审计报告", "type": "notify", "agent_role": "", "description": "生成报告", "next_steps": []},
             ], "avg_duration": 300000, "success_rate": 88.6},
            {"name": "数据分析 Pipeline", "description": "数据清洗→建模→可视化",
             "icon": "BarChartOutlined", "category": "data", "tags": "数据,分析",
             "steps_json": [
                 {"id": "da1", "name": "数据采集", "type": "agent", "agent_role": "developer", "description": "采集数据", "next_steps": ["da2"]},
                 {"id": "da2", "name": "数据清洗", "type": "agent", "agent_role": "developer", "description": "清洗数据", "next_steps": ["da3"]},
                 {"id": "da3", "name": "建模分析", "type": "agent", "agent_role": "architect", "description": "构建模型", "next_steps": ["da4"]},
                 {"id": "da4", "name": "可视化", "type": "agent", "agent_role": "developer", "description": "生成图表", "next_steps": ["da5"]},
                 {"id": "da5", "name": "结果推送", "type": "notify", "agent_role": "", "description": "推送结果", "next_steps": []},
             ], "avg_duration": 600000, "success_rate": 95.3},
        ]
        tpl_map: dict[str, uuid.UUID] = {}
        for t in templates:
            obj = PipelineTemplate(**t)
            db.add(obj)
            tpl_map[t["name"]] = obj.id
        await db.flush()

        # ---- Pipeline Runs (7) ----
        runs = [
            {"template_id": tpl_map["新功能开发全流程"], "template_name": "新功能开发全流程",
             "status": "running", "started_at": _dt("2026-05-29T09:00:00Z"),
             "current_step": "代码实现", "total_steps": 7, "completed_steps": 1,
             "failed_steps": 0, "triggered_by": "手动触发", "cost": 1.25},
            {"template_id": tpl_map["API 接口开发"], "template_name": "API 接口开发",
             "status": "completed", "started_at": _dt("2026-05-29T07:30:00Z"),
             "completed_at": _dt("2026-05-29T08:45:00Z"), "duration": 4500000,
             "total_steps": 5, "completed_steps": 5, "failed_steps": 0,
             "triggered_by": "Webhook", "cost": 0.85},
            {"template_id": tpl_map["Bug 修复流程"], "template_name": "Bug 修复流程",
             "status": "failed", "started_at": _dt("2026-05-29T08:00:00Z"),
             "completed_at": _dt("2026-05-29T08:32:00Z"), "duration": 1920000,
             "current_step": "回归测试", "total_steps": 4, "completed_steps": 2,
             "failed_steps": 1, "triggered_by": "自动触发", "cost": 0.42},
            {"template_id": tpl_map["安全审计流程"], "template_name": "安全审计流程",
             "status": "running", "started_at": _dt("2026-05-29T10:00:00Z"),
             "current_step": "静态分析", "total_steps": 4, "completed_steps": 1,
             "failed_steps": 0, "triggered_by": "定时任务", "cost": 0.30},
            {"template_id": tpl_map["数据库迁移"], "template_name": "数据库迁移",
             "status": "completed", "started_at": _dt("2026-05-28T22:00:00Z"),
             "completed_at": _dt("2026-05-28T22:45:00Z"), "duration": 2700000,
             "total_steps": 4, "completed_steps": 4, "failed_steps": 0,
             "triggered_by": "手动触发", "cost": 0.55},
            {"template_id": tpl_map["数据分析 Pipeline"], "template_name": "数据分析 Pipeline",
             "status": "completed", "started_at": _dt("2026-05-28T18:00:00Z"),
             "completed_at": _dt("2026-05-28T19:15:00Z"), "duration": 4500000,
             "total_steps": 5, "completed_steps": 5, "failed_steps": 0,
             "triggered_by": "定时任务", "cost": 1.10},
            {"template_id": tpl_map["API 接口开发"], "template_name": "API 接口开发",
             "status": "paused", "started_at": _dt("2026-05-29T08:30:00Z"),
             "current_step": "编码实现", "total_steps": 5, "completed_steps": 1,
             "failed_steps": 0, "triggered_by": "手动触发", "cost": 0.12},
        ]
        for r in runs:
            db.add(PipelineRun(**r))
        await db.flush()

        # ---- Skills (12) ----
        skills_data = [
            {"name": "Code Review Expert", "description": "自动化代码审查，检测安全漏洞、性能问题",
             "category": "code", "icon": "CodeOutlined", "author": "AI-OS Team",
             "version": "2.3.1", "downloads": 12400, "rating": 4.8,
             "installed": True, "size": "2.4 MB", "tags": "审查,安全,多语言",
             "requires_config": True, "config_fields": "review_rules,severity_threshold"},
            {"name": "GitHub Actions Builder", "description": "智能生成 GitHub Actions 工作流",
             "category": "ops", "icon": "GithubOutlined", "author": "Community",
             "version": "1.5.0", "downloads": 8900, "rating": 4.6,
             "installed": True, "size": "1.8 MB", "tags": "CI/CD,GitHub",
             "requires_config": True, "config_fields": "github_token"},
            {"name": "API Documentation Generator", "description": "根据代码自动生成 OpenAPI 文档",
             "category": "code", "icon": "FileTextOutlined", "author": "AI-OS Team",
             "version": "3.0.2", "downloads": 15600, "rating": 4.9,
             "installed": True, "size": "3.1 MB", "tags": "API,文档",
             "requires_config": False, "config_fields": ""},
            {"name": "Database Migration Helper", "description": "安全的数据库迁移辅助",
             "category": "data", "icon": "DatabaseOutlined", "author": "AI-OS Team",
             "version": "1.8.0", "downloads": 7200, "rating": 4.5,
             "installed": False, "size": "1.5 MB", "tags": "数据库,迁移",
             "requires_config": True, "config_fields": "db_connection"},
            {"name": "Slack Integration", "description": "通过 Slack 接收任务通知",
             "category": "communication", "icon": "SlackOutlined", "author": "Community",
             "version": "2.1.3", "downloads": 6300, "rating": 4.3,
             "installed": False, "size": "0.9 MB", "tags": "Slack,通知",
             "requires_config": True, "config_fields": "slack_webhook"},
            {"name": "Dependency Scanner", "description": "扫描依赖安全漏洞",
             "category": "security", "icon": "SafetyOutlined", "author": "Security Lab",
             "version": "4.2.0", "downloads": 10100, "rating": 4.7,
             "installed": True, "size": "5.2 MB", "tags": "安全,依赖",
             "requires_config": True, "config_fields": "severity_level"},
            {"name": "Performance Profiler", "description": "性能分析工具",
             "category": "code", "icon": "ThunderboltOutlined", "author": "AI-OS Team",
             "version": "1.2.0", "downloads": 5400, "rating": 4.4,
             "installed": False, "size": "3.8 MB", "tags": "性能,优化",
             "requires_config": True, "config_fields": "sample_rate"},
            {"name": "Docker Compose Generator", "description": "自动生成 docker-compose.yml",
             "category": "ops", "icon": "CloudOutlined", "author": "Community",
             "version": "2.0.1", "downloads": 8400, "rating": 4.6,
             "installed": False, "size": "1.3 MB", "tags": "Docker,部署",
             "requires_config": False, "config_fields": ""},
            {"name": "Test Case Generator", "description": "自动生成测试用例",
             "category": "code", "icon": "ExperimentOutlined", "author": "AI-OS Team",
             "version": "3.1.0", "downloads": 11200, "rating": 4.7,
             "installed": True, "size": "2.7 MB", "tags": "测试,TDD",
             "requires_config": True, "config_fields": "test_framework"},
            {"name": "i18n Translator", "description": "自动翻译国际化文案",
             "category": "media", "icon": "TranslationOutlined", "author": "Community",
             "version": "1.4.2", "downloads": 3900, "rating": 4.2,
             "installed": False, "size": "1.1 MB", "tags": "i18n,翻译",
             "requires_config": True, "config_fields": "api_key"},
            {"name": "PDF Report Builder", "description": "从 Markdown 生成 PDF 报告",
             "category": "media", "icon": "FilePdfOutlined", "author": "AI-OS Team",
             "version": "2.5.0", "downloads": 6700, "rating": 4.5,
             "installed": False, "size": "4.0 MB", "tags": "PDF,报告",
             "requires_config": True, "config_fields": "template"},
            {"name": "Kubernetes Deployer", "description": "智能 K8s 部署",
             "category": "ops", "icon": "ClusterOutlined", "author": "Cloud Team",
             "version": "1.0.5", "downloads": 4500, "rating": 4.1,
             "installed": False, "size": "2.0 MB", "tags": "K8s,部署",
             "requires_config": True, "config_fields": "kubeconfig"},
        ]
        for s in skills_data:
            db.add(Skill(**s))
        await db.flush()

        # ---- Memories (11) ----
        memories_data = [
            {"layer": "cloud", "title": "技术栈偏好",
             "content": "用户偏好 TypeScript + React + Python 技术栈。",
             "tags": "技术栈,偏好", "source": "自动学习", "importance": "high", "token_estimate": 120},
            {"layer": "cloud", "title": "工作背景",
             "content": "用户是 Windows 管理员，负责 WorkBuddy 项目开发。",
             "tags": "工作,背景", "source": "自动学习", "importance": "high", "token_estimate": 150},
            {"layer": "cloud", "title": "沟通风格",
             "content": "用户偏好中文交流，直接务实。",
             "tags": "风格,偏好", "source": "自动学习", "importance": "high", "token_estimate": 85},
            {"layer": "cloud", "title": "C 盘空间清理",
             "content": "C 盘 315GB 仅剩 1.1GB。",
             "tags": "系统,磁盘", "source": "自动学习", "importance": "medium", "token_estimate": 140},
            {"layer": "user", "title": "代码规范：文件行数限制",
             "content": "每个代码文件不超过 500 行。",
             "tags": "规范,代码", "source": "手动设置", "importance": "high", "token_estimate": 50},
            {"layer": "user", "title": "前端架构偏好",
             "content": "React 18 + TypeScript + Vite + Ant Design 5.x + Zustand。",
             "tags": "前端,架构", "source": "手动设置", "importance": "high", "token_estimate": 95},
            {"layer": "user", "title": "Git 提交规范",
             "content": "使用 Conventional Commits 规范。",
             "tags": "Git,规范", "source": "手动设置", "importance": "medium", "token_estimate": 60},
            {"layer": "project", "title": "AI Runtime OS 项目概述",
             "content": "构建 AI Agent 流程化管理工具。",
             "tags": "项目,架构", "source": "工作日志", "importance": "high", "token_estimate": 110},
            {"layer": "project", "title": "Phase 1 MVP 前端完成",
             "content": "已完成 Dashboard、Agent 看板、Trace 追踪。",
             "tags": "前端,里程碑", "source": "工作日志", "importance": "high", "token_estimate": 100},
            {"layer": "project", "title": "目录结构规范",
             "content": "ai-agent-os/ 下分 frontend/ backend/ docs/。",
             "tags": "规范,目录", "source": "工作日志", "importance": "high", "token_estimate": 70},
            {"layer": "project", "title": "Pipelines 流程设计",
             "content": "V1 支持 6 种 Pipeline 模板。",
             "tags": "Pipelines,设计", "source": "工作日志", "importance": "medium", "token_estimate": 105},
        ]
        for m in memories_data:
            db.add(MemoryEntry(**m))
        await db.flush()

        # ---- LLM Calls (12) ----
        llm_calls = [
            {"agent_id": agent_map["Reviewer-01"], "agent_name": "Reviewer-01", "model": "gpt-4o",
             "task_type": "代码审查", "prompt_tokens": 4200, "completion_tokens": 1800,
             "total_tokens": 6000, "estimated_cost": 0.34, "latency_ms": 240000,
             "created_at": _dt("2026-05-29T10:15:00Z")},
            {"agent_id": agent_map["Dev-02"], "agent_name": "Dev-02", "model": "claude-3.5-sonnet",
             "task_type": "API 开发", "prompt_tokens": 5800, "completion_tokens": 3200,
             "total_tokens": 9000, "estimated_cost": 0.46, "latency_ms": 320000,
             "created_at": _dt("2026-05-29T09:30:00Z")},
            {"agent_id": agent_map["Dev-01"], "agent_name": "Dev-01", "model": "gpt-4o",
             "task_type": "功能开发", "prompt_tokens": 6500, "completion_tokens": 4100,
             "total_tokens": 10600, "estimated_cost": 0.65, "latency_ms": 350000,
             "created_at": _dt("2026-05-29T09:00:00Z")},
            {"agent_id": agent_map["Frontend-01"], "agent_name": "Frontend-01", "model": "gpt-4o",
             "task_type": "组件开发", "prompt_tokens": 3200, "completion_tokens": 2100,
             "total_tokens": 5300, "estimated_cost": 0.33, "latency_ms": 280000,
             "created_at": _dt("2026-05-29T08:45:00Z")},
            {"agent_id": agent_map["Architect-01"], "agent_name": "Architect-01", "model": "gpt-4o",
             "task_type": "架构设计", "prompt_tokens": 4800, "completion_tokens": 2800,
             "total_tokens": 7600, "estimated_cost": 0.46, "latency_ms": 180000,
             "created_at": _dt("2026-05-29T08:00:00Z")},
            {"agent_id": agent_map["DevOps-01"], "agent_name": "DevOps-01", "model": "gpt-4o",
             "task_type": "部署配置", "prompt_tokens": 1800, "completion_tokens": 900,
             "total_tokens": 2700, "estimated_cost": 0.16, "latency_ms": 150000,
             "created_at": _dt("2026-05-28T18:00:00Z")},
            {"agent_id": agent_map["Reviewer-01"], "agent_name": "Reviewer-01", "model": "gpt-4o",
             "task_type": "安全审查", "prompt_tokens": 5200, "completion_tokens": 2200,
             "total_tokens": 7400, "estimated_cost": 0.41, "latency_ms": 260000,
             "created_at": _dt("2026-05-28T16:00:00Z")},
            {"agent_id": agent_map["Dev-03"], "agent_name": "Dev-03", "model": "claude-3.5-sonnet",
             "task_type": "前端组件", "prompt_tokens": 3900, "completion_tokens": 2400,
             "total_tokens": 6300, "estimated_cost": 0.34, "latency_ms": 260000,
             "created_at": _dt("2026-05-28T15:00:00Z")},
            {"agent_id": agent_map["Dev-01"], "agent_name": "Dev-01", "model": "gpt-4o",
             "task_type": "后端重构", "prompt_tokens": 7800, "completion_tokens": 4500,
             "total_tokens": 12300, "estimated_cost": 0.73, "latency_ms": 420000,
             "created_at": _dt("2026-05-28T14:00:00Z")},
            {"agent_id": agent_map["Tester-01"], "agent_name": "Tester-01", "model": "gpt-4o",
             "task_type": "测试生成", "prompt_tokens": 2500, "completion_tokens": 3500,
             "total_tokens": 6000, "estimated_cost": 0.45, "latency_ms": 200000,
             "created_at": _dt("2026-05-28T10:00:00Z")},
            {"agent_id": agent_map["Dev-02"], "agent_name": "Dev-02", "model": "claude-3.5-sonnet",
             "task_type": "微服务开发", "prompt_tokens": 6200, "completion_tokens": 3800,
             "total_tokens": 10000, "estimated_cost": 0.53, "latency_ms": 380000,
             "created_at": _dt("2026-05-27T16:00:00Z")},
            {"agent_id": agent_map["Architect-01"], "agent_name": "Architect-01", "model": "gpt-4o",
             "task_type": "技术选型", "prompt_tokens": 5500, "completion_tokens": 3100,
             "total_tokens": 8600, "estimated_cost": 0.52, "latency_ms": 200000,
             "created_at": _dt("2026-05-27T14:00:00Z")},
        ]
        for c in llm_calls:
            db.add(LLMCall(**c))
        await db.flush()

        # ---- Model Configs (5) ----
        models_data = [
            {"name": "GPT-4o", "provider": "openai", "endpoint": "https://api.openai.com/v1",
             "enabled": True, "default_for": "architect,developer,reviewer,tester",
             "max_tokens": 128000, "temperature": 0.4, "api_key_configured": True},
            {"name": "GPT-4o Mini", "provider": "openai", "endpoint": "https://api.openai.com/v1",
             "enabled": True, "default_for": "tester",
             "max_tokens": 128000, "temperature": 0.6, "api_key_configured": True},
            {"name": "Claude 3.5 Sonnet", "provider": "anthropic", "endpoint": "https://api.anthropic.com/v1",
             "enabled": True, "default_for": "developer,deployer",
             "max_tokens": 200000, "temperature": 0.3, "api_key_configured": True},
            {"name": "Claude 3 Opus", "provider": "anthropic", "endpoint": "https://api.anthropic.com/v1",
             "enabled": False, "default_for": "",
             "max_tokens": 200000, "temperature": 0.2, "api_key_configured": False},
            {"name": "Qwen2.5 (Ollama)", "provider": "ollama", "endpoint": "http://localhost:11434",
             "enabled": True, "default_for": "developer",
             "max_tokens": 32768, "temperature": 0.7, "api_key_configured": False},
        ]
        for mc in models_data:
            db.add(ModelConfig(**mc))
        await db.flush()

        # ---- API Keys (2) ----
        api_keys_data = [
            {"provider": "openai", "label": "OpenAI API Key", "masked_key": "sk-****aB3d",
             "encrypted_key": "", "enabled": True, "last_used": "2026-05-29T10:15:00Z"},
            {"provider": "anthropic", "label": "Anthropic API Key", "masked_key": "sk-ant-****Xy9Z",
             "encrypted_key": "", "enabled": True, "last_used": "2026-05-29T09:30:00Z"},
        ]
        for ak in api_keys_data:
            db.add(ApiKey(**ak))
        await db.flush()

        # ---- Agent Permissions (5) ----
        permissions_data = [
            {"role_id": "architect", "role_name": "架构师",
             "can_create_pipeline": True, "can_deploy": False,
             "can_access_network": True, "can_write_files": True, "can_execute_commands": False,
             "max_concurrency": 2, "max_tokens_per_task": 50000, "max_daily_cost": 15},
            {"role_id": "developer", "role_name": "开发者",
             "can_create_pipeline": False, "can_deploy": False,
             "can_access_network": True, "can_write_files": True, "can_execute_commands": True,
             "max_concurrency": 4, "max_tokens_per_task": 30000, "max_daily_cost": 10},
            {"role_id": "reviewer", "role_name": "审查员",
             "can_create_pipeline": False, "can_deploy": False,
             "can_access_network": True, "can_write_files": False, "can_execute_commands": False,
             "max_concurrency": 3, "max_tokens_per_task": 20000, "max_daily_cost": 10},
            {"role_id": "tester", "role_name": "测试员",
             "can_create_pipeline": False, "can_deploy": False,
             "can_access_network": False, "can_write_files": False, "can_execute_commands": True,
             "max_concurrency": 4, "max_tokens_per_task": 25000, "max_daily_cost": 8},
            {"role_id": "deployer", "role_name": "部署员",
             "can_create_pipeline": False, "can_deploy": True,
             "can_access_network": True, "can_write_files": True, "can_execute_commands": True,
             "max_concurrency": 2, "max_tokens_per_task": 15000, "max_daily_cost": 5},
        ]
        for p in permissions_data:
            db.add(AgentPermission(**p))

        await db.commit()
        print("Seed 完成！")


if __name__ == "__main__":
    asyncio.run(seed())
