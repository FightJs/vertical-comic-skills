# 空间、细节与原尺寸审查：visual_evidence_v1

新建整话RV默认启用 `visual_evidence_policy=visual_evidence_v1`。使用配置可显式写 `quality: {policy: visual_evidence_v1}`。初始化只创建未批准模板；具体视觉依据、B与包仍按原准确范围批准。旧RV不自动加字段：恢复须使用其冻结工具/规则快照，或显式建立新RV迁移；不得重签旧哈希。本文不改整话并发、六项QA、真实实图依赖、原稿/比例或唯一自动返修预算。

## A：固定来源

在现有全话visual_basis增加相同策略及两个映射，不另建重复资产库：

- `scene_layouts[space_id]`：所属原 `scene_id`、`layout_id`、`entities`（实体ID→批准来源能证明的描述）、`relations`。
- 每个relation含唯一 `id`、已登记的 `subject/object`、具体 `expected`、批准参考文件 `reference_sha256`。例如“主桌位于舞台前方，两者之间没有其他餐桌”，不能只写金色灯饰。来源无法证明的关系先留缺口，不编精确坐标。
- `appearance_details[detail_id]`：`subject_id`、当前 `costume_state`、具体 `expected`、`reference_sha256`；从原板忠实提取时可登记原像素 `source_region=[x0,y0,x1,y1]`。只记录重要且能看清的首饰/固定特征，不为每根发丝建资产。
- `reference_sha256` 必须来自本视觉基准reference_files。原图未清晰显示的设计不能靠放大猜测。需要新设计时仍为A候选。

坐标使用相对区域/座位编号即可。固定实体、反复可辨认人物和远处人群区域分别登记；远处模糊宾客不用逐人设计。布局图按复杂场景需要制作一次后复用；每格不强制画图。

原relations和blocking只补影响连续镜头的关系：床头/床沿与躯干承托、人物相对固定床侧、车辆相对路沿等。相对关系足够时不编厘米坐标。没有台词或暂时不参与动作不会删除在场者；物件大小以真实形态和相对手/头比例核对，透视变化不等于物件变大。

## B：本格状态和可见性

全话shot_manifest及每个panel声明同一策略。panel增加 `visual_evidence`：

```json
{
  "scene_run_id": "当前连续场景状态ID",
  "previous_panel_id": null,
  "spatial_applicability": "REQUIRED",
  "spatial_reason": "背景与座位关系承担本格信息",
  "blocking": {
    "人物ID": {"position": "座位S1", "facing": "主桌", "presence": "present", "basis": "本次批准座位与原稿"}
  },
  "changes": [],
  "visibility": {
    "人物ID": {"status": "visible", "expected": "人物仍在S1，本机位投影在画面右侧", "basis": "批准机位与座位"}
  },
  "hands": {"applicability": "NOT_VISIBLE", "basis": "批准肩上裁切不含手"},
  "detail_visibility": {},
  "checks": [
    {"id": "space-01", "kind": "space", "subject_ids": ["人物ID", "S1"], "expected": "人物不换座位，背景对应舞台所在方向"},
    {"id": "presence-01", "kind": "presence", "subject_ids": ["人物ID"], "expected": "人物在场，不能因换机位新增或删除他人"},
    {"id": "clarity-01", "kind": "clarity", "subject_ids": ["人物ID"], "expected": "焦内眼线、发束与衣领轮廓清晰，无非预期涂抹；保留批准景深"}
  ]
}
```

这只是字段示例，不是生产批准或可直接套用的镜头。空镜可没有blocking，确无环境信息才用NOT_VISIBLE并说明依据；背景非minimal仍须REQUIRED。

`space_id`区分同一酒店资产中的宴会厅、走廊、卧室等真实物理子空间；单一场景可省略并沿用scene_id。不同子空间不能因为共用一个资产ID而合并站位。`previous_panel_id`关联本话同物理子空间最近的前序格，切场再切回不能重置。真正时间/场景状态变化换scene_run_id并写 `run_change_basis` 的原稿依据。同run的实体不能从blocking删除来表示离场；改为 `presence=off_scene`，保留其状态。移动、朝向、离场分别在changes记录 `entity_id/field/from/to/basis`。屏幕左右变化由visibility描述，不更改世界座位。

visibility覆盖全部blocking实体及需要检查的固定锚点。status取visible/occluded/out_of_frame/off_scene，并写具体expected和basis。画外、遮挡与离场不能混用；入画人物和visibility须由执行者按当前裁切实际核对。

occluded的expected写清谁挡住哪部分、遮挡边界；out_of_frame写哪条画幅边界排除该实体。较早宽景才能证明状态时，可在同一visual_evidence增加comparison_panel_ids，只列必要的同子空间/同scene_run前序格；最近前格仍由previous_panel_id记录。此列表用于实图比较，不自动增加生图依赖或阻塞普通独立格。QA在continuity_comparisons逐项绑定这些格当前output的path/sha256；其中任何原图换版，只复核受影响比较。

