# Input audit

新运行优先按[第一批前期提速](preparation-efficiency.md)执行最小充分设计、代表格接线、单次B/包展示及问题分级处理。可选润饰不产生HOLD；真实缺口在现有委托内修复，局部问题只影响真实依赖，其他工作继续。正式输入与接包要求仍按原合同。

### Phase A — script and asset audit

先按[任务来源](task-origin.md)冻结允许输入。fresh从指定源稿提取本批实际需求，再查当前资产及包内适用确认；不主动读取旧成图/QA/调用目录。旧索引路径缺失先判断本次是否使用，未使用缺项不阻塞。正文历史仅核本任务；不能把新任务无旧账写成UNRESOLVED。

For new B packages, read [structural guidance and execution evidence](control-guidance.md) and register the actual generation backend before selecting a control route. Ordinary reference-image upload is `reference_guided`, not proof of ControlNet or another structural interface. Record actual input slots and capability evidence; control models/versions apply only to supported structural backends. For Codex built-in generation, read [codex-imagegen.md](codex-imagegen.md), use `codex_builtin_imagegen/reference_guided` and `reference_input_policy=codex_reference_v1`; no mask, pose/depth control, reference weight, separate negative or size argument is inferred. Unknown capabilities remain HOLD. Use structure controls only when the actual backend supports them, and do not require controls for every panel.

Create an input audit without editing the source script. Register:

- `identity_policy=identity_confirmation_v1`, `book_id`, `episode_id` and the same-book `identity_registry`; resolve every source character label, including offscreen speakers, to a confirmed canonical name/ID and applicable relationship. “傅妈” must identify a specific person and relation target, not a generic mother;
- per-panel character and scene bindings, the episode appearance states, approved asset versions, actual confirmation evidence and unresolved questions; keep all locked script text unchanged. Before A/B/C design, use the identity gate's `--identity-only` check; asset gaps remain `ASSET_HOLD` and can become scoped asset tasks after identity/state confirmation. E-stage delivery and repair must pass the strict asset-binding gate;

- script version and hash;
- panel IDs, text IDs, characters, props, locations, time, action, shot intent, and diegetic text;
- existing asset IDs and versions;
- scene-state changes and character continuity anchors;
- whether a panel can be represented by current assets;
- conflicts, missing information, and approval status.
- for each real script/scene/physics conflict, record the exact source phrase, approved scene or physical evidence, affected panels, whether it is a locked story fact or a camera/presentation suggestion, and the decision needed. Do not silently reclassify an action target or required prop as optional. A missing table or impossible viewpoint is a scoped HOLD until a feasible solution is approved;
- an asset-closure result for the requested production episodes: resolve every required source/asset/prompt reference and recurring state in this batch to approved evidence or an explicit scoped gap. A book-wide closure scan is required when publishing the canonical asset library or when separately requested; unrelated episode gaps do not block this batch.

Do not delete, merge, reorder, or add panels. New episode_preparation_v1 plans every source panel in one episode, including episodes above 32 panels; the old first-version exception belongs only to older package modes. Do not cut a 35-panel episode into two preparation packages.

For reference and continuity planning, read [references/reference-continuity.md](reference-continuity.md). Register current identity/costume states, actual reference capabilities and any supported state changes. Ordinary dialogue does not require an extra pose reference; complex contact may benefit from one compatible with the locked event and crop.


New comic_execution_v2 production freezes one immutable raw source snapshot and derives only the ID mapping using source_adapter.py. Inspect actual source images/selected regions for identity, state and space; do not treat a contact sheet or saved candidate as completed review. In episode_preparation_v1 complete one source-bound semantic_audit_v1 for the whole episode before B, with all six checks in [execution-compatibility.md](execution-compatibility.md). Keep unknowns grouped at the existing A/B checkpoint.

新runtime先一次核对本批完整格序、全部身份/状态需求与输出规格，按话补齐必要资产、全话镜头和全话比例计划，再开始该话整话就绪格生产。缺口逐格记录实际范围；确实未解决的全话准备项须先处理，不能用“后半话以后再做”绕过B。

## 本批集中准备

审计仅覆盖请求话；将真实脚本冲突、缺资产和可行方案集中随A交审，关键未知提前问。开批先检查输出空间并创建唯一运行快照，原图/资产共用只读来源，不逐话全量复制。技术HOLD先诊断，不把路径/版本问题直接变成人工选择题。

## 可移植XLSX读取

源稿为XLSX时可使用`scripts/source_workbook.py --source <本机文件> --output <新原始单元格证据JSON>`。使用已检查的同一Python解释器及openpyxl，不依赖Excel、COM、AppleScript或桌面办公软件。读取保留工作表、单元格坐标、原文、公式及源文件哈希；输出仅为原始证据，不推断话号、格序、身份或批准。执行者随后按本节核对请求范围，并按既有source_adapter建立真实源编号映射。不可把文件存在检查或伪XLSX夹具通过视作源稿已审计。
