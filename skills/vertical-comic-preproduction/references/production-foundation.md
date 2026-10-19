# Shared production invariants

## Absolute script lock

The source script is immutable in content. “完善脚本” in this skill means improving only what can be shown in the image. The skill may clarify or adapt visual presentation, but it must never change:

- panel count, panel order, or the event in a panel;
- dialogue, inner voice, narration, caption, SFX wording, or punctuation;
- who says a line, who owns an inner voice, or the intended read order;
- character relationships, story facts, causal results, time, place, or required props;
- a required action into a different action, or a required reaction into a different reaction.

If a visual solution appears to require changing any of these, keep the original field, create a `SCRIPT_CONFLICT` entry, and stop for user approval. Never silently “improve” the writing. The output must preserve both the locked script text and a separate visual-adaptation layer.

## 生图输入的冲突处理优先级

新建生产包声明 `input_priority_policy: physical_scene_priority_v1`。优先级用于发现冲突后决定先调整哪一类画面表现，不授权牺牲任何硬要求。执行顺序：

1. 人体关节、重心、支撑、接触、透视、遮挡等物理可行性。
2. 已批准场景的真实布局：门窗、墙体、家具、固定物件的存在、数量、形状和世界位置。镜头变化只改变屏幕投影；剧情明确且有依据的移动按状态变化处理。
3. 人物与剧情硬要求：身份、当前衣装、指定表情、动作、作用对象、结果、必需道具和原文字。
4. 本书已批准画风与实际样例。
5. 可调整的机位、景别、裁切、可见范围和非关键画面位置。
6. 美观、完整展示及未获批的戏剧化强化。

前四项均必须同时满足。批准场景参考负责空间，人物/衣装参考负责各自状态，批准画风样例负责风格；构图辅助图与真实前格只在各自获批范围提供画面或连续性依据。脚本中的镜头描述可按获批镜头适配；原脚本中提及家具、动作对象或人物状态时，先判断是否属于剧情事实，不能因“可能写错”就擅自降为可变描写。比如脚本明确要求把合同放到桌上而批准场景没有桌子，保留原文并让受影响格 `SCRIPT_CONFLICT`/`VISUAL_CONFLICT_HOLD`，集中确认处理方式；不得自动改成放到沙发上。没有桌子时也不能凭一句“桌旁”直接生出桌子。

没有冲突的格沿用现有镜头和 QA；有冲突的格在原镜头记录的 `visual_resolution` 登记原问题、场景依据、已批准画面方案与批准证据。原文、资产和镜头记录分别保留，不建第二套权威脚本。未批准的冲突不得编译成看似确定的生图指令；仅暂停受影响格和真实依赖格。新合同不回填旧 RV，也不使旧批准自动失效。具体物理/空间/遮挡检查使用当前实际命中的 MEM 正文，见 [规则归属](rule-ownership.md)。

## Core operating principles

