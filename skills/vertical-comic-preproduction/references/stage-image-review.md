# Image review and repair

新运行统一按[第一批生产决定](production-decisions.md)衔接审核、返修与交付：真实FAIL不改写，处理动作与交付结论分别记录；旧冻结合同不迁移。下文审核方法、源稿/批准/证据要求仍适用。

当前新RV使用 [整话异步生产](episode-async.md) 和 [异步工具执行](async-generation.md)：每张真实返图立即审六项与适用规则，真实失败格可滚动返修，整话连续性及适用跨话实图比较完成后交D。高风险新状态仍单独确认。下文H001/H002、C与runtime_v1步骤只适用于原冻结旧RV。

> 阶段化五件套执行时，同时遵守 [固定流程](staged-workflow.md) 和 [生图输入输出合同](generation-io.md)。每次生成及返修必须实际传入批准画风样例，单独审查画风；最终交付逐格图片包，旧“进入排版/C阶段”只作历史术语，不启动排版。单格原编号快照由 staged_workflow.py 调用完整门禁校验，不能为通过旧完整话编号检查重编号。


### Phase F — returned-image gate

For `physical_scene_priority_v1`, begin the same observation with the real physical and scene facts: body support/contact and believable perspective/occlusion; then check existing fixed objects against the approved scene in world space, followed by person/wardrobe/expression/action/target/outcome and style. Fill the existing dimension, style and applicable memory judgments separately; the `priority_review_focus` in the QA packet is a viewing aid, never an automatic PASS or extra review gate. A camera change may alter screen position and visibility, but not the room's true layout. Compare any `visual_resolution` against its exact approved scope. Fail the relevant original QA dimension when a new table, moved sofa, impossible pose, missing required action or style drift appears.

When B returns generated images, create a separate image-QA record before final panel delivery. At minimum check:

- actual character identity, appearance state and scene identity/state against the corresponding confirmed reference; inspect first appearances, new outfits/injuries and characters returning after a scene cut. Wrong identity/state is `IMAGE_CONTINUITY_HOLD`, not permission to alter the source asset;

- actual pixel ratio against the per-panel `frame_ratio`;
- adjacent angle family and physical camera position;
- adjacent shot scale and visible subject extent;
- background anchors and reverse-shot face exposure;
- action, expression, occlusion and fixed props;
- whether the image tool silently returned a repeated default scene view.

For batch5_v1, review the first five source panels (or all panels if fewer) side by side for gate C; legacy single-panel mode retains the first-three requirement. Each production batch also needs per-image QA and a frozen batch continuity report, including the previous batch boundary. See [execution-compatibility.md](execution-compatibility.md). Judge the returned images against the approved focal subjects, body crops and visible beats. Same-scale shot/reverse-shot is valid; an unintended repeated default view or an unapproved unchanged composition is `IMAGE_CAMERA_HOLD`. Also check that the generator did not expand a half-body/detail into full-body or wide coverage, add offscreen characters, or omit required action/props/text. 第一批交接按production-decisions.md保留真实FAIL并标明人工后修/人工优先处理；不得将这些图描述为全部审核通过。 For Codex, record a delivery-specific `ratio_tolerance`. If Phase D selected CREATE/REUSE, compare the returned image against the reviewed composition, especially hands/contact, occlusion and background projection. For NOT_REQUIRED, review against the approved shot/spatial records and relevant assets; only the extra image-to-image comparison is NOT_APPLICABLE, while framing and spatial QA remain required. Use `scripts/make_generation_qa.py` to create the ratio/error report, selected composition/returned-image comparisons, adjacent-pair checklist, and review contact sheet. That script cannot replace human visual judgment; it makes the missing judgment visible and auditable.

If a recurring character changes face, hair, fixed marks or wardrobe without a script-supported state change, mark `IMAGE_CONTINUITY_HOLD` and stop. A text prompt cannot guarantee a stable 3D room; recurring-space production requires an approved scene plate or a generation tool with image/structure control. If the B tool is text-only, use it for concept candidates only and do not call the output continuity-safe.

