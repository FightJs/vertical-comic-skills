# 最终执行输入审查与接包复用

新运行声明 `input_semantics_policy=final_input_semantics_v1`，冻结能力同名。旧运行按原冻结工具/策略执行；不补造旧证据、不热改已发布ZIP。该合同扩展原 `semantic_audit_v1`，不增加第二套源稿、镜头、参考或批准账，也不新增固定人工停点。

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