`detail_visibility`必须覆盖当前入画人物/衣装在基准登记的全部细节，逐项写status与basis；可见细节另有kind=accessory、detail_id对应的检查。可见手写hands.applicability=REQUIRED并有kind=hand；真实遮挡不强求五指全露。多人接触有kind=contact检查，额外写actor、actor_limb、target、target_part、visible_path，明确角色自身左右与画面左右。躯干到手腕的连接、握持和受力都要实际看图。

check的kind只取space/presence/contact/hand/accessory/clarity，id唯一，subject_ids和expected具体。没有某风险不新增重复项；同一观察可支持原六项与适用MEM，但不是所有项共用一条泛泛结论。

## 编译与实际参考

共享 `visual_evidence.py` 提供：

- `context_for(basis,panel)`：只派生本scene的layout及本格细节。写入执行panel.visual_evidence_context。
- `execution_block(panel,context)`：编译所需固定关系、当前站位、可见/遮挡、检查约束及首饰细节；写入visual_execution_block并合入实际prompt和prompt.txt。
- `--basis <真实基准JSON> --panel <本格JSON>`只输出候选上下文、文本块及缺项，不写批准、不调用生图。

包内panel.visual_evidence必须与获批镜头完全一致，派生context必须与当前基准一致。基准和镜头的根策略也须相同。实际参考持续携带批准画风、身份衣装、场景和必要细节；每请求最多5条路径。单图多用途去重；忠实人物图集只有裁区实际覆盖该细节source_region才可证明携带了细节。看过原图、相同源哈希但裁掉耳环的图集都不能替代实际细节输入。

调用前由execution_contract语义门禁、batch_workflow实际输入门禁、codex_reference_contract实际参数导出共同检查。技术检查只能证明输入一致和缺项被拦截，不能证明几何和图片已经正确。

## 返图：全图、原尺寸局部、连续镜头

make_generation_qa在原QA中增加visual_evidence_review，初始全为UNREVIEWED。先实际打开原图、批准参考及相关真实前序图；全图审主体、动作、风格和构图，手/首饰/接触/清晰度看原尺寸局部，连续场景按实际图比较。已批准的正常景深、真实透视缩短和遮挡不是失败理由；clear_limited不能临时用背景虚化解释错误。

每个observations沿用原id/kind/expected等，不得事后改判据；填写status、reviewer、observed和view。view含真实image_sha256；细节检查含 `scale=original_pixels` 和实际原图像素区域 `region=[x0,y0,x1,y1]`。observed要描述实际看到的结构和差异，不能用预期文本代替观察。同一实际观察只写一份，原dimension_review及命中MEM的evidence可准确引用该检查ID和对应观察，不再复制整段描述；被引用的观察必须实际存在、内容适用并绑定同一原图。

需要审阅局部时，用下列命令从原图无缩放、无损提取。regions JSON清单每项是check_id与整数region。生成的是审阅辅助文件，不能作为生图底图或成品替换：

```text
python <scripts>/visual_evidence.py --review-image <本次真实原图> --regions <区域清单JSON> --output <不存在的新审阅目录>
```

记录full_image_review；visibility_observations、detail_visibility_observations逐实体写status、actual_visibility、observed。计划可见却消失不能PASS，计划画外却新增也不能PASS。

full_image_review先记录逐人物肢体总量与所属路径、承托、人物持续在场，再沿原尺寸观察验证局部。检查露出区域是否真的有眼部/指掌结构，不能把“模糊”“可能被挡”当成观察证据。区分确认错误与证据不足；后者保留UNREVIEWED/HOLD并说明缺哪个视图，不冒充PASS，也不猜造必然错误。

continuity_comparisons引用真实同场景前序panel_id及本话output的原样 `{path,sha256}`，写status与具体observed。前序换版即比较失效，重新看受影响格对；不要重跑不变图的全部审查。独立格生成仍并发，不因设计连续性自动创建generation_dependencies。前序图未返回时，先审本格六项和局部，连续性保持未审；实际匹配后补齐，不能提前记VISUAL_PASS。批次与D仍执行整话/跨话验收。

## 返修底图和清晰度

operation=repair时增加repair_source：真实 `image_sha256`、`source_attempt_id`、`selection_reason`、非空 `preserved_features`。底图必须属于本格已记录的原始返回尝试，并实际携带；不能用客户红字标注图、缩略图或别格图冒充。preserved_features逐条进入实际prompt，包含此前有效修正。选最清晰且错误较少的适用底图，不机械沿用最新图或最早图。