1. Treat the approved script, approved assets, and user-approved samples as read-only evidence. Never overwrite them. Candidate adaptations go into a new RV directory.
2. Separate `story facts`, `camera adaptation`, `asset invention`, `spatial inference`, and `prompt wording`. Never hide a change of story fact inside camera design.
3. The script may be adapted only in camera position, height, facing direction, angle, shot scale, crop, visible region, and the visual presentation of an already-specified action or reaction. Dialogue, inner voice, narration, captions, SFX wording, event order, character identity, and key continuity facts are locked.
4. A camera change is not valid merely because the label changed from “side” to “oblique side.” Validate the actual camera signature and the actual visible face, body, background, scale, and occlusion.
5. Choose adjacent shots within the locked beat and apply the current rule library's applicable camera/scale requirements. Use the batch-frozen MEM-010 version: v2 permits justified same-scale dialogue coverage and prioritizes physical continuity; frozen v1 runs retain their original dual-change requirement. Compare observable composition rather than renamed signatures, preserve physical space and required crop, and record a conflict when the locked beat cannot satisfy the applicable rule. See [rule ownership](rule-ownership.md).
6. The correct image is the view from the camera position in the real space. Do not repair an impossible view by moving doors, windows, furniture, vehicles, trees, props, or people to make them convenient.
7. Occlusion follows the physical world. Do not remove a table, door frame, hand, foreground person, or prop merely to show a complete body or item.
8. Do not use long theory lectures in B prompts. Keep the detailed reasoning in the shot and spatial records; write the final prompt as a short, literal description of what is visible and where it is in the overall frame.
9. If an asset, spatial fact, camera authority, or image-generation tool is missing, stop at the appropriate HOLD. Do not fill a gap with a plausible guess and call it continuity.
10. This is a local workflow constraint, not model training. Each run must read the batch-frozen applicable rules and actual visual evidence; installation updates do not upgrade an active batch.
11. A camera field stored only in JSON is not an executable camera instruction. The same camera angle, shot scale, frame ratio, camera position, facing direction, and visible-face logic must be written into the actual per-panel `prompt.txt` and must be checked literally before delivery.
12. Separate `PACKAGE_READY_FOR_B` from `PANEL_PACKAGE_ACCEPTED`. A package may be ready before any final image exists; returned-image QA blocks final panel delivery, not initial generation. Structural PASS is never user approval or proof of image quality.
13. One-off characters, scenes and props do NOT require independent asset sheets (user requirement 2026-09-29). Count actual visible occurrences by canonical identity within the available book scripts, not file mentions or dialogue names. A single-scene multi-panel sequence is recurring, not one-off. Record the evidence scope and panel IDs; do not invent future occurrences. Describe a one-off object's actual visible design, placement, scale and occlusion directly in the prompt. Reuse available appropriate references when useful; do not make redundant asset-generation tasks.
14. In repairs, reconcile later scoped user approvals before importing historical HOLDs. Relative spatial coordinates are valid; absence of absolute XYZ is not a blocker by itself. Neither a new filename nor copying an approval to another scope can authorize a camera or asset.
15. A scoped approval of a character/scene asset or a relative camera idea does not resolve a spatial HOLD. `ID_RESERVED_ONLY_NOT_A_STATION_MAP`, null camera coordinates, `HOLD_NOT_YET_SPATIALLY_PROVEN`, `CAMERA_HOLD`, or `downstream_status=CAMERA_HOLD` must survive rebuilding and block `READY_FOR_B_GENERATION_PENDING_IMAGE_QA` until scene evidence, actual blocking and the approved camera/crop establish the view. Do not require a new diagram for every panel by default; if a clean camera-view reference is needed for a particular Codex panel, record that requirement and keep it HOLD until available and reviewed.
16. Never append a generic face-direction sentence to every character. A panel that says “只露双手”“脸在画外”“背对观众” must not also contain “露出正脸”; each character needs an explicit screen position and actual visible-face rule. Generic “按上述人物屏幕位置” is a prompt defect, not a harmless shorthand.
21. Before declaring a book asset inventory complete or building a new comprehensive asset package, run a book-wide asset-closure scan. Reconcile every episode's `04_逐话生产`, `98_记忆更新`, input audits, `USER-ASSET-REF`/`主参考资产审计` events, prompt-package reference manifests, and user-provided local attachments against the current book canonical asset index. A user asset recorded only in an episode package is not book-level complete. Any independently recurring space or state found by the scan but absent from the canonical package must be recorded as `ASSET_GAP` and must not be silently replaced by a mother scene, similar room, or old candidate.
22. Frame the smallest region that preserves this panel's required information. Dialogue usually uses medium/medium-close, half-body framing or a relevant detail. Full-body coverage and environment-wide coverage each need a beat-specific reason. Keep the complete scene ledger while simplifying the visible frame. Read [information-first framing](shot-framing.md) for crop decisions and the review contract.

23. Visual style is a hard generation and returned-image acceptance constraint. Use the current book's approved character boards and approved comic samples as the style authority, inspect them, and write their concrete linework, face-proportion, coloring and shading traits into the actual prompt. Composition, scene, prop and previously failed image references must not override that authority. For an approved 2D anime book, photorealistic, semi-realistic CG or 3D rendering is `IMAGE_STYLE_HOLD`, even when identity, action and crop pass. Do not impose one book's anime style on a book with a different approved style.
24. Preserve source panel identity and order. New tasks use episode_async_v1 with scoped_episode_review_v1, episode_preparation_v1 and incremental_runtime_v2: one EPISODE scope, approved independent requests continuously dispatched, on-return six-part visual QA, content-bound reuse of unchanged QA and one automatic correction round. There is no fixed half-episode C gate. Only real input-image dependencies block generation; actual neighboring/cross-episode comparisons must finish before final acceptance. High-risk/user_required images retain real human confirmation; ordinary states may merge into D only as approved in B. Local holds affect only their true scope/dependencies. Read [episode-async.md](episode-async.md), [batch-runtime.md](batch-runtime.md) and [grouped-review.md](grouped-review.md). Legacy RVs retain their frozen mode and evidence; read legacy references only when restoring them.

