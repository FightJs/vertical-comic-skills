---
name: vertical-comic-preproduction
description: Coordinate a staged vertical-comic workflow from approved scripts and assets to an accepted per-panel image package. Use for single or multiple episodes, whole-episode asynchronous generation, split preparation/production handoff, stage routing, resuming production, or explaining the comic skills. Excludes script rewriting, strip assembly, bubbles, lettering and PSD finishing.
---

# 条漫逐格成品生产总控

新整话同时执行[服装配饰定位与单画面](references/appearance-and-single-frame.md)：appearance_lock_v1固定当前衣装、配饰归属和身体锚点，single_frame_v1禁止一图双格。源稿多画面只选一幅绘制，原文/格序保留，未选内容不进实际prompt；A/B、实际参考、原QA及返修共用同一依据。新RV默认启用，旧RV按冻结版本，不热升级。

从批准脚本与资产推进到逐格成品图片包；不含拼接、气泡、文字排版或PSD。阶段请求只处理所选范围，不自动启动整套生产。

首次进入运行读[共同约束](references/production-foundation.md)、[固定流程](references/staged-workflow.md)和[规则归属](references/rule-ownership.md)。具体规则只在共享正式来源维护；运行按冻结版本读取，不在生产中更新规则库。

## 简易入口（首次使用优先）

用户首次使用或缺配置时，按[首次配置引导](references/quick-start.md#安装后的首次配置引导)一次收集缺少的书名、脚本、资产和话号，自动校验并生成本书配置；不要求用户预建JSON。已有配置只询问差异。

读[短启动与本书配置](references/quick-start.md)。用户只需脚本、资产、话号及可明确识别的书名，内部默认配置与规则自动解析，不要求填写技术JSON；“前期制作”路由分工前期并停在正文前，“接包生产”路由正式ZIP接收。用comic_start.py合并初始化或校验/解压/bind/rehearse步骤，初始化通过不等于源审计或批准通过。

规则记忆默认随本Skill内置，四个阶段共用assets/rule-memory；用户增补与内置规则分开。维护/导出/可选GitHub同步读[内置规则维护](references/builtin-rule-maintenance.md)；不需要GitHub账号才能生产或本地更新。明确外置来源和旧RV保持原冻结来源，不静默改库。

## 选择任务模式

- 新任务：按[整话异步](references/episode-async.md)使用episode_preparation_v1、episode_async_v1、scoped_episode_review_v1、comic_execution_v2与incremental_runtime_v2。全话准备、[逐格就绪](references/panel-readiness.md)，B与实际包合并展示并分别记录决定；缺口仅阻塞受影响格及真实依赖。默认无固定半话C。
- 恢复任务：先从原冻结入口运行staged_workflow.py --check status；按原模式、源序、输入、规则与预算恢复，不静默迁移旧RV。
- 用户指定分工制作：读[双电脑交接](references/split-production.md)、[直接交付](references/direct-delivery.md)及[ZIP演练](references/zip-handoff.md)。只提交获批当前半话，第一半话确认后才提交后半；缺技术编译的候选不能当正式可生产包。

核对准确书话、源脚本、真实格数及源序、资产、批准画风和输出RV，不按估计格数初始化。配置存在时读[使用配置](references/usage-configuration.md)，新任务用init_preproduction.py创建未批准模板。

## 阶段职责

A由[视觉资产](../vertical-comic-visual-assets/SKILL.md)维护身份、衣装、场景与画风；B由[镜头设计](../vertical-comic-shot-design/SKILL.md)落实动作、承托、机位及裁切；[逐格生图](../vertical-comic-panel-generation/SKILL.md)编译真实输入并提交；[图片验收](../vertical-comic-image-review/SKILL.md)完成实际QA、连续性与最终包。不要复制第二套身份、镜头或参考台账。

全批先按[批次运行](references/batch-runtime.md)冻结唯一快照。每话唯一owner写本话状态，总控单写共享调度；多话可按实际槽位使用最多五个工作agent，不能用新聊天替代。额度服从实际核定服务容量；本话租约内自主领取、预检、提交和保存。独立格异步，状态落盘串行；真实返回保存后释放生图槽，不等待QA。未知结果先查证，不超时重发。

[实际执行质量](references/execution-quality.md)把物理、场景方向、可见饰品、接触与原尺寸观察落到现有字段；技术PASS不证明空间或图片正确。源描述与批准物理条件冲突时先处理受影响A/B，不让模型自行改家具或动作。正文[比例计划](references/frame-ratio-plan.md)保留六种批准比例、竖版严格大于75%与交错要求，先验证内容容纳，不为凑比例扩大取景。

## 授权、修复与完成

按[合并审查](references/grouped-review.md)处理准确范围。用户亲自批准与执行者在明确委托内的决定分开记录，后者绑定真实用户授权及约束，不伪造APPROVED；配置或泛指继续不授予新权限。仅范围外事项、明确保留亲审项或外部阻塞需要用户处理。

每图真实审六项与适用规则，失败保留原件和记录。局部问题滚动修，超过5张真实失败先登记共因诊断；最多一轮自动修正。二轮仍失败停止自动尝试；明确追加授权单独保留次数和attempt，不重置预算。先分流裁切、局部编辑、修输入或停止诊断，不能靠强化措辞整图重抽。

[两级监控](references/worker-watchdog.md)只依据真实保存事件诊断。等人工不催执行者；本话仅等跨话比较时交回总控结束本轮。按[停点进度](references/review-progress.md)报告真实完成/待补与下一步，状态不变不反复通知。

每话独立完成真实QA、适用连续性及D决定后运行deliver门禁，保存逐格包、源序索引及证据。多话另做实际跨话边界比较；总包从已验收文件组装，校验计数/哈希/CRC，不重新生成合格图。统计按[增量运行](references/runtime-efficiency.md)及production_metrics.py记录，缺失时间不当作0，不把测试通过宣称为生图质量提升。