Use the five-dimension review in [references/reference-continuity.md](reference-continuity.md): identity, costume, action/interaction, background space and framing. Applicability is decided from the approved crop before generation; never waive a missing required prop/contact after seeing the result. Same-scene camera changes are reviewed against spatial geometry, not identical background pixels. `make_generation_qa.py` leaves required reviews unfilled. `continuity_contract.py --qa-report` checks recorded evidence and frozen hashes only; it cannot grant image approval or release to the final panel package.


## Feedback and memory

Every user correction is first written as the user's original feedback with scope and affected phase. After a revision, save before/after versions, changed and unchanged areas, actual QA evidence, and unresolved issues. Keep episode-only facts separate from book rules and cross-book methods. Only explicit user acceptance may upgrade a candidate to locked/book-confirmed/global-published status.

When a user says the result is wrong, diagnose which layer failed:

- source/script interpretation;
- camera adaptation;
- scene ledger or nine-grid;
- station map;
- per-panel spatial and crop records;
- asset reference selection;
- prompt wording;
- external image generation.

Do not repair a layer-3 spatial error by adding vague wording to layer 4. Correct the earliest failed layer and invalidate downstream records that depend on it.


v2验收核对真实前格相邻关系、实际可比较脸部、适用规则与原范围例外替代判据；技术PASS不代替人物动作/承托/视域等语义实图核对。已审未变图复用，修正图完整重审；本话临时检查器不能替代当前共享合同。 详细字段、命令和恢复规则见 [生产兼容与提速](execution-compatibility.md)。

道具出现不抵消背景错误：凭空家具、拉长桌面、移位座椅、堵住走道均判背景空间失败。选择 [先空景、后人物](background-first.md) 时，保存两阶段原图并对照未遮挡锚点，允许的接触阴影/人物遮挡不能扩大为家具结构变化。原失败图即使曾被模型标PASS，用户指出的空间错误也要在实验记录中保留；不回写旧QA或把旧失败图当作当前正确底图。控制变量比较使用同一评价标准并计入全部阶段耗时。

实际返回图的inspection_plan把基础六项和命中专项判据按观察对象组织；一次打开原图、批准参考及真实前格，逐项写入原style_review/dimension_review/memory_review。相同观察仅供确实被其证明的项目共享，清单PASS不覆盖原字段FAIL/UNREVIEWED。 归属与正式来源见 [rule-ownership.md](rule-ownership.md)。

除单格比例误差外，D按实际宽高复核每话六种画幅分布、竖版格数>75%及交错均衡。计划多比例不代表输出多比例；不能只看manifest就放行。当前整话模式只在完整源序上判断75%指标；旧C停点按原冻结合同恢复。详见 [全话画幅计划](frame-ratio-plan.md)。

新runtime的增量队列只整理新增/变化项；保存真实QA后统一commit。每个失败格在原diagnosis补repair_routes；输入、镜头或prompt根因先修依据，只有generation_execution进入targeted_image_repair及唯一第二轮。C按本话完成事件即时提交，不因其他话未完成而等待。

新RV额外执行 [原图、原尺寸局部和连续镜头审查](visual-evidence.md)：逐检查项写具体observed，手/首饰/接触/清晰度绑定真实原尺寸区域，同场景前序换版只重审受影响比较。前序未返回可先审本格但不能提前放行。客户标注样本的复核不宣称盲测。

## 构图、清晰背景与既有图片处理

同次看图核对主体和动作是否突出、上下缘是否符合批准裁切、必显手势/道具/文字/同时反应是否完整、clear_limited有无被画成散景或虚化、背景机位结构是否正确，以及视线、持物手、首饰。写入原framing/background_space/action_interaction及适用visual_evidence/MEM，不以提示词或文件成功代替观察。

| 实际问题 | 处理 | 边界 |
|---|---|---|
| 图本身正确、仅背景过多 | 裁切候选 | 保留全部必显信息、目标比例与有效像素；超出批准构图范围按原流程解决 |
| 首饰/手指/腕部局部错 | 合并本格局部修复 | 保留正确脸型、衣装、动作、背景及先前有效修正 |
| 站位/肢体归属/接触方向错 | 修订受影响镜头后重绘 | 先解决空间动作依据 |
| 连续图布局矛盾 | 回查A/B布局视角 | 不靠裁掉矛盾部位宣称空间通过 |

