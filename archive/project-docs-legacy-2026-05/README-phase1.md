# Pipeline Phase 1 Skeleton

这个目录是为“爆款视频工作流不停产迁移”准备的第一阶段工程骨架。

## 当前包含

- docs/pipeline-migration-phase1.md
- src/config/*
- src/core/*
- src/services/*
- src/types/task.ts
- src/workers/render.worker.ts

## 用途

这一版不是完整业务代码，而是一个可以逐步把现有脚本接进来的基础层：
- 统一配置
- 统一日志
- 统一错误码
- 统一重试/超时
- 统一 service 入口
- render worker 骨架

## 建议下一步

1. 把现有 FastMoss / Gemini / Sora / Feishu 调用迁到 `src/services/`
2. 把现有视频生成逻辑优先接到 `runRenderTask`
3. 增加数据库层（Phase 2）
4. 增加 scheduler 和 task claim 机制
