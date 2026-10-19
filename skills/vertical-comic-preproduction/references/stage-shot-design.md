# Shot and spatial design

启用readiness_policy=panel_readiness_v1时优先按 [全话准备、逐格放行](panel-readiness.md)：全话总览保持完整，就绪设计和完整输入按准确范围集中交B及包审，缺口列待补；当前整话获批独立格可先生成。前格设计未定及真实图片依赖继续等待，D仍须完整；旧半话RV保留原C。本文全话准备一次不要求无关缺口清零；未声明该策略的旧RV继续原完整准备门禁。

`episode_preparation_v1` 在B一次完成整话镜头、空间连续性、比例及实图依赖规划，根shot_manifest须准确覆盖全话源格序。当前EPISODE只用它选出就绪格，不另设半话C；真实新增或依据修订只回准确影响范围。旧RV按原H001/H002合同。

### Phase B — shot adaptation candidate

Read [references/shot-framing.md](shot-framing.md). Identify the visual focus and required visible information before selecting the camera and shot scale. A two-person conversation may focus on one speaker, the listener, a justified over-shoulder view, or two cropped figures. Required simultaneous reactions, contact points, props and diegetic text must remain visible. Characters merely present in the scene need not all enter every frame.

Carry confirmed `character_bindings`, `scene_binding` and `identity_registry` into the shot records. Selecting a camera cannot resolve an uncertain name, face, wardrobe or place. Reopen the relevant confirmation if the design requires an unconfirmed appearance feature or state.

For `physical_scene_priority_v1`, derive each view from the approved room and current station state: fixed geometry and real support/contact → the specified character action and expression → a camera that can actually see the required information → crop. A script's shot description is a candidate view, not authority to add furniture or bend a body. Preserve a hard action target and outcome; if no physically possible view satisfies them, hold only the affected panel/dependencies for a scoped decision. Record any approved conflict solution in this panel's `visual_resolution`, rather than altering `locked_script`.

For every panel, create a `shot_design` record with at least:

- `panel_id`, `script_shot_id`, `scene_id`, `station_state_id`;
- camera position in scene coordinates, camera height, facing direction, horizontal angle, vertical angle, and lens/field-of-view description;
- `camera_angle_family`, `shot_scale`, `frame_ratio`, `visible_region`;
- `framing`: focal subjects, required visible information, explicit body crop, crop rationale, background detail level, and a reason when full-body or environment-wide coverage is necessary;
- `adjacent_change_reason` when retaining an adjacent angle or scale; explain the existing beat, not an invented gesture or emotion;
- characters visible, body orientation, head orientation, gaze, expression, action, and depth order;
- background anchors visible and their screen positions;
- fixed props, signature traits, injuries, costume marks, and their character-relative side;
- occlusion and contact relations;
- why this shot serves the beat;
- the locked script beat: `goal`, `obstacle`, `result_or_turn`, and `new_information` as an analysis of the existing script, not new story text;
- previous-panel and next-panel difference checks.
- when a visual/source conflict exists: `visual_resolution` with `issue`, `scene_evidence`, `approved_visual_solution`, `approval_evidence`, `status=APPROVED`; unresolved candidates stay HOLD outside a B-ready package. Ordinary panels need no duplicate empty record.

Use real visual language: `画面左`, `画面中央`, `画面右`, `画面上部`, `画面下部`, `前景`, `中景`, `后景`, `面对观众`, `背对观众`, `露出大部分后脑勺和少量面部`, and so on. Do not use only “角色左边/right side” or “自由机位.”

The adapter must check adjacent camera signature, angle, scale, height, direction, and visible region together. It must also check:

- allow justified same-scale dialogue coverage; verify an actual change in subject, view, crop or script-supported visible beat. Mechanical repetition and signature-only changes remain HOLD unless that exact pair has explicit repeat approval;
- a reverse shot shows the physically correct back of head/face exposure;
- the background behind a person follows the camera's real position;
- the same person does not repeat the exact body state and micro-expression in adjacent panels without a script reason;
- every visible prop has a stable scene coordinate and plausible occlusion.

