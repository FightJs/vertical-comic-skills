# 按叙事选择背景：narrative_background_v1

新整话RV显式启用background_policy=narrative_background_v1，配套visual_evidence_v1。配置文件省略background时保持旧行为；无配置的新整话初始化默认启用。旧RV使用冻结快照，升级需新RV核对来源与批准，不原地重签。背景策略不改变源脚本、格序、比例、整话异步、真实实图依赖、人工审查范围或唯一自动返修预算。

## 选择与边界

先核对必显剧情 → 承托/接触/遮挡/视线与反射 → 最小充分裁切 → 主背景模式 → 重点清晰对象。每格只选一种主模式；必要局部实物可保留。近景优先采用实景柔化，保留可辨识的场景大轮廓，不设置全话留白配额，相邻变化按本批冻结MEM-010版本核对，不靠背景换色伪造叙事变化。

| background_treatment | 适用及边界 |
|---|---|
| clear_limited | 必要实景：建立地点、进出、位置变化、路线、环境线索；仅绘必要结构，仍可省略无关细节 |
| scene_flat | 特殊同色留白：仅明确选择抽象背景表达且不会损失空间衔接时使用；reason记录具体理由，不能仅以近景或双人近景作为理由 |
| scene_softened | 实景柔化：仍需识别场所，二维大色块减少纹理、边缘与对比；不默认摄影散景或全图模糊 |
| scene_outline | 轮廓概括：次要环境与远处对象，保留需要的数量、所在位置和遮挡；实体轮廓不变成墙面投影 |
| approved_depth_of_field | 保留现有特殊获批景深入口，须background_treatment_basis及真实适用批准 |

床上近景可省房间纹理，不能丢床面/被单承托；拿杯可省墙饰，不能丢握持和必要桌缘；发现门后有人须留门缝、遮挡与被发现对象；镜中剧情保留所需镜框及反射关系，仍执行MEM-008或真实获批例外。背景简化不授予镜面例外。

默认只减少背景细节，不删除环境。B在retain写清本机位真实可见、能承接前后格的结构；omit优先列纹理和小装饰，不笼统写“全部背景”。不得为了凑背景扩大取景或硬塞出画家具。光向、冷暖、曝光、人物受光保持原批准依据，背景柔化不授权重新打光。新默认不改旧RV冻结模式；显式scene_flat配置仍兼容。

## A：场景资料只准备一次

visual_basis.scene_background_profiles为对象，按profile_id索引，每项含profile_id、scene_id、space_id、scene_run_id、base_color、line_color、lighting、reference_sha256。scene_run_id对应本格visual_evidence的同场景连续状态；不混用不同房间或昼夜依据。来源属于reference_files，实际携带原板或覆盖必要选区的忠实图集；裁区证明规则沿用detail_carried/source_region。色调用可观察描述，精确色号可补充但不宣称工具能硬锁色值。

A只冻结颜色/光向/来源，B选择具体必显对象。无需为色调新增一次生图或强制色板。具体书/人物/家具事实留项目基准；不写入通用记忆。

## B：逐格计划与清晰度分区

新策略根状态、visual_basis、镜头集合、每个panel、执行包均声明同一background_policy。每格沿用framing.background_treatment，增加framing.background_plan：

```json
{
  "reason": "原稿重点是反应，场景已建立，镜框提供足够定位",
  "profile_id": "当前已批准场景状态的资料ID",
  "retain": [{"id": "MIRROR_FRAME", "expected": "画右一段与机位相符的镜框"}],
  "omit": [{"id": "WARDROBE_GRAIN", "expected": "衣柜木纹及远处装饰"}],
  "sharp_focus": ["人物眼睛与嘴角", "当前可见耳饰和衣领", "原稿必显手指与动作对象"]
}
```

示例需替换为本格事实，不凭模板增加耳饰、杯子或手势。retain/omit可为空数组，sharp_focus非空。稳定ID不得同时保留和省略；必显项不能列入省略项。人物身体裁切、required_visible、visible_region、blocking、hands、接触和细节可见性继续复用现有字段，不另建完整重复表。表情按原稿写可观察变化和适用幅度，不统一夸张。