原图保留、改版另存；“修改版”仍看真实图。裁切候选记录原图path/sha256、矩形、输出尺寸、必显信息与比例复核。审阅局部截图不作成品，本次未自动化裁切入包。新生成以镜头取得紧凑构图，不默认先生成宽景再裁切。替代方案影响剧情、人物关系、服装或获批构图时先按准确范围解决。

普通独立格仍异步，逐张实际审查；仅真实实图依赖、高风险或用户明确要求逐张串行时等待。不改变一次自动返修预算和人工停点。

同一次原图观察填写适用检查，复用有效未变QA。已批准技术派生在范围内直接处理并重验；轻微取景容差须有明确原授权，不改身份/衣装/动作/空间判据。自动预算用完集中提出准确格号、实图、方案和次数，不逐格重复提问。


新背景策略按[背景模式](background-treatment.md)在原QA同次检查。只简化细节且保留场景结构可通过；严重空背景记录scene_background_missing，不能写PASS，缺必显承托/接触/遮挡/线索仍失败。重点部位看原尺寸；省略环境写omitted_by_design而非人物离场。D核对留白到实景的实际连续性。


原QA误判处理及返修路线见[实际执行质量与返修分流](execution-quality.md)。复用现有记录和人工停点，不静默升级旧RV。

## 局部证据、误判与编辑退化

inspection_targets存在时，原尺寸view.covered_targets须准确覆盖该check的目标；复杂接触结合原图看所属前臂、手腕及对象，不能截掉目标只凭手掌局部通过。scale=original_pixels，声明resampled=true或source_size与真实原图不同不能冒充原生细节。

固定观察顺序为全图→原尺寸局部→必要连续图，不新增一次审查。全图先逐人物追踪掌/腕/袖口的数量和所属身体，再看局部握持、指掌、眼部与遮挡边界，最后按床头/床沿/路沿等固定锚点比较世界位置。缩略总览只用于定位，不能作为手指、眼睛或清晰度通过证据。补充comparison_panel_ids时使用其真实最新原图；没有看见的另一侧路沿、被裁掉的床面不能作为确定移位/消失的证据。

分别记录已确认缺陷与尚无足够证据。图中裸露眼区没有结构、多出掌/腕/袖口、可见承托矛盾应FAIL；合理画外或真实遮挡不能误判成缺失；不能分辨则保留UNREVIEWED/HOLD并指出缺少什么证据。用户标注后的复核不宣称盲测，代码测试不宣称模型已能稳定识别这些错误。

preservation_regions存在时，repair_comparison逐区填写preserved_observations，并同时检查修复部位、原清晰度和先前有效修正。整体涂抹或主体过小先分辨构图/输入原因，插值及锐化不是清晰度通过证据。发现旧QA误判则追加更正依据和新结论，保留旧记录，不为迎合错误图回写冻结标准。

有structural_change的返修，repair_comparison.whole_subject_recheck另记录全人物重新计数与连接、旧结构移除和承托的实际结果；局部正确而全图多手仍FAIL。此项复用六项重审，不增人工停点。


新整话按[服饰与单画面](appearance-and-single-frame.md)填写原visual_evidence_review的frame_observation与appearance_observations。自身左右结合全图朝向判断，原尺寸局部核对归属/部位/手指/数量/款式及附着；任何可见关键项不清楚不得PASS。发现上下/左右分格或漫画内嵌格，原framing维度FAIL；服饰位置错记原costume维度FAIL。真实镜面不是独立漫画格。

审核优先读取当前包派生inspection_plan：原规则的具体执行约束与服饰身体锚点、可见数量均定位到原QA字段。按原图真实观察填写结论；不临时更改标准迁就图片。只有实际输入缺陷才修对应生图包；一般执行偏差沿原范围返修，局部修正同时检查配饰及已正确区域是否保持。
