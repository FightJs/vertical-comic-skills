# 使用配置与运行容量

当前新RV先读 [整话异步生产](episode-async.md) 和 [逐格就绪](panel-readiness.md)。B与包按准确就绪范围分别批准；独立格获批且完整预检通过即可提交。旧半话RV按其原合同恢复。

首次使用优先走[简易启动](quick-start.md)，配置由工具生成。comic_usage_v1保留inputs.script_path、asset_root；memory_root省略时默认解析Skill内置+用户增补。显式外置memory_root仍须是有效绝对目录，失效不回退。production.book及episodes明确书与话号；从真实脚本核对格数，不把配置合法当成已授权/批准生产。

当前generation配置：execution_mode=episode_async_v1、batch_strategy=full_episode、episode_workers=5、max_inflight_per_episode=episode、max_inflight_images=auto。不设batch_size。整话源格数是待提交池的上界，实际在途数仍受总控和已核定后端容量约束；后二者可设正整数上限。每话一名唯一执行者。

新任务的runtime.watchdog完整对象见 [执行者两级监控](worker-watchdog.md)，项目实例见 [配置示例](../../../examples/comic.config.example.json)。默认准备和自审/诊断5分钟T1、12分钟T2；单个请求15分钟T1、30分钟T2。六项秒数可调，均须为正整数且同类T2大于T1；不改变episode_workers或图像并发上限。旧RV未写watchdog按原冻结版本恢复。

新配置声明preparation.policy=episode_preparation_v1，初始化写入根visual_basis/shot_manifest/semantic_audit/gates，A/B及全话生图包各按实际范围确认；optimization.approval_scope=generation_episode_only表示整话逐格生成、自审和滚动返修。旧half_scoped_v1状态不自动迁移，行为见 [整话异步生产](episode-async.md)。

`physical_scene_priority_v1` 由新任务初始化自动写入生产流程、镜头表和 B 索引，属于生产合同，无需在本书使用配置里重复设置。镜头选集与单格执行包必须携带同版本；缺失或不一致时对应格保持 `INPUT_HOLD`。旧 RV 不自动回填。

```json
"preparation": {"policy": "episode_preparation_v1"},
"readiness": {"policy": "panel_readiness_v1"},
"optimization": {
  "policy": "scoped_episode_review_v1",
  "approval_scope": "generation_episode_only",
  "review_strategy": "on_return",
  "unchanged_qa": "reuse_recorded"
}
```

无配置的新初始化也采用整话优化策略；旧配置和旧RV保留原行为，不静默升级。新状态合并策略由真实B镜头逐格批准，JSON不授权跳过高风险确认。

review配置为systemic_failure_count_gt=5、max_auto_correction_rounds=1，保持用户确定的超过5张共因诊断、最多一轮自动修正。更改这两项要明确重新设计流程，不直接写数值绕过停止条件。memory.index=记忆索引.json、cache=run_worker_version、admission=cross_work_only继续使用，字段合同见 [rule-memory.md](rule-memory.md)。

当前规则库另显式启用独立读取扩展，配置、索引顶层及初始化后的 memory_source.loading_policy 必须一致：

```json
"memory": {
  "index": "记忆索引.json",
  "cache": "run_worker_version",
  "admission": "cross_work_only",
  "loading_policy": "stage_baseline_loading_v1"
}
```

索引每条 load_policy=stage_baseline（进入其 stages 时预读）或 on_match（实际命中再读）。当前 MEM-005/006 为前者，其他八条为后者；同agent/运行/版本只返回一次正文。预读不等于适用，不新增图片检查或人工停点；执行/QA仍按实际触发。修改读取方式属于规则维护：改索引对应条目、提高version并校验，不在使用配置里复制规则 ID 清单。

旧配置省略 loading_policy 只适配未升级的旧索引。新旧不一致立即 HOLD，不能默认补上字段。新任务使用上述配置直接初始化；无配置且直接 --memory-root 时另显式提供 --memory-loading-policy stage_baseline_loading_v1。配置和命令同时指定时必须一致；初始化只绑定来源，不加载正文或批准生产。旧任务迁移使用新RV核验版本/原批准，保持旧记录原样。

