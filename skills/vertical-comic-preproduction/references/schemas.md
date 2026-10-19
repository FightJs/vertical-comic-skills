# 结构化记录字段

## 状态

- `INPUT`
- `IDENTITY_HOLD`
- `APPEARANCE_HOLD`
- `SCENE_IDENTITY_HOLD`
- `CANDIDATE`
- `CAMERA_CANDIDATE`
- `CAMERA_LOCKED`
- `ASSET_CANDIDATE`
- `ASSET_HOLD`
- `STATION_CANDIDATE`
- `CAMERA_HOLD`
- `PROMPT_PACKAGE_HOLD`
- `PASS_WITH_WARNINGS`
- `USER_ACCEPTED`

## 镜头记录

新镜头表和新提示词索引在根节点声明 `framing_policy=information_first_v1`。每格以 `framing` 分别记录景别之外的身体裁切、视觉重点与背景必要程度；详细判断见 [shot-framing.md](shot-framing.md)。

```json
{
  "panel_id": "P001",
  "script_shot_id": "SHOT-001",
  "scene_id": "SC-001",
  "station_state_id": "ST-001",
  "camera_view_id": "CAM-001",
  "camera_position": {"x": 0.0, "y": 0.0, "z": 1.6},
  "camera_height": "人物胸口高度",
  "facing_direction": "朝向场景东南",
  "horizontal_angle": "人物正面偏画右约30度",
  "vertical_angle": "略微俯拍",
  "camera_angle_family": "three_quarter_front_right",
  "shot_scale": "medium_close_up",
  "framing": {
    "focus": "本格已有表情与上半身动作",
    "focus_subjects": ["CH-001"],
    "required_visible": ["原脚本要求的表情", "原脚本要求的手部动作"],
    "body_crop": "waist_up",
    "crop_reason": "必要信息完整入画，腿脚与地面不承担本格信息",
    "background_level": "anchor_only",
    "wide_or_full_reason": ""
  },
  "adjacent_change_reason": "基于原脚本说明本格焦点或反应与上一格的实际变化",
  "frame_ratio": "9:16",
  "visible_region": "画面左前景到画面右后景",
  "camera_view_signature": "right-three-quarter / medium close / chest height / slight down",
  "characters_visible": [],
  "background_anchors_visible": [],
  "occlusion_relations": [],
  "locked_script": {
    "dialogue": [],
    "inner_voice": [],
    "narration": [],
    "sfx_text": [],
    "event_text": "原脚本内容原样复制"
  },
  "visual_analysis": {
    "goal": "只分析原脚本已有目标",
    "obstacle": "只分析原脚本已有阻碍",
    "result_or_turn": "只分析原脚本已有结果",
    "external_rhythm": "松|中|紧",
    "internal_rhythm": "轻|中|重",
    "information_function": "ESTABLISH"
  },
  "script_lock_check": "PASS",
  "view_check": "PASS"
}
```

`camera_angle_family`与`shot_scale`可分别保持。相邻检查还核对实际焦点、身体裁切、位置/朝向、可见范围和脚本支持的可见反应；`camera_view_signature`不能只改编号。完全相同且无可观察变化的格对须有实际 `camera_exception_approval`，按 shot-framing.md 记录批准范围与事件哈希。

`locked_script`中的文字和事件字段必须逐字来自源脚本。`visual_analysis`可以解释画面功能，但不能成为新的剧情文本。

新建镜头表与 B 索引根节点都声明 `input_priority_policy: "physical_scene_priority_v1"`。普通格只执行共同约束，不要求填写空的冲突记录。若脚本画面描述与物理或已批准场景冲突，受影响格在镜头表及 B 逐格 JSON/索引保留相同的 `visual_resolution`：

```json
{
  "issue": "准确的原文冲突及受影响格",
  "scene_evidence": "已核对的场景/空间来源或具体物理依据",
  "approved_visual_solution": "获批的具体可见画面方案",
  "approval_evidence": "本格适用的真实批准记录",
  "status": "APPROVED"
}
```

待确认的方案保留在输入审计/镜头候选的冲突与 HOLD 记录，不得作为 `APPROVED` 编译进 B。技术字段完整不证明场景或批准内容真实，仍须实际核对。正式源文不随适配更改。

## 身份与状态确认扩展

