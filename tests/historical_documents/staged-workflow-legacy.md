# 固定流程与状态合同：staged_comic_v1

当前新RV使用 [整话异步生产](episode-async.md)：A、B与包、整话生产及D；没有固定半话C。下文H001/H002、C和half_episode_async_v1只供旧半话RV恢复。

当前新任务启用 `episode_preparation_v1`、`panel_readiness_v1`、`episode_async_v1` 与 `incremental_runtime_v2`。按 [全话准备、逐格放行](panel-readiness.md) 在准确就绪范围分别完成B与生图包批准，缺口只阻塞受影响格及真实依赖；整话独立格持续生产、返图即审、滚动返修，最后做整话连续性及D。旧batch5、单格与半话RV按原冻结合同恢复。

## 范围与人工停点

当前全话准备、半话生图任务增加全话生图包构建/完整预检后的人工确认，首次正文或校准调用前须有适用的包批准；第2/3/6/8及包等审消息的第一行显示简短进度。8阶段编号和补齐/复用范围见 [review-progress.md](review-progress.md)。这是Skill的额外提交前核对，原generate技术PASS不授予这项人工批准；本文旧任务表格继续按其原模式解读。

终点是逐格成品图片包，不做长条拼接、气泡、对白/旁白排版、后期特效字或 PSD。剧本要求的画内文字仍属于图片。旧文档的 B 指生图输入，C/排版放行状态只作历史兼容，不触发排版 Skill。

| 阶段 | 输入 | 输出 | 审查 |
|---|---|---|---|
| 输入审计 | 批准剧本、资产索引、记忆和样例 | 源快照、缺口、确认问题 | 仅未知/冲突项需答复 |
| 视觉基准 | 明确身份/状态、实际资产与样例 | 视觉基准、参考职责与适用格 | A：用户确认；同范围既有批准可复用 |
| 镜头空间 | 源快照、视觉基准与空间依据 | 全话镜头表、审阅表、选做辅助图 | B：用户确认镜头与必要新增参考 |
| 正式试产 | 批准镜头、实际参考、当前批次单格包 | 源顺序首五格、逐张 QA 与批次报告 | C：检查通过后并排确认 |
| 批次生产 | 已批样张、授权范围、批次计划 | 每批最多五张独立候选、调用证据与 QA | 新状态首格确认；正常批次不需逐批人工批准 |
| 成品整理 | 全话已检查图片、顺序总览、跨话复核 | 逐格图片包及索引 | D：用户最终确认 |

上表及本段后续首五格说明仅适用于旧任务显式 `execution_mode: batch5_v1`；新任务的权威流程见half-episode.md与review-efficiency.md。旧batch5调度、输入输出及批次合同见 [按话并行与五格批次](batch-parallel.md)。先准备全部镜头和依赖，当前批次内无实图依赖的格可独立并发生成；返回后逐张六项 QA，再检查本批、跨批及适用跨话连续性。整批通过后进入下一批。首五格（不足五格则全部）为 C；遇到依赖或新状态拆批，仍累计首五格，C 未确认不得进入第六格。P001 之后首次出现未确认视觉状态的格，包括试产内，须单格生成/检查并获实图确认后续行。

A/B 可在一次消息中合并审阅，分别保存批准范围；新增未确认资产不能跳过。生产授权与图像验收分开记录，已有整话授权不重复询问。多话由总控协调各话审查，批准一话即可推进该话，不强制等齐全部话。

**旧任务兼容：** 未声明 execution_mode 的 staged_comic_v1 状态沿用原规则：源序首三格（不足三格则全部）作为 C，每格生成并检查通过后进入下一格；第四格前须 C 批准。旧任务不因安装新 Skill 自动切为批次或扩大批准范围。用户明确要求迁移时创建新 RV，保留原批准来源，重新核对当前版本，按目标模式核对真实批准范围、完成对应第一半话图像与审查记录后才能满足新模式 C。历史“按话号逐格、不并发不同格”只适用于旧模式；新模式适用当前批次边界与依赖规则。

## 唯一记录与文件引用

