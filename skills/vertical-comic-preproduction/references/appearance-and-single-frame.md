# 服装配饰定位与单画面

新运行的主表、增量派生、共用规则/图集复用与少冻结执行见[第二批草稿提速](draft-authoring.md)。派生文件不授予批准或生产权限。

新整话RV由init_preproduction默认声明appearance_policy=appearance_lock_v1和frame_policy=single_frame_v1，配套visual_evidence_v1。旧RV保持原冻结工具，采用新合同须在新RV明确迁移、核对受影响批准；不得热改在途包或签回旧批准。通用方法属于Skill，具体人物穿戴只属于本书批准基准，不自动存入规则记忆。

## A：唯一衣装状态与细节来源

继续使用visual_basis.appearance_details，不另建人物/首饰表。每个入画人物当前costume_state须有至少一条garment核心衣装记录（无服装也须有批准的absence依据，不能猜）；重要配饰分别记录。不能只给耳环依据，却漏掉衣领、袖长、内外层和当前衣装。状态范围沿原人物状态登记，跨话同状态复用同一依据。

每条细节沿用subject_id、costume_state、expected、reference_sha256，增加：

```json
{
  "category":"accessory",
  "presence":"present",
  "count":1,
  "design":{"style":"单层水滴耳坠，顶部菱形连接件","color":"银色","material":"银与透明石"},
  "placement":{
    "side_basis":"wearer_anatomical",
    "side":"left",
    "body_part":"ear_lobe",
    "anchor":"角色自身左耳垂穿孔处",
    "attachment":"耳钩连到耳垂，不悬浮在头发上",
    "motion":"natural_swing"
  },
  "source_region":[120,80,200,200],
  "readability_evidence":"实际打开批准原板，在此原像素区域能分辨连接件与坠体"
}
```

这是字段形状示例，不是本书设计或批准。presence=absent时count=0，须明确原板证明哪个身体部位没有此装饰；不可从遮挡/模糊猜不存在。present为正整数数量，数量是该细节在整个人物上的总数，不是双侧各自数量。absence无需虚构不存在首饰的材质。

side取left/right/bilateral/center，始终以角色自身为准。body_part取ear_lobe/neck/chest/wrist/finger/lapel/sleeve/collar/torso/waist/leg/foot/hair/other；other要在anchor具体解释。戒指须另填finger=thumb/index/middle/ring/little及left/right手。motion取fixed/natural_swing/drape：胸针/刺绣固定于衣片；项链耳坠可合理摆动，衣料可起褶，但不能换归属、佩戴侧、款式、数量或层数。

category=garment时design及expected写当前款式/领型/袖长/开合/内外层、颜色和材质；固定口袋/胸针/绣纹可另列。所有描述须来自批准资产。每条source_region定位真实清晰原板区域，reference_sha256来自原基准reference_files；只放大模糊耳部不算得到新细节。未知款式或佩戴侧集中提问，不默认对称、不抄其他状态。

## B：身体位置与画面投影分开

原visual_evidence.detail_visibility仍覆盖当前人物/衣装全部已登记细节。每项取visible/occluded/out_of_frame并给basis；只有visible需要增加projection：

```json
{"surface":"direct","screen_position":"本机位投影在画面右侧耳部","occlusion":"发丝遮住耳钩后半部，坠体仍可见"}
```

surface=mirror_reflection时须另填reflection_basis说明批准镜面、机位和反射方向。反射改变画面投影，不改变人物实际佩戴侧。不可见不强求画出，不能为展示耳环改变头向或裁切。真正摘戴/换装按原稿和批准状态转换登记，不因换机位产生新状态。

每个visible细节用原kind=accessory检查（该原类别同时承载衣装细节），detail_id指向本细节、subject_ids仅为所属人物。检查需观察款式、总数量、附着、角色自身侧、当前投影及清晰度。原图中高光/褶皱不自动视为多了首饰或换了服装。

## 每格只允许一幅画面

每个panel声明同一frame_policy，并记录：

```json
{"frame_plan":{"layout":"single_scene","source_layout":"multiple","selected_scene":"此处写唯一保留的完整画面","omitted_scenes":["另一幅被忽略的完整画面描述"],"selection_reason":"优先保留关键动作或剧情结果；用户要求一图一画面"}}
```

源本来只有一幅时source_layout=single、omitted_scenes=[]。源有上下/左右两格或多个镜头时，自主选择承载本格关键动作、情绪或剧情信息的一幅，其他忽略；不新增格号、不拆成两张、不把另一幅改成内嵌格。原脚本、格数、顺序及locked_script保持原样，frame_plan只记录绘制取舍。B中人物、动作、道具、visible_region和required_visible须随已选画面一致，不能遗留另一幅的必显要求。

忽略项留在审计JSON，不进入绘图prompt。实际内容编译器仅写已选画面，不把完整双画面事件句作为另一个绘制要求。frame_plan不能自行取消原文中的交付文字要求；若保留画面无法容纳原指定文字，沿原文字合同集中解决，不擅改文字。