输入审计、镜头表和 B 索引同时声明 `identity_policy=identity_confirmation_v1`、`book_id`、`episode_id`，携带同一份 `identity_registry`。逐格保留源称呼 `script_character_labels`，并登记 `character_bindings` 与 `scene_binding`；镜头表登记 `planned_identity_assets`，B 包使用具有资产 ID、版本和哈希的实际 `reference_images`，正文及逐格 JSON 同步 `identity_execution_block`。完整字段、批准范围、真实依据及单次出镜边界见 [identity-confirmation.md](identity-confirmation.md)。人物名称、称呼关系、外观状态和资产绑定分别确认；未知项保持 HOLD，不能用现有文件名或一次出镜豁免补成确定事实。

## 场景账本

场景账本至少包含 `scene_id`、坐标约定、边界、固定锚点、物体尺寸/高度/方向、光源、来源资产和置信度。未知事实使用 `UNKNOWN` 或 `ASSET_HOLD`，不要编造。

## 站位状态

新目录为 `03_站位_CANDIDATE`，空间索引使用 `vertical-comic-spatial-board-v2`，保存 `states`。每格可见内容沿用镜头记录中的 `visible_region`、`characters_visible`、`framing` 和 `occlusion_relations`；`camera_view_id` 仍表示镜头标识。

站位状态至少包含 `state_id`、`scene_id`、`scale_reference`、`people`、`objects`、`anchors`、`camera_views`。人物包含平面坐标、身体朝向、视线朝向和角色自身左右侧连续性；对象包含坐标、尺寸、方向和高度。

站位状态是空间记录，`station_state_id/station_id` 不表示必须存在站位图片。站位图和目标机位灰阶构图参考图在 D 阶段独立按需选择；无需图片时仍保留空间与逐格裁切记录，在已有记录中简述判断依据，不新建重复台账或占位图片。已绘制站位图放 `supporting_documents`；无图不要求该图的路径/哈希，未知空间关系仍 HOLD。条件及示例见 [visual-continuity.md](visual-continuity.md)。

## 提示词包

使用当前工作区的 `vertical-comic-prompt-package-v1` 时，每格至少需要 `panel_id`、`script_shot_id`、`station_id`、`camera_view_id`、`camera_view_signature`、`visible_region`、`view_check`、`prompt`、`negative_prompt`、`reference_images`。参考图条目必须有 `alias`、`path`、`role`、`version`、`sha256`。

新包的每格 `framing` 必须与镜头候选批准版一致。`body_crop` 采用 `waist_up/chest_up/shoulders_up/face_detail/hands_detail/object_detail/full_body/mixed/environment`；`mixed` 时逐人物另写准确裁切。`background_level` 采用 `establishing/anchor_only/minimal`。全身或宽景填写 `wide_or_full_reason`；这些字段的可见结果也要写进实际 prompt.txt，不能只存在于 JSON。

## 第一轮连续性扩展

新镜头表与 B 索引同时声明 `continuity_policy: "reference_continuity_v1"`。逐格 `continuity_contract`、`reference_bindings` 的单一字段规范及迁移边界见 [reference-continuity.md](reference-continuity.md)。B manifest/逐格 JSON 保留批准镜头表内容，另带编译进实际正文的 `reference_usage_block`。参考文件继续使用现有路径/版本/哈希；身份及服装参考的 `reference_images[].subject_ids/subject_states` 标明角色归属和真实状态。旧包缺策略时不视作已通过新增门禁，也不自动补齐。

## 结构控制链路扩展

新 B 索引声明 `control_policy: "structural_guidance_v1"`，登记 `generation_backend` 和每格 `control_inputs`（不使用时显式为 `[]`）。计划、实际请求/响应与图片验收分别记录；字段及能力证据规范见 [control-guidance.md](control-guidance.md)。旧包缺该策略且无控制声明保持 `LEGACY_NOT_ASSESSED`，存在声明不能通过删除策略绕过检查。

## Codex 本地参考输入扩展

镜头表与 B 索引同时声明 `reference_input_policy: "codex_reference_v1"`，B 后端为 `codex_builtin_imagegen/reference_guided`，结构接口和每格 `control_inputs` 均为 `[]`。逐格 `composition_reference` 含 `mode`（CREATE/REUSE/NOT_REQUIRED）、`reason`；CREATE/REUSE 另含实际参考 `alias`、`review_evidence`（包内路径/哈希）。其值在批准镜头表、B 索引和逐格 JSON 保持一致，不另存重复机位字段。