沿用现有剧本、镜头、identity_registry、reference_images/reference_bindings、continuity_contract。episode_preparation_v1在生产流程根字段保存全话visual_basis/shot_manifest/semantic_audit及gates.visual_basis/shot_design；generation_packages.EPISODE绑定一次批准的全话包。H001/H002只在batch_plan、轮次和图片审查中出现；不复制第二份前期准备。旧half_inputs/half_gates只用于原RV兼容。

`00_输入审计/生产流程.json` 根字段：

- `policy: staged_comic_v1`、`book_id`、`episode_id`。当前新任务声明 `execution_mode: half_episode_async_v1`、`preparation_policy: episode_preparation_v1`；旧batch5_v1任务声明其原模式，缺省只兼容旧单格模式。
- `source_script`：本 RV 中只读源剧本副本的文件引用；原始路径保留在输入审计。
- `source_snapshot`：JSON 文件引用，内容为 `source_sha256`、源顺序 `panel_ids`、按格 ID 索引的 `locked_scripts`。原文字段沿用 dialogue/inner_voice/narration/sfx_text/event_text，字符与标点不得改。提取后实际对原稿核对，脚本只能检查后续记录相对该快照一致，不能证明抽取正确。
- `visual_basis`：JSON 文件引用；含 book_id/episode_id、实际 `reference_files`、身份/衣装/场景范围、画风特征与批准依据。另含 `style: {reference_sha256: [实际批准风格样例哈希], traits: {linework, face_proportions, hair, coloring, shading}}`，traits 为实际特征字符串；每格执行副本的风格哈希集合和 traits 必须与此一致。reference_files 是本话批准资产索引；实际生图数组仍只使用每格 reference_images，不重复维护另一套逐格输入。
- `shot_manifest`：获批完整镜头表引用。
- `gates`：visual_basis、shot_design、pilot、final 四项批准对象。
- `production_authorization`：用户生产授权对象，额外包含 `panel_ids`；只允许已授权格。用户原始整话制作请求可作授权证据，不能替代视觉批准。
- `panels`：按源顺序排列；每项为 panel_id、status，以及当前版本 package_manifest/shot_subset/output/qa_report 文件引用。未产生的文件不造假引用。
- `state_reviews`：按新状态首格 ID 索引的批准对象。
- batch5_v1 另有 `batch_plan` 文件引用与 `batch_reviews`（按 batch_id 索引的报告文件引用）；按话并行时附 `parallel_context`，具体字段及跨根目录规则见 [批次合同](batch-parallel.md)。
- `holds`：未解决问题数组；`cancelled`：是否取消本次任务。取消的局部返修记录在当前格状态 CANCELLED，保留原证据，不能改 PENDING 自动重启。

所有文件引用统一为 `{ "path": "相对本话根目录路径", "sha256": "实际SHA256" }`，不能越界。执行包内部的图片、批准、调用证据则相对该包根目录，与旧脚本一致。复制文件后按目的地登记引用，不能混用两种根路径。

全话镜头表每格增加 `visual_state_keys`：稳定、具名的状态键数组，覆盖可见身份、衣装、场景状态和风格版本，例如 `identity:CH01:base-v2`、`costume:CH01:auction-v1`、`scene:SC03:night-v1`、`style:book-v2`。使用本书真实 ID；适用范围由批准裁切决定。不得用每格独有的任意键增加停点，也不得漏记新状态来绕过确认。B 审阅时核对键与人物/场景绑定；程序检查首次出现和批准，不能自动判断图像语义。

## 批准记录

批准对象字段：status=APPROVED、source_kind=user_message、source_locator=真实消息位置、quote=用户原文、book_id、episode_id、artifacts=该批准覆盖的文件引用数组。不得生成假消息或把计划变成批准。复用以前批准时保存原始依据并说明适用范围，不伪装用户刚说了话。脚本检查记录一致性，不能认证批准来源真实。

- A 覆盖 source_script、source_snapshot、visual_basis。
- B 覆盖 visual_basis、shot_manifest。
- C 覆盖 visual_basis、shot_manifest 和当前第一半话全部outputs；旧batch5_v1为首五格（不足则全部），旧单格模式为首三格。旧首三/五格批准不自动扩成新半话C。
- 新状态首格批准覆盖 visual_basis、shot_manifest、该格 output。
- D 覆盖 visual_basis、shot_manifest、全部 output。同一并行 control.jobs 超过一话时，另须整个并行批次的跨话报告有效才可交付；报告不代替各话 D，不额外阻塞生成。
- 生产授权覆盖 source_script，并明确 panel_ids。