single_scene指一个连续取景的漫画画面，不是只能出现一个房间/一个人物。真实镜面、窗外、电视或相框作为本场景物件不被误算为漫画分格；禁止借这些名义另插第二个独立叙事镜头。

## 生图和返修实际输入

appearance_lock.py复用原visual_execution_block编译：人物/当前衣装 → 具体款式与数量 → 身体锚点/佩戴侧/手指 → 本镜头投影/遮挡 → 单画面要求。原identity/style/reference_usage等块继续保留，不用新块覆盖原完整prompt。

每次生成和返修都实际携带适用身份、衣装、画风及清晰细节来源；衣装用途绑定归属同一人物。完整原板可以承担多个职责；忠实局部/图集须覆盖细节原裁区并保持来源，不新画假参考。原参考合同继续核验裁区像素及最多5条路径，超限先忠实整理，不删关键人物或配饰。

参考上不同衣装/人物的首饰不迁移；风格参考只承担画风，失败图不成为款式权威。detail_carried检查来源覆盖，reference_errors另核验实际原板裁区边界及本人物costume_state用途。它们不能判断图像究竟清不清，readability_evidence必须来自实际看图。

返修增加appearance_repair：correct_detail_ids与preserve_detail_ids互斥、完整覆盖本格可见细节；instructions逐个写具体纠正内容。非服饰问题返修时correct_detail_ids=[]，可见服饰全部列preserve。改配饰时repair_focus.failed_transfers含accessories，改衣装时含clothing；失败图不得允许继续迁移对应错误。纠正/保留段进入真实prompt，保留已正确脸型、动作、光线、背景及先前修正。原唯一自动返修预算不变。

## 一次看图、原QA逐项记录

make_generation_qa经原visual_evidence.review_template自动生成两类UNREVIEWED记录，仍位于同一visual_evidence_review，不新建第二份QA：

- frame_observation：真实图hash、scene_count、layout、reviewer、observed。scene_count表示漫画子画格数量，不是房间/人物/镜中物件数量；PASS必须为1和single_scene。发现双格须FAIL，不把用户禁止的双格当艺术构图通过。
- appearance_observations[detail_id]：actual_owner、actual_costume_state、actual_side、actual_body_part、actual_finger、actual_count；款式/附着/当前投影/清晰度分别写checks及observed；side_evidence说明从全图身体朝向与局部如何确认自身左右。observation_id引用原accessory检查ID及其真实原尺寸view，不重复裁一套图，不借另一个人物的耳朵作依据。

总PASS不能覆盖局部FAIL或看不清。遮挡/画外以B计划与真实图核对；可见耳坠被漏画、戒指换手、衣装串状态属于失败。原尺寸不足以认清关键位置时保持未通过，放大、锐化、PNG格式不能代替细节证据。服饰失败写入原costume维度，漫画分格失败写入原framing维度。

返修继续完整六项审查，在原repair_comparison增加preserved_detail_observations，逐项观察原已正确服饰是否保留；与原返修底图hash和当前输出hash绑定。修好耳环却改坏领口/项链不能通过。未变图沿原真实QA复用，实际改图重新审查。

## 验证与边界

新增门禁验证字段、冻结来源、实际prompt、参考携带和观察记录；不声称程序能自动识别耳环或保证模型不画错。旧基准未写清来源先补准确范围A/B，不把生成错误改成新标准。通用规则不增加固定人工停点；正常独立格保持并发。

代码测试使用隔离合成输入、真实参考文件与原完整门禁，验证拒绝缺项和错误记录；不以合成图测试冒充本书真实生图效果。后续真实对照应固定源稿、批准资产、镜头、实际后端和返修预算，分别记录串装/配饰位置、双格、漏检/误判及返修次数；未做真实生图对照不宣称通过率或耗时已经改善。

## 可见数量与不可见配饰

批准count继续表示人物身上的总数量。多件细节，或bilateral双侧配饰，在visible条目的projection增加visible_count（整数）：present时为1到总数，absent为0。单件可省略，默认等于总数。镜头只能看到一侧时不要写成必须画出全部；需要进一步区分不同手/不同位置的单件，仍分别建立原appearance_details条目。

编译器同时写总数和本镜头可见数量。occluded/out_of_frame也进入本格约束，说明原身体锚点与遮挡/画外依据，禁止为了展示细节而移位、解除遮挡或扩大裁切；不要求画出隐藏首饰。不可见细节沿原detail_visibility_observations核对真实遮挡与意外补画，不猜测隐藏款式已经正确。

appearance_observations附expected供审阅，须与当前基准一致；actual_count记录本机位实际可见数量。checks增加anchor，逐项观察固定位置与身体/衣片关系；attachment继续检查真实连接，screen_position检查机位投影。反打、镜面、头部转向和自然摆动均不能改变身体锚点。返修correct/preserve仍完整覆盖可见细节，并重查不可见项有无被移到可见位置。

同一人物与衣装状态跨格复用同一批准细节来源；摘戴、换手、换位置须有准确源稿/批准状态变化，不能靠给错误配饰另起名字维持表面一致。审核先依据身体朝向确认自身左右，再看原尺寸配饰及附着点，不能按画面左右认佩戴侧。