构图选择在 D 阶段完成并写回镜头记录。`NOT_REQUIRED` 的 `reason` 简述现有批准依据为何足够，不需要 alias、review_evidence 或空参考槽；该模式不免除空间验证。站位图是否制作不由 composition_reference 决定，保留在已有空间记录中。

构图核对 JSON 冻结现有 `panel_id/camera_view_id/camera_view_signature/framing/frame_ratio`，记录 `status=REVIEWED/reviewer/evidence/reference_sha256/clean_camera_view=true`。参考图片本身仍放 `reference_images`；实际数组顺序用于图片编号和工具路径顺序。`composition_required=true` 时不可使用 NOT_REQUIRED。

F 阶段 QA 的 `composition_match` 在 CREATE/REUSE 时留空待审，NOT_REQUIRED 时为 `NOT_APPLICABLE`；`composition_review_basis` 标明是参考图片还是批准镜头/空间记录与资产。该项仅表示额外图片对照，`dimension_review.framing` 与机位、裁切、遮挡、接触复核仍按原必审要求执行。

B 逐格另明确 `ratio_tolerance`（有限数字，0≤值<1，为返回图相对比例误差容差）、`transparent_background`（布尔值）。完整参数、审阅边界及执行 JSON 见 [codex-imagegen.md](codex-imagegen.md)；单一字段定义以该文档为准。Codex 使用本地 `attempt_id` 关联可观察调用，不强制不可见的服务端 request_id。旧包不自动激活此策略或被补成批准版。

正文画幅根字段：frame_ratio_policy=content_balanced_ratios_v1、frame_ratio_plan={path,sha256}和source_snapshot，引用相对本话根。全话计划policy/book_id/episode_id/source_snapshot/panel_ids/panels，行字段panel_id/frame_ratio/frame_ratio_reason。镜头与执行格同步ratio/reason，执行格再含frame_ratio_execution_block并写实际prompt。 详见 [全话画幅计划](frame-ratio-plan.md)。

## incremental_runtime_v1 扩展

runtime对象按 [使用配置](usage-configuration.md)；episode_preparation_v1使用根visual_basis/shot_manifest/semantic_audit/gates和generation_packages.EPISODE，全话包scope=episode覆盖完整源格序。approval_index_v1的generation_package批准覆盖真实包、全话基准与镜头。dependency_completion_plan_v1在新模式使用scope=episode并绑定全话依据，只允许获批模板中真实前格路径的准确替换。旧half_scoped_v1的半话包/half_inputs仅按旧RV恢复。诊断repair_routes、返回时间、单写CAS更新按 [增量执行](runtime-efficiency.md)。

## 构图背景处理可选扩展

旧策略可填写framing.background_treatment="clear_limited"；新narrative_background_v1按background-treatment.md逐格选择模式。clear_limited，表示保留的少量背景清晰、简洁，区别于background_level的信息量。特殊已批准景深可选"approved_depth_of_field"，须同时填写非空framing.background_treatment_basis说明具体设计依据。基础framing字段不变；visible_region为具体区域文字，含实际边界、必要动作及背景锚点。

声明扩展后，visual_evidence.framing_execution_block(panel)编译文字必须进入prompt/同版prompt.txt；visual_evidence_v1的visual_execution_block包含它。执行包framing与批准镜头完全一致。旧包无字段则不添加默认值或重签。framing_review_focus仅提示在原dimension_review.framing/background_space记录结果，不新增通过字段。


背景扩展根/逐格声明background_policy=narrative_background_v1，A增加scene_background_profiles，B增加framing.background_plan；完整字段和适用条件只维护在[背景模式](background-treatment.md)。新visibility可用omitted_by_design仅表示批准环境绘制省略，不能用于人物或首饰细节。

## 新整话批次运行字段

以下仅用于显式启用的新RV；旧状态不回填。runtime的snapshot_policy、question_policy、dispatch_policy分别为batch_snapshot_v1、grouped_review_v1、episode_slot_lease_v1。

