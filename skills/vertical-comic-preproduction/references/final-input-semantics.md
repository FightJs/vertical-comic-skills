# 最终执行输入审查与接包复用

接包用途优先按[免外部配置接包](quick-start.md#接包生产免外部配置)路由：只提供正式包路径及可选输出位置，书话/脚本依据/必要资产从包内读取，不进入首次前期配置、prepare或主表重建。历史usage_config_path只作来源记录；接收与生产不重新加载前期电脑配置。环境、有效生产授权、真实依赖及包内审核合同仍适用。

新运行优先按[第一批前期提速](preparation-efficiency.md)执行最小充分设计、代表格接线、单次B/包展示及问题分级处理。可选润饰不产生HOLD；真实缺口在现有委托内修复，局部问题只影响真实依赖，其他工作继续。正式输入与接包要求仍按原合同。

新整话运行默认声明 `input_semantics_policy=final_input_semantics_v2`，冻结能力为prepared_panel_inputs；已有v1继续原语义审查合同。旧运行按原冻结工具/策略执行；不补造旧证据、不热改已发布ZIP。该合同扩展原 `semantic_audit_v1`，不增加第二套源稿、镜头、参考或批准账，也不新增固定人工停点。

## 阶段与闭合顺序

1. 输入审计/A：锁定原文与参考用途。身份板的姿态、表情不覆盖源稿明确状态；缺必要资产在A解决。
2. B：在既有逐人物记录中明确状态、可见面、裁切下沿与必要手势。先检查设计可实现性，再编译实际包。
3. 实际包：读取最终请求的完整prompt、参考数组/顺序/用途及检查判据，完成逐格最终输入审查。候选输入不是提交许可。
4. 合并审查：准确差异、B与实际包一起展示，分别记录决定；可合并取得输入不变且演练通过后的导出授权。
5. 冻结/交接：全话准备及最终输入审查覆盖完整，再全新目录解压、bind、冻结门禁演练、正式发布。技术PASS与执行者语义审查分别记录；两者均不替代用户批准或实图QA。
6. 接收：校验包与本机路径，核验原审查绑定。未变内容复用已有审查；实际输入变化、新补实图或新发现异常只复查对应格及真实依赖。

## 逐人物设计字段

在当前镜头添加 `semantic_facts` 和 `subject_visibility`，执行包原样携带；确无明确状态可用 `semantic_facts=[]`，无人可见使用空visibility。不得默认套用专注、闭嘴、眼睑略收。

`semantic_facts` 每项包含 `subject_id`（原character_id）、`subject_name`、`instant="current"`、`attribute`、`value`、`source_quote`。source_quote必须是本格locked_script中的准确原句片段。字段只标注原文，不复制/改写源稿。当前机器枚举：eyes=wide/narrow/half_closed/closed，mouth=parted/closed，focus=focused/unfocused，face=visible/hidden。其他自然语言状态保留原逐人物描述并人工核对，不能强套枚举。镜中本格反应属于当前所绘瞬间；过去状态不要混作当前事实。

`subject_visibility` 按character_id记录 `subject_name`、布尔 `face_visible`、布尔 `identity_observable`、具体 `evidence`。每个on_screen人物都须记录。肩背/后脑可辨身份时，face_visible=false而identity_observable可为true；不能因此取消身份、衣装或发型QA。面部部分可见时，只要求可见五官；adjacent_face_comparison仍逐人物判断，不从布尔值自动授予表情比较通过。

裁切继续使用framing、visible_region与逐人物裁切。胸上却必显腰部或自然垂手指尖须先修镜头；需要下沿到上腿可用现有mixed并明确每人的边界，无需把所有半身扩大成全身。源稿与已批准镜头发生真实冲突时列准确变更并按原授权处理，不由编译器自行取舍。

## 原语义记录中的最终输入审查

每格增加 `execution_review`：policy、input_digest、status、reviewer、evidence、checks，以及可选unresolved_issues。模板status=UNREVIEWED；实际审完才填REVIEWED。checks各项须有PASS和具体观察依据：

- source_and_expression：源稿明确状态与最终文字一致；沉默不等于闭嘴，失焦不等于专注。
- crop_and_required_information：上下沿、逐人物范围、手势/指尖/物件/接触均可容纳。
- per_subject_visibility：不要求不可见五官，不混淆身份与面部可比较性。
- action_and_space：肢体任务、动作瞬间、站位、承托、遮挡、反射与机位相容。
- actual_references：实际看过输入图片及必要裁区；角色、衣装、场景、画风的用途、顺序和限定范围适用。
- all_execution_text_and_criteria：完整prompt的规则/参考块、逐格JSON与QA判据没有旧的反向要求。

只核文件名或填写通用“全部一致”不能代替实际审查。机器只能验证摘要、完整性和少数明确冲突；未命中冲突不等于语义PASS。自动检测避开否定、前后瞬间、无法准确归属人物的句子，这些仍由执行者阅读。

摘要绑定源文字、逐格设计、视觉基准、规则索引、冻结工具/Skill内容、最终prompt、规格、真实参考内容/顺序/职责及执行判据。地址只在可验证内容引用中归一化，任意绘图文字中的路径不被随意删除。批准记录、回执和审查自身不进入输入摘要，避免哈希循环。原批准和撤销状态仍由原门禁实时核对。

使用包内冻结Python/脚本生成新的未审模板，命令中的路径替换成本次真实值：

```text
python -B scripts/input_semantics.py --state <本话根/00_输入审计/生产流程.json> --output <本话根/00_输入审计/最终输入审查候选.json>
```

该命令读取现有semantic_audit并扩展选中行，保持设计审查不变；不修改状态引用，不生成批准或图片。用`--panels P009`只重新准备变更格。执行者实际审查后保存新版本并明确更新状态semantic_audit引用；再编译全话审查包和准确批准材料。不得在审查后追加未经核对的prompt块。

## 正常实图依赖

前期用`--dependency-plan <相对本话根的补齐方案.json>`读取原补齐方案。每行除已有arguments/reference_files/output_spec外，须带实际reference_bindings和`reference_path_basis="run_root"`；固定参考使用相对本话根的包内路径，bind后按新根解析，不能引用前电脑绝对地址。固定参考是真文件，前置槽仍是`@DEPENDENCY:Pxxx`，不用占位PNG。静态计划及允许替换范围完成execution_review，标记待生产的真实参考审查。

前置图经适用QA/人工确认后，按已批准补齐方案替换实际参考，在原审计行追加 `dependency_completion_review`。使用`--completion --panels <准确格号>`为真实最终请求生成未审模板；审新图内容、参考职责、顺序及实际请求。静态计划的审查继续保留，原dependency_plan_matches仍校验允许变化。路径替换不自动变为新的画面设计批准，超出范围须走变更流程。

原自动返修仍限一轮。返修实际包与初始包不同，也必须核对修复目标、保留区域和最终实际输入；不能复用初始input_digest冒充返修输入已审。新审查不重置原预算。

## 导出与接收

交接验收索引每话增加input_semantics_policy及semantic_audit文件引用；全话实际包带同一审查引用与final_input_semantics覆盖结果。正式发布要求所有源格前期审查闭合，正常实图依赖单列；H001可启动不能替代H002前期完成。审查UNREVIEWED、失效摘要、未解决冲突只能交诊断候选。

接收仍校验文件/发布证据、bind、本机冻结门禁。receiver-audit在一个读取事务内核验H001、全话准备、全话输入及前期语义证据；它不生成图片、不授予容量/调用许可。运行地址变化且内容相同不要求用户重批。预算、未知结果、批准撤销及半话窗口仍实时检查。

设计或实际输入有变化时先明确受影响内容，再重编译相关逐格包、全话引用和上下文，核对语义证据。更新全话文件引用不等于每格改设计；真实依赖阻塞不等于依赖格存在设计错误。生产保留高风险实图、H001后H002、D及跨话审核，不拼接或加气泡。

## 前期收敛、按包执行：v2

前期依次完成原稿瞬间与人物分析、实际资产观察、镜头及物理可行性、连续性分类、适用规则、最终prompt/参考与审核目标。所有指定格的静态工作须闭合才可正式交付前期包；真正等待未来实图的格保留精确补齐方案，不能把未定动作、缺衣装或未选规则伪装成实图依赖。连续制作仍可逐格放行，不让局部缺口停止其他已获准的就绪格。

不新增第二套设计记录。input_semantics.py从原shot、visual_basis、memory_applications和实际输入派生preparation_targets，绑定在execution_review.input_digest内，并为原审查增加三个未审项：

- continuity_and_dependencies：检查连续性不变量、允许变化、实际generation_dependencies与只在验收比较的格。需要前图作输入时，在原continuity_contract.generation_dependency_reasons中按准确依赖格号写用途和必须等待的原因；键须与generation_dependencies完全相同，无实图依赖用空对象或省略。只需保持衣装/配饰/空间的格不因此增加图片依赖。
- rule_execution_coverage：展示shot_design/generation/image_review的实际命中规则、版本、命中原因及原检查键；generation应用记录须有准确APPLIED或合法NOT_APPLICABLE。需要绘图约束的规则用原memory_applications.generation[].prompt_constraints写本格具体要求，必须进入实际prompt。通用规则正文、审批记录及纯审核流程不整段塞入提示词。审查者还须检查是否漏掉实际风险，机器匹配不能证明规则已经齐全。
- appearance_anchors：从批准appearance_details和当前detail_visibility带出款式、人物/衣装归属、总数量、身体自身侧、部位、手指、锚点、附着方式及本镜头投影/遮挡；逐项检查实际输入是否正确表达。反打和反射只改变投影，不能改变佩戴侧或衣装状态。

每项expected由工具生成，执行者实际审查后填写PASS和具体evidence；模板不批准、不生图。expected缺项、改写或输入变化都不能沿用旧审查。普通图片仍走原六项与规则QA；新增审查不是新增用户亲审停点，准确委托与保留亲审项沿grouped-review.md。

依赖计划仍使用原槽位格式，v2计划可以携带memory_applications供generation规则检查；缺省时使用本格原记录。静态prompt必须已经含具体空间、服饰和规则约束。真实依赖补入后按原允许范围核对新图与职责，填写dependency_completion_review，不重做未变化设计，也不把批准槽位当成任意换图许可。

生产compile原样导出包中的prompt和实际参考，附prepared_input_digest用于核对输入来源；摘要属于回执元数据，不进入绘图文字，也不是生产许可。取消、批准撤销、容量、预算、在途状态与真实文件仍实时核验；本事务复用原检查结果，不新增跨命令永久信任缓存。任何绘图文字的临时追加须更新包并重做受影响输入审查。

返图后的inspection_plan引用原规则执行约束、配饰锚点/可见数量与原QA位置，帮助执行者按前期目标观察，不自动填PASS。输入错误修对应包并重新审查；执行偏差按批准方案限定修图；工具未知结果查原请求。修正只影响相应格及真实依赖，原自动返修次数、旧图和失败记录保留。

旧RV使用冻结入口；迁移需新候选、历史及未知请求核对和准确授权。不能只改input_semantics_policy、复制v1的PASS到v2或重签旧输入。交接同时支持v1/v2，保留准确策略；新能力不自动启用短锁。


## 批量制作前先走真实入口

新批次在铺开逐格包前，先从本次真实脚本选能覆盖主要接口的代表格：多人/配饰与裁切、连续场景，以及存在时的跨话末格→首格。用同一份 A、镜头、参考与规则完成实际 prompt 编译、原语义审核及完整候选门禁；不要先批量复制尚未走通的字段结构。全话源序先建齐，其他格明确保持未完成，不能为了测试样例填假设计或 PASS。样例通过只是接口验证，不替代其余格的逐格准备。

使用现有真实入口（`--panels` 为准确样例格号）：

```text
python <本次快照scripts>/production_runtime.py --state <本话生产流程.json> --action compile --candidate --panels P001 P002 --progress
```

按编译结果中的 `preflight.reports`、实际 `jobs.arguments` 和待补项核对；图片可解码/哈希一致或 `validate_preproduction.py` 局部 PASS 均不能代替完整入口。尚无语义审查时先用原 semantic_template 生成未审模板，执行者实际检查后补记录，不复制通过值。代表格遇到缺字段或接口限制时先修好共同来源，再批量制作；不反复拷贝整套 RV 调试。

正式前期 ZIP 仍须在新位置执行完整 bind/rehearse。只有最终 B/包批准和正式导出证据齐全才可发布；未批准的代表格不伪装正式接包包。跨机路径可先用候选副本搬移验证，再在最终包完整复演。技术诊断只标“局部检查/完整候选编译/冻结接收演练”中的实际范围及数量。

## 前期权限与同批候选上下文

新工具支持 `preparation_authorization_v1`。收到用户明确的前期制作请求后，将**已有原话**一次记录在状态的 `preparation_authorization`：`policy`、`phase=preparation`、`status=APPROVED`、`source_kind=user_message`、真实 `source_locator/quote`、准确书话与 `panel_ids`、绑定 `source_script/source_snapshot` 的 `artifacts`，以及指向原请求记录的 `evidence={path,sha256}`。证据内原话、来源和来源类型须一致。状态表示前期请求范围已确认，不表示 A/B/包或正文获批；不要为已有明确请求再增加用户确认。

此记录只在候选编译/全话候选包/只读接包输入审计中替代正文生产授权检查；其他 A、源序、输入、规则、语义和预算检查照常。`candidate_only` 或 `input_audit_only` 的 job 一律 `dispatch_authorized=false`。正式领取、普通编译及提交仍核验独立 `production_authorization`；内部领取预检使用 candidate 参数不等于前期权限。没有前期记录的旧运行继续原规则，不静默迁移。

同批跨话候选复用原 `continuity_sources` 和 `approved_shot_context_v1`，不另造批准台账。来源使用 `approval_resolution=source_runtime_gates_v1` 与真实 `source_state_file`：

- 两话必须属于同一初始化 task_context、准确话序，且各自已有准确前期范围授权；来源必须在当前状态明确登记，四个源输入引用精确匹配。
- 只读候选上下文允许来源 B 未批准；来源 A、真实源稿与完整连续性检查仍须通过。普通编译、领取和接包审计不会借此免除 B。
- 候选审查上下文覆盖公共准备检查和逐格检查，离开入口后立即结束；输入/来源/授权变化使缓存失效。
- 可移植 `continuity_sources.root` 以本话根为基准，写 `root_mode=context_relative_v1`；context 文件中的来源根以该 context 文件目录为基准。使用 `continuity_context.build` 和 `portable_context`，按解析后的来源及准确证据比较，不能仅靠绝对路径字符串或改哈希伪装同一来源。

版本变化时区分创作内容与引用地址：沿用现有逐格设计签名、原批准覆盖与语义摘要判断受影响格；来源记录、实际 prompt、参考或判据变更的格必须重审。仅更新汇总引用不要求重写无关格，也不能沿用已经不匹配的摘要。补齐共性结构后集中编译一次，按相同错误原因归组解决；不要逐格重复修改同一工具。


前期耗时控制沿[减少重复检查与版本返工](runtime-efficiency.md#减少重复检查与版本返工)：使用现有批量入口，在准确依赖范围修输入、重建未审模板和复核，不为进度汇报重做同版技术检查。

## 具体输入疑点复用原审查

scoped_input_signals只把场景固定描述中的双手承托与本格肢体任务、动物体表与人体衣装模板的具体可疑片段送入原all_execution_text_and_criteria.expected，不新增审核项或模型调用。疑点不是自动FAIL；本项evidence解释修订或不冲突的依据，不能用其他项相同的笼统PASS代替核对。没有信号不代表所有语义正确。场景布局字段只保存固定空间，人物动作与承托写本格任务；自然体表描述不能套用人体衣装属性。批准动物确实穿衣时按真实参考保留。可在appearance_details明确subject_kind=animal、clothing_applicable=false；此时确切的人体领口肩袖模板会报错。修复发生在前期来源属性，不只删除成品prompt字词。

## 空间输入收敛

新任务相关格按MEM-003/006/009选择必要空间关系，字段见[空间扩展](schemas.md#按格空间关系与投影绑定选择式扩展)。普通格不强加结构图或空景。完整实际输入审查沿action_and_space、crop_and_required_information及all_execution_text_and_criteria执行：核对机位、blocking、逐人物动作、背景、衣装配饰投影是否为同一瞬间和同一位置依据。共享衣装不携带上一格人物站位。

改变机位、取景或动作后同步复核可见性、配饰投影及关系选择，再派生所有受影响文字段；不在末尾追加相反命令。结构化重复来源冲突/旧投影签名由spatial_contract检查，自由文本疑点由scoped_input_signals定位；提示信号不是自动FAIL，也不能自动重签。preserved_import保持原始文字，改动须明确重新编译。只重检受影响格及真实依赖。

承托名称有歧义时在本格依据中解释实体表面；空间未知但非必要的区域允许不展示。必要剧情与批准空间不能同时成立时按原权限处理准确范围，不让生成自行改建筑或动作。

新版整话交接在handoff_zip.py pack创建压缩文件前，以正式模式解析每格前序上下文批准；沿用原单项证明、原证明集合和运行批准解析，不把shot_approval为空直接判错。缺正式覆盖时返回FORMAL_CONTEXT_HOLD及准确话/格，不写ZIP。该检查只前移引用闭合，搬迁后仍执行原正式接收演练。