实际worker数取请求数、话数及当前可用子槽位的最小值。CLI --agent-slots含总控，五子agent＋总控填6；Codex自身max_concurrent_threads_per_session计数不含主agent。以当前实际工具容量为准，Skill不修改全局TOML。[OpenAI 配置参考](https://learn.chatgpt.com/docs/config-file/config-reference)

整话额度演算用--episode-panel-counts（源审计总格数JSON）和--active-episodes；--current-half-counts仅供旧半话RV。没有真实格数不虚报待提交池；没有实际核定backend-limit时max_inflight=null。容量确认后将全局上限写control.max_inflight，本话上限写job.max_inflight，active_batch_id=EPISODE；新策略再分配槽位租约，本话领取唯一许可。

旧permit模式实际执行由总控调用 `episode_dispatch_queue.py`，以当前状态和控制文件SHA256批量预留真实空闲许可；对返回格号再调用runtime `compile --panels` 完整检查。领取后编译失败保留许可待诊断，不以新attempt重发。具体命令、滚动返修和超过5张视觉失败时的共因登记见 [整话异步生产](episode-async.md)。

```text
python <scripts>/usage_config.py --config <配置JSON>
python <scripts>/usage_config.py --config <配置JSON> --agent-slots 6 --backend-limit <实际核定容量> --active-episodes E021 E022 --episode-panel-counts '{"E021":30,"E022":35}'
python <快照scripts>/init_preproduction.py --config <配置JSON> --runtime-snapshot <本批运行快照/manifest.json> --output <新RV> --book <配置book> --episode E021 --backend codex_builtin_imagegen
```

第二条只演算两个话的待提交池，不探测/申请容量。初始化只建未批准模板，绑定memory_source和整话/自审策略，不派agent、不生图。显式--execution-mode可选择旧half_episode_async_v1/batch5_v1/sequential_v1；使用旧配置时保持原模式。整话不设--batch-size。

修改配置只对新任务及明确迁移生效；旧RV恢复按冻结记录。中途调额度先暂停新派发、处理超出新额度的在途请求，再由总控更新。高风险新状态、第二轮停止及最终D不因速度调整省略。真并发调用见 [async-generation.md](async-generation.md)。

当前新任务还启用执行兼容配置，须配套整话与审查复用策略：

```json
"execution": {
  "contract": "comic_execution_v2",
  "request_log": "structured",
  "semantic_audit": "before_freeze",
  "id_mapping": "source_preserving"
}
```

初始化冻结真实共享工具版本、准确话序及空前格登记；全话源映射、语义核对、逐格包与真实批准仍须执行者完成。执行字段不是并发上限；由generation.episode_workers和实际许可容量控制。旧配置/旧RV不自动升级。

当前新任务启用framing={"policy":"content_balanced_ratios_v1"}。初始化写入frame_ratio_policy和空frame_ratio_plan，不预填统一9:16。比例由源内容决定，分布在B冻结前一次核验，D按实图复核。详见 [全话画幅计划](frame-ratio-plan.md)。

## 当前提速配置

当前整话新初始化默认追加下列runtime；自审分组4张不是生图批量4张。

~~~json
"runtime": {
  "policy": "incremental_runtime_v2",
  "audit_scope": "requested_episodes",
  "checkpoint_presentation": "grouped",
  "episode_review_dispatch": "as_ready",
  "review_group_size": 4,
  "review_max_wait_seconds": 30
}
~~~

实际用法见 [整话异步生产](episode-async.md)。新RV没有固定半话C；3–5张/1–30秒仅合并自审通知，依赖/校准图即时审。旧RV不原地添加runtime或准备策略。

无配置的新全话初始化默认启用panel_readiness_v1；配置文件须显式填写readiness对象。省略它的旧配置保留旧行为，不默认迁移。初始化只绑定策略，不批准任何格。

新建整话默认启用 `quality: {"policy":"visual_evidence_v1"}`，无需在每次启动消息重复规则。参数只用于新RV，不修改已有运行策略；实际配置、输入输出和返修例子见 [质量证据使用说明](visual-evidence.md)。

## 新任务运行策略

本项目新配置runtime追加snapshot_policy=batch_snapshot_v1、question_policy=grouped_review_v1、dispatch_policy=episode_slot_lease_v1。开批一次创建快照，各话初始化传同一--runtime-snapshot；配置不是批准。具体命令见[批次运行](batch-runtime.md)，审查范围见[合并审查](grouped-review.md)。旧配置与已有RV不自动添加字段。


新配置增加 `"background": {"policy":"narrative_background_v1","selection":"content_driven","closeup_preference":"scene_flat"}`，与framing画幅比例配置独立。配置省略保持旧行为；无配置的新整话初始化默认启用；旧RV不自动升级。A准备profile、B逐格批准模式，实际包仍按原准确范围批准。详见[背景模式](background-treatment.md)。


新配置execution_quality={"policy":"execution_quality_v1"}，仅新整话RV启用；旧配置省略保持旧行为见[实际执行质量与返修分流](execution-quality.md)。复用现有记录和人工停点，不静默升级旧RV。


## 分工模式与现有配置的关系

先确定[任务来源](task-origin.md)。本书配置只提供路径和运行偏好；fresh独立任务不继承同书同话旧调用。接包/恢复保留原task_context；任务身份不是新的并发或人工批准开关。

用户显式选择分工制作时按[split-production.md](split-production.md)切换职责和半话提交窗口；现有generation.execution_mode=episode_async_v1及当前runtime不改成旧半话格式。源配置提供书/话/来源/规则和请求容量，实际本次明确书话优先并须核对范围。前期停在正文前；接包端建立本地路径/容量绑定，原批准原件与规则版本保留。模式名不是现有CLI参数，不宣称配置读取器自动创建半话人工停点或跨机迁移。用法对齐不授权修改全局或正在运行RV的配置。


分工正式导出采用[ZIP交接闭环](zip-handoff.md)：候选ZIP须先在全新目录解压并通过真实冻结门禁演练，核清历史预算和准确就绪范围，再取得真实导出确认，发布正式ZIP及SHA256。接包路径填写ZIP绝对路径；按包内具体说明新建本地RV，不直接运行前期目录。半话/高风险/D人工节点保持原要求，无需新增全局配置字段。

新正式分工包按[直接交付合同](direct-delivery.md)使用direct_delivery_v2：全部技术编译先于最终B/包审查；真实批准可附不变输入演练通过后直接导出的条件授权。接手端bind自动建立本地运行，完整前期资料/历史/预算未闭合不发布正式包。此项是分工交付策略，不修改正在运行旧RV。

## 执行方式与授权来源

开批区分逐项用户审查和真实用户委托下的范围内决定，操作方法见grouped-review.md。配置只表达运行偏好，不生成AUTHORIZED或APPROVED；委托原文、来源、格号、阶段、保留亲审事项及具体约束仍存本批证据并由门禁核验。用户授权范围变化时追加新证据，不覆写旧批准或扩大旧次数。

当前安装版新建episode_async_v1默认写入input_quality_policy=execution_quality_v1，即使旧使用配置未列execution_quality。该默认只作用于新初始化；恢复现有RV继续使用其冻结快照和原字段，不自动补写策略或重签批准。