- state.runtime_snapshot：本批唯一manifest的绝对path与真实sha256；manifest列五件套、实际引用规则正文和逐文件相对path/sha256。state.memory_source指向快照memory并携带同一runtime_snapshot。
- control.dispatch_policy=episode_slot_lease_v1；各job.slot_lease={lease_id,slots,worker_id,epoch}。所有额度总和不超control.max_inflight；job.max_inflight仍为本话上限。control.permits在新策略下为空，原历史保留。
- state.dispatch_ledger：本话唯一写入者维护的请求列表；每项包含原job_id/worker_id/epoch/permit_id/batch_id/round_id/attempt_id/panel_id，加lease_id、status及真实事件。RESERVED/IN_FLIGHT/RESULT_UNKNOWN占槽；COMPLETED绑定真实输出哈希或明确失败证据。RELEASED仅用于确定未提交的预留。
- 新dispatch_receipt保留全部原字段并增加lease_id；原round_context与实际attempt不变。控制只分配容量，本话commit原子推进图片状态和对应请求状态。
- unknown_resolutions按原attempt_id绑定真实查证报告；不新增尝试或自动恢复调用。报告字段与命令见[批次运行](batch-runtime.md)。
- grouped_review_v1 proposal包含book_id、episode_id、items及内容绑定event_id。每项含item_id、phase、准确panel_ids、artifacts、summary；技术处理另列operations和constraints。真实回复明确选中哪些item_id，输出独立普通批准证据，附review_event_id/review_item_id。旧未带phase的真实批准继续按原合同核验。
- 新语义核对checks.framing_feasibility初始UNREVIEWED，expected由当前镜头的裁切/必显信息和机位派生，实际核对后填PASS及具体evidence；自然语言几何不能由技术模板自动判定。
- 仅待最终实图比较的局部hold可显式写scope=panels、dimension=boundary_comparison、comparison_only=true、准确panel_ids及具体evidence。此标记不豁免任何真实设计或输入依赖；新整话生成可继续，但scope_complete/D仍须解决实际比较。


input_quality_policy、scene_views及原checks扩展字段见[实际执行质量与返修分流](execution-quality.md)。复用现有记录和人工停点，不静默升级旧RV。

## 维护扩展：委托决定与局部观察

这些字段用于新安装版本创建的新运行；旧快照不热升级，缺少这些可选局部字段不强制迁移。

真实用户委托记录（示例是结构，不是实际授权）：

```json
{
  "policy":"user_delegation_v1", "status":"AUTHORIZED", "source_kind":"user_message",
  "quote":"实际用户授权原文", "source_locator":"真实消息定位",
  "book_id":"准确书名", "episode_ids":["E001"], "panel_ids":{"E001":["P001"]},
  "phases":["shot_design","generation_package","state_review","final","technical_operations"],
  "constraints":["实际用户要求和不能改变的范围"],
  "operations":["information_preserving_crop"],
  "excluded_panel_ids":{"E001":[]}, "retained_user_phases":[]
}
```

phases使用现有review_policy.PHASES精确枚举，不能填通配符。执行者proof引用authority={path,sha256}，status=AGENT_DECIDED_UNDER_USER_AUTHORITY、source_kind=agent_decision，并带reviewer/evidence、准确phase/panel_ids/artifacts及原样authority_constraints。它不带伪造用户quote，真实原文只留authority。源索引与所有门禁仍校验准确阶段和范围。

追加授权如包含additional_repair阶段，grant还须additional_attempt_ids={话号:{格号:[准确新attempt编号]}}，具体proposal/proof用attempt_ids={格号:[准确新attempt编号]}绑定。只记录明确已授予的次数，不创建或复用旧attempt，不替代执行门禁。technical_operations仍要求operations与constraints。

局部扩展沿原字段：check.inspection_targets=[具体观察目标]；观察view.covered_targets=[实际覆盖目标]，可选source_size=[原宽,原高]/resampled。ref.detail_readability=[{subject_id,detail_id,region,status,observed}]对应图集原像素。repair_focus.structural_change={remove,replace,connect}；repair_source.preservation_regions={名称:[x0,y0,x1,y1]}对应真实底图；repair_comparison.preserved_observations={名称:{status,observed}}。模板不预填PASS，文本与像素范围校验不能替代实际观察。
