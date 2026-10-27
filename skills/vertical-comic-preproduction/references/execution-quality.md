# 实际执行质量与返修分流：execution_quality_v1

新运行优先按[第一批前期提速](preparation-efficiency.md)执行最小充分设计、代表格接线、单次B/包展示及问题分级处理。可选润饰不产生HOLD；真实缺口在现有委托内修复，局部问题只影响真实依赖，其他工作继续。正式输入与接包要求仍按原合同。

新运行统一按[第一批生产决定](production-decisions.md)衔接审核、返修与交付：真实FAIL不改写，处理动作与交付结论分别记录；旧冻结合同不迁移。下文审核方法、源稿/批准/证据要求仍适用。

本扩展复用visual_evidence_v1的scene_layouts、appearance_details、checks、原六项QA与原诊断，不增加人工停点。只在新整话RV启用；旧RV、已冻结批次不热升级。当前新建整话RV默认启用execution_quality_v1；配置可显式写execution_quality={"policy":"execution_quality_v1"}，初始化在根状态、镜头及包写input_quality_policy；A、集合、逐格须同策略。初始化不是批准，不能伪填已核对。

## 开批与分话

先按batch-runtime.md一次冻结五件套及规则来源，所有生产入口从本批快照运行；安装更新留下一批。本批配置、源稿及实际参考版本留原流程记录，调用前核对适用文件哈希；不重复复制整套资产。每话租约内自主领取、预检、提交、保存、释放，原图保存后释放生图槽，QA队列随后处理；总控只介入容量调整、共因故障、真实批准变化与D。未知结果不自动释放/重发，保留唯一attempt与原预算。读缓存按原运行版本复用，变化只重审受影响内容。

## A：场景视图与细节来源

visual_basis增加scene_views对象，索引每个已核对视图：view_id、scene_id、space_id、description、camera_axes（允许的相机世界朝向N/NE/E/SE/S/SW/W/NW/DETAIL）、visible_anchors、reference_sha256。多房间/多视图板声明multi_view=true并给source_region整数xyxy，注明具体哪一个子视图；来源属于reference_files。方向不是“画面左/右”，轴与对应区域须实际看图确认。匹配只证明声明一致，机器不证明自然语言几何。

复用appearance_details，每项增加presence=present/absent，expected写具体款式/层数/佩戴侧或无该装饰，沿用reference_sha256和必要source_region。absence须有清晰批准来源，不能从低清或遮挡推导不存在。衣装状态一次维护；逐格仅说明可见、遮挡、画外。可见区的缺省装饰也按accessory检查；source_region须被实际输入覆盖，不能用看不清耳部的全身图当已约束。

## B：动作阶段和当前视图

原visual_evidence增加scene_view={view_id,camera_axis,required_anchors,direction_basis}，context_for从A派生scene_view；spatial_applicability=REQUIRED时必须有适用来源。不得把反打前图当布局权威，不把画面左右当换座位。提示词只编译当前必要关系，完整世界位置仍留原账本。

原hands增加narrative_role=critical/incidental/not_visible。剧情手须REQUIRED；普通非剧情手按真实裁切处理，不强求全部露指。

不新增动作表：原checks中的contact检查增加action_stage、support、occlusion、forbidden_substitute；原关键hand检查沿用actor/actor_limb/target/target_part/visible_path，并增加action_stage、support、occlusion、palm_orientation、thumb_side、forbidden_substitute。字段写具体当前状态，不能填“正常/按脚本”。如“已接稳手机下缘”不同于“手靠近手机”，“指臀侧”不同于“指腹前”；孩子前探仍须说明臀腿承托在后排。局部不适用写有依据的具体状态，不猜角色左右手。

同一人物/肢体在本格统一用同一个actor/actor_limb值，推荐自身left_hand/right_hand；不能换近义词掩盖重复占用。检查器拒绝同一声明肢体被分配不同对象；确实一手共同握持多个对象时，相关check给出相同combined_grip_basis，解释具体接触与共同受力，并在原可实现性审查核对。它不是几何证明。递接中的两个不同人物可以接触同一物件，不应被“一个物件只能一只手”误拦。

input_quality按已有hand/contact、人物blocking、space检查有条件编译肢体唯一归属、自然持物、摄影机与目光分离、物件正反面及露出部位完整性，不再手工重复通用负面词。具体左右、对象、视线与屏幕朝向仍写原check/人物字段；检查器不能读懂自然语言矛盾，framing_feasibility在B同次明确核对这些事实。

input_quality.execution_block合入visual_execution_block，进入真实prompt及同步JSON。动作、参考、必显信息变化会改变原语义审计expected和QA指纹。framing_feasibility与提问UI解耦，原审计一次核对本格动作字段、当前镜头及适用参考；不能只用通用PASS代替看图判断。普通格不强制辅助图；复杂关系无法说清时先修候选镜头，只对必要高风险格按原流程准备简洁图。

## QA：一次观察与误判处理

原图先核对承托/接触/遮挡，再看身份、衣装、动作阶段与结果；五官、剧情手、重要首饰与物件看原尺寸。机器验证记录与哈希，不证明手部已经正确。尺寸归一、PNG格式或插值不能把模糊图判为清晰。皮肤高光不是自动新增耳钉；褶皱或被遮住的裤缝不自动证明衣装变裙。怀疑时看对应原尺寸局部和清晰原板再下结论；判断仍写原QA，不新建第二份审查表。

先在全图按人逐一追踪可见掌/腕/袖口到所属躯干，查多出的结构，再看局部是否接触；局部“手已托住”不证明总数量正确。比较连续性时选同场景最近前格，必要时补能证明固定床侧、路沿或持物状态的较早图。只把可观察矛盾判FAIL；看不见的区域保留未核实，不凭用户提示或模型想象确认移位。已看清的裸露眼部不能用另一侧头发遮挡来解释消失。