## Required startup route

Before identity/asset decisions, read [identity, appearance and scene confirmation](identity-confirmation.md). Resolve source labels to canonical character IDs and confirmed names/relationships, then bind the episode's approved appearance and scene states. Preserve source labels in the locked script; never invent a full name for an unnamed character.

Perform startup once per active run/version; within the same run reuse actually read, unchanged rules and inspected evidence across stage switches. Recheck changed dependencies and inspect the actual references needed by the current generation/review. A new session must reload required rules and visual evidence. Before doing production work, locate the workspace root by finding the applicable `AGENTS.md`. For configuration-driven new tasks, first read the configured script, applicable asset evidence and batch-frozen rule index/bodies; do not require unrelated historical workspace paths. The following historical workspace route applies only if restoring a legacy task that actually declares it:

1. root `AGENTS.md`;
2. `00_排版电脑生产工作区_RV_v003_20260922/AGENTS.md`;
3. `00_先读/00_入口.md`;
4. `00_先读/00_记忆库入口.md`;
5. `00_先读/01_记忆读取与回写执行规则.md`;
6. `01_通用标准/排版电脑统一基线_RV_v003.md`;
7. `02_可复用经验/原始证据索引_A_B_RV_v003.md`;
8. current published workspace rules, applicable event files, and actual approved A《示例作品A》/B《示例作品B》 samples;
9. the current book's project entry, current book rules, visual card, character/prop/scene asset index, continuity records, canonical name/alias/relationship table and scoped identity/state acceptance evidence;
10. the current episode's script, input audit, station/scene records if any, and scoped production records (legacy episode memory). These facts remain episode-local and must never be copied into the portable rule library.
11. for asset work, the current book's `03_资产/全面资产包_*/00_全面资产包入口.md`, its metadata index, and the latest book-wide asset-closure scan report. If the scan report is absent or older than the latest episode asset-reference event, stop at `ASSET_AUDIT_HOLD` and rebuild the scan before making a package or claiming no gap.

Do not infer that a directory or filename is approved. Report the project, episode, current phase, script and asset versions, approval basis, loaded memory IDs, sample files actually opened, unresolved items, and the current stop point before production.

If a memory receipt is required by the workspace, run the workspace `memory_gate.py snapshot`, read the actual files and samples, write the receipt, and run its check. A receipt that only lists paths is not proof that images were inspected.

## Modes and mandatory stops

At every phase, an unresolved identity, appearance or scene-state question is a mandatory stop: record `IDENTITY_HOLD`, `APPEARANCE_HOLD` or `SCENE_IDENTITY_HOLD`, show the source wording/evidence/conflict, affected panels and the exact decision needed, then ask the user. First reuse applicable existing confirmation; do not ask again when the accepted scope/state is unchanged. While waiting, only read evidence and organize questions; do not design, generate assets or produce B-facing prompts that depend on the uncertainty. Silence, confidence, a plausible interpretation, file names and authorization to produce are not identity/state confirmation. A one-off asset exemption does not waive this gate.

Default mode is `CANDIDATE`. Follow `staged-workflow.md`; stage names A–F below are legacy production labels, not permission to skip human checkpoints.


## Portable rule source

At the first active run, read [rule ownership and one observation](rule-ownership.md). Fixed contracts and base six-part QA always execute; portable rule bodies provide conditional additional criteria. Do not maintain a second set of camera/visual criteria in the Skill text or let a technical PASS waive matched rules.

The additional memory_root is separate from mandatory workspace instructions and scoped evidence above. Read only its lightweight index at startup; route stage/visual triggers before loading rule bodies, per [rule-memory.md](rule-memory.md). Do not traverse the entire rule library for every panel. Explicit current user intent, locked script and approved assets govern conflicts. Do not turn episode-specific facts or QA failures into shared rules automatically. [usage-configuration.md](usage-configuration.md) defines the three inputs and independent worker/request/batch limits.

正文逐格恢复content_balanced_ratios_v1：六种允许画幅按内容选择；竖版格数严格大于全话3/4；组内数量均衡、相邻交错、方/横分散。比例计划在B一次冻结，两半与返修共用，D核实际像素。 详见 [全话画幅计划](frame-ratio-plan.md)。


启用narrative_background_v1时，[批准背景简化](background-treatment.md)只改变绘制信息量，固定实体的存在/位置、支撑接触、遮挡及剧情事实仍遵守本合同。不能用物理约束要求每格绘出整个场景，也不能用留白删除必要结构。