Use the useful part of the existing screenwriting skill without importing its rewriting authority:

- Translate each existing beat into visible action: goal → obstacle → visible result/turn. If the script gives no visual evidence, mark `VISUAL_HOLD` rather than inventing psychology or exposition.
- Use “show, do not tell” as a camera test: prefer a visible gesture, pause, prop interaction, gaze, posture, or spatial relation already supported by the script. Do not add an unstated thought or motivation.
- Track two independent rhythms per beat: external event intensity and internal emotional intensity. Use their contrast to select scale, camera distance, negative space, reaction detail, or a transitional view; do not rewrite the beat to force a rhythm.
- Mark each panel's information function: establish, orient, reveal, react, escalate, contrast, breathe, or hook. This changes shot emphasis only; it cannot add or remove plot information.
- Protect opening and ending visual functions. The first panel may clarify an existing hook; the last panel may emphasize an existing turn or question. Neither may invent a new hook or cliffhanger.
- Track character physical state, emotional presentation, known information, active clues, and continuity anchors across panels. Update the record when the script changes them; do not manufacture a change just to make a shot different.

Output `A_镜头改编_CANDIDATE` with the original-to-adapted comparison, explicit crop/required-visible records, full-body/wide-shot reasons and a HOLD list. Flag spatial questions that Phase D must resolve; decide and produce optional station maps and composition references during Phase D, rather than generating them for every shot here. Use available spatial evidence; uncertain geometry stays visibly CANDIDATE and cannot be presented as proved. Stop for user confirmation before locking any new camera that affects downstream assets.


### Phase D — spatial validation and optional spatial aids

Validate each panel's people, objects and camera positions/orientations, occlusion, contact and actual visible crop. Keep the findings in the existing spatial and shot records. Station maps and **目标机位灰阶构图参考图** (also called 灰阶分镜构图稿) are both optional and are generated here only when useful. Read [visual-continuity.md](visual-continuity.md) for the independent selection criteria and visual examples. First use sufficient approved evidence, then reuse matching aids, then create only the aid needed to resolve a concrete question. A small interior, crowd or new camera is a reason to inspect, not an automatic requirement to draw either or both aids. Unknown spatial relationships remain HOLD; absence of an unused optional image alone does not create HOLD.

Create one station state whenever a person changes position. Create a new state when a materially different body orientation, gaze relation, or blocking arrangement changes what the camera sees, even if the feet did not move.

Use the confirmed character/scene IDs and states in station maps and shot records. Any changed or uncertain binding invalidates dependent spatial records and prompts until the appropriate confirmation is restored.

When a station map is needed, use a simple vector top-down plan whose proportions follow the scene ledger. It shows:

- circles and labels for people;
- rectangles for objects with name, size, and location;
- triangles or markers for doors, windows, and background anchors;
- solid arrows for body direction;
- dashed arrows for gaze direction;
- camera position, height, facing direction, field of view, and visible wedge;
- state ID, scene ID, scale and legend.

Record the visible front/back/side of each person, screen left/center/right placement, foreground/midground/background order, visible object positions and occlusion/contact relationships directly in the existing shot JSON. Compile those facts into the actual B prompt. When a target-camera grayscale composition reference is useful, show the approved crop, facing, contact points, perspective and occlusion at the intended ratio, using blank facial features and only enough grayscale detail to judge the view. Keep annotations and arrows in review materials; formal identity, clothing, expression and gaze come from the approved assets/script/records. Do not make a text/JSON screenshot or treat a top-down plan as the camera view. For Codex, finalize CREATE/REUSE/NOT_REQUIRED in the existing shot record following [codex-imagegen.md](codex-imagegen.md); CREATE/REUSE needs the actual reference alias and spatial/view review evidence. The image alone does not resolve a spatial HOLD.