重点清晰区＝表情/首饰/关键手指与物件；结构辨识区＝retain的承托面、门框等；允许简化区＝omit及无关环境。可见首饰锁定款式/层数/佩戴侧，真实遮挡不强行补出。手部写所属人物、角色自身左右、对象、接触路径及遮挡，不强求五指同时可见。

背景实体若在视域内但按设计不绘出，才可在原visibility写status=omitted_by_design，须同ID存在omit；不标成离场/画外，人物不得用此状态。detail_visibility不允许用它省略本应可见的关键首饰。原布局仍在context，不搬家具，不解遮挡。保留实体的格spatial_applicability=REQUIRED。

## 生图：只有一个最终执行段

使用visual_evidence.context_for从A派生background_profile；framing_execution_block/ execution_block编译实际段落。镜头、人物当前状态、表情动作、必要接触/物件、背景模式/保留省略、清晰重点和画风合成唯一prompt；执行块已存在不重复追加。编译不自动选择模式或修改源原文。

场景参考提供批准布局、色调、光向及必要空间关系；留白格不复现整套家具/灯泡/灯带，除非明确在retain。来源图继续实际传入；人物/衣装/画风职责不被场景覆盖，每请求仍最多五条参考路径。不得用最近图片作为并发定位。

检查与旧句冲突：留白却要求完整复现房间，平涂却要求背景强散景，手势必显却要求双手出画。机器检查结构化同ID/原文冲突、模式合法、来源及执行块一致；同义冲突、叙事信息是否丢失仍在原B语义审计中实际判断，不宣称正则能证明。

## QA、连续性与返修

按原六项QA一次观察，不增加人工停点或独立PASS：framing核对模式/裁切/必显，background_space核对锚点/遮挡/色调，action_interaction核对承托/接触，身份衣装核对细节，原尺寸clarity核对人物与手饰是否一起变软，style_review核对二维表达。新增计划和profile变化会使旧质量指纹失效，实际新图仍须真实审查。visual_evidence_review.background_observation逐项记录mode、实际image_sha256、observed、sharpness_observed，以及retained/omitted按ID的实际观察；模板为空，不新增独立PASS，放行结论仍在原六项QA。

获批留白不因没画全套家具失败；缺床面、门缝、必要反射、文字或接触物仍失败。实景柔化不能把人物轮廓变糊；轮廓人群不能变成投影。实际visibility记录保留omitted_by_design，保持其世界事实。D按同场景真实图补连续性，人物换位/进出及留白回实景仍承接原账本；不以同色替代几何依据。

在原有一次审图中判断柔化背景是否仍可辨识场所、与相邻实景是否衔接；缺场景轮廓记录为背景过度简化，不因肤浅同色视为连续。按当前轻审核与返修预算处理，不新增独立审核轮次。

背景太复杂→纠正背景段与参考职责；必要结构丢失→补具体对象并重审空间；人物变软→核对原尺寸与细节输入；布局依据错→回受影响A/B。返修按原合同选本格真实清晰底图，明确保留正确脸/衣装/首饰/手势/必要锚点和有效修正；同格问题合并一次修正，自动预算不增。调用未知不当视觉失败重发。

## 使用与验证

配置background={"policy":"narrative_background_v1","selection":"content_driven","closeup_preference":"scene_softened"}只对新任务生效。每格模式在原B批准，包仍分别批准准确范围。整话独立格持续并发；不新增背景生成阶段，也不修改在途容量。复杂空景路线仍只按background-first.md的真实适用条件选择，不因留白自动启用。

先跑字段/编译/QA/配置/恢复测试，再同输入独立新生成实景与留白；原文、资产顺序/哈希、机位/比例、人物/动作一致，仅背景执行段不同。保留所有返回、失败/未知与总耗时；不把历史图当新基线、不编辑基线得到新图、不用一对随机结果证明返修率下降。重点覆盖灯带残留、床面承托、手部接触。测试候选不是生产批准图。