背景根据叙事干扰、漂移风险与必要空间选择模式，不因近景自动留白；优先减少不重要纹理，保留接触、承托、线索和正确方向。背景控制的实图收益需独立验证，不能由模式字段通过推导质量提高。

## 返修：先决定下一动作

在原failure_diagnosis或返修授权内记录repair_decision：reviewer、evidence、source_image_sha256、defects（crop/accessory/eyelid/finger/local_clarity/costume_detail/expression/seat/support/reflection/limb_ownership/camera/scene_reference/action_stage/action_target/prop_state），必要时same_problem_persists。

- 只有crop→crop_candidate，不提交生图。
- 仅局部装饰、眼睑、手指、局部清晰度等→local_edit，一次合并本格问题。
- 错座位/承托/反射/肢体归属/动作阶段对象/道具状态/场景机位→rebuild_inputs，先修对应A/B/包。
- 第二轮或同一问题持续→stop_diagnose，不能重置自动预算。

原repair-authorize在新策略下必须读取repair_decision。rebuild_inputs只有input_resolution绑定当前visual_basis、shot_manifest并有具体evidence，且真实新包在framing/visual_evidence/reference_images/visible_region/reference_bindings中确有变化，才可继续按剩余原预算预检。该结构不授予批准；原完整generate门禁仍核验真实A/B/包，单改prompt措辞不算修复输入。

```text
python <快照scripts>/production_runtime.py --state <流程> --action repair-plan --panels P001 --diagnosis <本话诊断相对路径>
```

repair-plan只读输出路线。裁切工具保留原图，design含source_image_sha256、reviewer/evidence、crop整数xyxy、target_ratio、min_short_edge、从批准镜头复制的required_visible及逐项required_regions原图框；脚本检查全部区域保留、比例与有效像素，不放大。区域是否准确覆盖剧情需实际核对，不能空填框凑通过。

```text
python <快照scripts>/repair_routes.py --crop-source <本格原图> --crop-design <核对后的JSON> --output <不存在的新PNG>
```

输出仅CANDIDATE_REQUIRES_ACTUAL_QA和来源报告，image_calls=0，不改原state或把裁切图伪造为原生返回。候选进入原图像审查及D，符合既有交付派生合同才入包；本工具不自动放行/替换成品。局部编辑仍用真实清晰底图与批准参考，返回后检查保留项是否退化，调用名称不是像素锁定或质量证明。

## 只读统计与验证

production_metrics.py显式指定每话一个权威state；禁止把多个迁移RV混算。按书/话/格/attempt去重，分别报告声明输出、实际原图核验、原生终态事件、QA登记和人工批准未知项。多个round_id=1的迁移记录单列歧义，不擅自当同一格真实首次。诊断字段统计为mentions，不冒充互斥错误数。缺时间/错误分类记不可用，不以0掩盖；并发耗时不可相加成总历时。

```text
python <scripts>/production_metrics.py --state <E021流程绝对路径> --state <E022流程绝对路径> --native-events <原生事件CSV> --verify-images
```

只有真实核定capacity才传--capacity，观察窗口在途率不等于“有就绪任务时”的有效利用率。新运行持续保存原提交/返回/保存/QA时间和具体错误；等待阶段已有真实事件时再推导，不从气泡间隔猜服务时间。首轮通过率、每张合格调用成本、互斥等待与编辑退化率无法还原时如实未知。

先验证快照/租约/异常恢复，再真实问题只读回放、编译实际请求。付费小样保留同一源稿、原批准资产及画面目标，优化允许改变真实prompt或忠实选区并明确记录变量；每次独立生成不编辑历史图冒充新基线。新图不自动成为生产批准或写回记忆。不增加并发上限，不改变唯一自动修正轮次，不以新增规则或测试通过宣称实图质量提高。

## 局部可读性与保留范围

B的framing_feasibility同次核对关键接触能否在当前裁切中看清，以及场景/身份/画风/失败底图是否有相反内容。复用已有动作字段，不为普通手势制造完整复杂模板。可在原hand/contact/clarity检查声明inspection_targets，返图view.covered_targets逐项说明实际观察覆盖；文本和框只绑定证据，不能自动证明解剖正确。

局部编辑若容易损伤正确脸/服饰/背景，在repair_source可声明preservation_regions={名称:原图整数xyxy}。范围须落在真实所选底图内；不能用较大的声明尺寸或新图尺寸代替旧底图。修复QA的repair_comparison增加preserved_observations={名称:{status,observed}}，同尺度实际比较并记PASS/FAIL。保留区不是工具执行的像素锁定，不改变修复图六项重审。

改变肢体姿态时，在repair_focus.structural_change写remove（旧结构移除）、replace（新结构）、connect（所属连接路径），三者进入实际prompt；不能只添加一条新手臂。已有错误更少、更清晰的本格原图优先，连续编辑发生退化或相同问题持续时先stop_diagnose。

返图在原repair_comparison.whole_subject_recheck记status和observed，重新核对整个人物的手/腕/袖口数量、旧结构确已移除、连接归属及承托；有structural_change而缺该实际复核不能通过。多手、错误肢体所属或整条腿扭转归limb_ownership/support输入问题，不伪装成finger局部编辑。手指局部问题只有在整体归属、动作、空间已成立时才走local_edit。


新整话再叠加[服饰与单画面](appearance-and-single-frame.md)的appearance_lock_v1/single_frame_v1。规则增加具体身体位置、当前衣装核心与可见配饰检查；衣料褶皱、自然摆动、真实反射按批准状态判断，不锁死像素位置。原局部返修与并发/预算不变。