凡新增参考/构图图都核对后纳入基准。批准依赖变更，相关批准先失效；有可复用的既有明确批准时，只以真实证据重建当前范围，不能静默改哈希。依赖变更后的影响分析保留在修订记录，避免要求用户重审无变化内容。

## 逐格状态与实际执行

`PENDING → GENERATED → VISUAL_PASS → USER_ACCEPTED`；失败进入 HOLD，取消进入 CANCELLED。返修经诊断并在既有授权内可设 REPAIR_AUTHORIZED；已明确取消的任务须用户恢复后才可进入该状态。VISUAL_PASS 是实际看图后的六项判断，不是校验器输出；USER_ACCEPTED 还需对应用户证据。

先做全话镜头和全话生图包；生图时从获批全话镜头与生图包选取当前格的单格镜头快照与执行包，保留源格号，不能把 P014 改成 P001。单格包声明 workflow_policy=staged_comic_v1、style_policy=approved_style_v1，并保留原身份/连续性/后端合同。全话包总览在B阶段一次准备；启用readiness时待补格差异另存新版本集中补审，原批准包保留；有实图依赖的格只按批准补齐方案替换真实前格路径，实际提交前仍完整预检。

每次尝试为新版本目录，调用前冻结输入；调用后补充实际 execution 证据，再冻结供 QA 使用的 manifest。QA 对应这个确定版本。改变 prompt 或引用后旧 execution 恢复 NOT_RUN，旧记录进历史；旧图片要复用需重新核对其适用性和真实原调用，不虚构为新 prompt 的输出。

使用：

```text
python <总控>/scripts/staged_workflow.py --state <本话>/00_输入审计/生产流程.json --check status
python <总控>/scripts/staged_workflow.py --state <本话>/00_输入审计/生产流程.json --check generate --panel P001
python <总控>/scripts/staged_workflow.py --state <本话>/00_输入审计/生产流程.json --check deliver
```

脚本只读，不代替人工判断、不自动写批准、不自动推进。返回 next_action 指明停点；generate 模式另调用完整单格前期门禁，核对来自源格序的准确选集。旧 Gate 默认完整话的连续编号规则保持；不能为选集重新编号。状态检查 HOLD 可能代表正常等审，不意味着程序故障。

旧模式要求当前格之前的验收快照仍有效。batch5_v1 要求全部前批次验收有效；当前批次的独立格可先返回后集中检查，明确依赖格仍等待前置实图 QA。全话镜头包含相邻比较；批次审查必须覆盖批内与上一批衔接，适用相邻格和原批准样例不可省。试产总览保留源序并排图与用户证据。

## 返修与交接

先诊断最早失败层，记录受影响格、保留内容、目标和尝试数。同一问题一次针对性修复仍失败就停下诊断，不无限抽图；工具无图返回不能被记为已生成。每次返修重新检查全部六项。不要把本话一次反馈扩为全书规则，除非用户明确要求。

总控读规则和状态；执行 Skill 只读本阶段资料。切换 Skill 不保证上下文自动清空，效率来自按需读取和确定记录。新会话仍须读取必要规则和实际视觉证据；旧“看过”回执不能代替本次所需目视核对。

## 规则记忆与可配置批次补充

第三来源与按阶段命中读取见 [规则记忆合同](rule-memory.md)，路径、子 agent 数和请求额度见 [使用配置](usage-configuration.md)。启用记忆的新任务在生产流程、批准镜头、冻结执行包绑定一致 memory_source；镜头 memory_tags 冻结传递，生成与图片验收分别留执行记录，不能删除来源绕过。实际人体在床上等命中条件要求适用站位图及实际提示词约束，未核对则 MEMORY_HOLD。

仅旧batch5_v1使用batch_size默认5，可配置1–5；文内“五格批次”指最多五格，批次计划 max_batch_size 取实际配置。首五格 C 范围保持不变；独立图片质量、依赖、新状态、批内/跨批及跨话检查不因调小批次或增减 agent 而省略。修改配置不会自动覆盖已有 RV 的冻结状态。