The spatial state retains all scene occupants and fixed objects, including when no map is drawn; a map, when used, reflects that state. The shot record and prompt describe only the chosen crop: visible characters, visible body regions, required props/text and necessary background anchors. Record offscreen occupants separately for continuity. Cropping must preserve required contact and simultaneous reactions. Keep the approved ratio and framing in the existing per-panel record. Reuse existing confirmations in their accepted scope; optional aids do not introduce an additional confirmation stop for every panel.

Bind each visible character ID to its own reference owner and actual screen region. Separate identity, costume, pose/contact, scene view and framing purposes; a retrieved pose cannot import its person's face, clothes or background. Keep the contract's `required_visible` identical to approved framing, and keep offscreen entities out of positive image content. These text records do not imply that region masks or model-level controls were executed.

Keep annotated station maps separate from model-facing `control_inputs`. A control image must use its backend's pose/edge/depth encoding, match the approved camera/crop and actual generation size, and carry preprocessing, model, strength and view-review evidence. Do not feed a labeled top-down station map as a target-camera depth map or infer structural control merely from uploading it. Apply the contract in [control-guidance.md](control-guidance.md); a control-file check cannot establish physical visibility or image quality.

Render station plans with vector symbols and labels when useful. Review actual visibility using scene evidence, camera position and the recorded crop; a diagram alone does not prove the view.


v2镜头使用准确源格映射与真实前格上下文；逐人动作、画面坐标、接触承托、必显信息和裁切一次核对齐。相邻与脸部可比标签由实际上下文派生。源稿/通用规则冲突保留原文，绑定实际用户的本次例外与替代判据。 详细字段、命令和恢复规则见 [生产兼容与提速](execution-compatibility.md)。

道具需要放置/承托时，绑定具体已有家具或原图选区；不能为了展示内容新增桌子、扩大桌面或移动通道。实际打开将随调用传入的场景参考，核对目标空间及必需结构覆盖，地点名称一致不证明几何适用。复杂空间仍易漂移的格，可在同一镜头记录选择 [先空景、后人物](background-first.md)，先明确双方共用的真实布局、机位和裁切；普通格继续直接生成，不为路线扩大源稿/批准取景。

B冻结前使用semantic_template生成准确rule_triggers命中版本清单，逐格核对覆盖和人体适用性，保存到根semantic_audit的全话语义核对，不另设人工停点。结构可证明的对象/相邻关系由rule_tags派生；人体/床/镜面等真实语义仍由执行者核对，不用关键词代替。 归属与正式来源见 [rule-ownership.md](rule-ownership.md)。

B冻结前按源稿完成全话frame_ratio_plan，每格frame_ratio/frame_ratio_reason依内容填写，显示比例序列及数量统计。全话计划是比例小表，与全话必要资产和镜头一起在B前完成。 详见 [全话画幅计划](frame-ratio-plan.md)。

新RV镜头执行 [具体视觉证据](visual-evidence.md)：同场景最近前序格跨切场关联，人物移动/离场有准确变化依据，画面左右变化不改世界座位；多人接触逐肢体说明。只生成必要辅助图，不逐格重复。


B按[背景模式](background-treatment.md)选择主背景模式并冻结framing.background_plan；审阅表在原逐格记录展示模式、保留/省略及理由，不新增人工停点。


B阶段具体可实现性与方向核对见[实际执行质量与返修分流](execution-quality.md)。复用现有记录和人工停点，不静默升级旧RV。

## 在B解决动作可实现性

framing_feasibility沿用原semantic_audit：实际核对裁切是否容得下必显动作、当前方向是否可读所属肢体与接触点、承托及反射是否成立、参考是否含相反状态。检查器验证当前expected绑定，不证明几何正确。简单手势不强制复杂接触字段；多人接触读不清先修镜头或选必要辅助图，不能只在prompt重复“严格正确”。

关键局部易漏检时，在原check增加inspection_targets具体列所属前臂/腕、接触点/对象或清晰度目标。它用于返图观察覆盖，不是模型级区域控制或新增审批点。普通格不为凑字段加框。