空间/状态依据错误先回对应A/B；同格局部错误尽量合并一次修正。原repair_focus仍须禁止继承待修要素；唯一自动返修预算不变。返修返回仍完整六项，另在visual_evidence_review.repair_comparison记录base_image_sha256、clarity_status、实际observed及原样preserved_features，与所选底图在可比尺度比较细节与修正保留。尺寸/PNG格式通过不等于清晰度通过，不自动锐化或放大冒充质量改善。

## 验证与效果记录

先用现有真实问题图验证检查覆盖，再同输入、同工具/并发/返修预算做小样对照，最后整话验证。原稿、批准资产、机位与参考变化必须记录；未配对原图/脚本版本不能声称复现或作公平对照。保留所有首轮结果、未知/失败调用和额外中间图成本。统计首轮通过率、严重空间错误、审查漏检/误判、返修次数、准备/审查/人工等待及整话总耗时。客户红字图是已知问题样本，已看过标注的复核不得宣称盲测。没有真实新旧生图结果时，只报告合同/回归验证，不宣称质量或速度已提高。

## 执行链审计补充

失败图仍须实际完成本格全图及适用局部检查，允许明确PASS/FAIL但不允许UNREVIEWED；同场景前序图未返回时可暂不完成连续性，不因此阻断已确定失败的局部返修。失败项同时记录到原六项相应维度。实际原图尺寸重新读取，不能靠填写较大image_size放行越界局部。

返修引用只允许在原reference_bindings之后追加本格已记录原始返回图的编辑/空间/动作/道具用途，不修改原身份衣装画风绑定，不扩张创意批准。编辑目标与历史attempt/output经状态门禁核对后临时加入执行参考允许清单，不成为新资产或画风来源。返修授权、真实输入门禁、逐格JSON与manifest、返回登记、质量验收均检查相应来源与冻结判据。

原尺寸局部必须覆盖所审目标；复杂接触应联合原图查看肩肘腕掌和接触对象。局部裁掉目标或接触点被遮挡时，不能仅凭该局部判完整动作通过。

接触处露出且线条清楚，仍须核对动作的具体作用部位和阶段。例如批准扶前臂却实际抓住上臂，不能以“已经看见搀扶”通过；同样不能把伸手靠近判成握住。保持原check的target_part和expected，以实际观察写明差异。

一张场景板含多个房间/子空间时，编译前实际看清本格对应视图；提示词明确所选视图和不可混入的邻近子空间。首轮若混用场景，唯一修正轮先检查输入是否突出正确视图；必要时按现有忠实派生合同使用原批准视图选区，保留原像素来源和用途，并在五条预算内重新核对画风、人物衣装、场景及编辑目标。不要只追加“严格一致”或照搬错误图的装饰。缺少所需机位依据仍回受影响A/B，不以裁区制造新几何批准。

## 通用提示词到本格事实

背景扩展按shot-framing.md选用。framing_execution_block(panel)把focus、body_crop、required_visible、visible_region和background_treatment编译成文字；execution_block已携带该块，不再追加第二份。缺值HOLD，不凭模板补画面；旧包没有本字段时输出保持原合同。

沿用checks：hand写指掌/腕臂连接和握持；contact写actor、角色自身左右肢体、target/target_part及visible_path。单人操作也明确接触和当前动作阶段，不把指向当按下、靠近当触碰。动作阶段、视线目标、持物手来自批准逐人物记录及具体checks.expected，不另建状态账本。首饰由appearance_details编译，画外细节不强行补入。

clear_limited格在原clarity检查写当前背景需要清晰可辨的对象，原framing/background_space维度分别看实际裁切及机位空间。framing_review_focus只提示原QA，不新增PASS或人工停点；通用判据仍以实际MEM-004/005/006为准。


新策略background_policy=narrative_background_v1的场景色调资料、逐格模式、清晰分区和验收边界见[背景模式](background-treatment.md)。context_for仅派生本格profile；背景计划必须与批准framing一致，变化使新策略QA指纹失效。


具体动作阶段、场景视图与细节有无见[实际执行质量与返修分流](execution-quality.md)。复用现有记录和人工停点，不静默升级旧RV。

## 有针对性的观察覆盖

check.inspection_targets可列本格易漏检的必要观察目标；返图view.covered_targets须与其一致。可选view.source_size指真实原图尺寸，resampled只用于如实标注，不能用重采样区域作为原生细节证据。区域存在与目标完整覆盖仍由实际观察判断，不用填写目标名称冒充看过图。

repair_source.preservation_regions为真实底图具名整数框；repair_basis和实际参数导出均检查原图边界。返图repair_comparison.preserved_observations逐名称记status/observed；源图与新图可有不同尺寸，不能用新尺寸猜原保留区。所有字段保留在现有QA/执行包，不创建第二套验收来源。


新整话补充[服装配饰定位与单画面](appearance-and-single-frame.md)：在原appearance_details/detail_visibility/checks和同一visual_evidence_review内记录身体锚点、投影与实际观察；appearance_lock.py由本模块原入口调用，不新增第二套资产表或QA。
