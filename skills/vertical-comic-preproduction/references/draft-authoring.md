# 第二批提速：唯一主表、增量派生与少冻结

仅在声明支持panel_authoring_source_v1的新运行使用。已有冻结RV不自动迁移、不覆盖原工具/批准/在途账本。先完成第一批的最小充分设计和代表格接口，随后保持每话一份可编辑主表；草稿编辑不创建新冻结运行、不重新索取A/B批准。调用和正式交接仍绑定准确输入版本。

## 主表职责与接线

主表只维护创作事实，不保存调用结果、QA结论或用户批准。主表policy为panel_authoring_source_v1，status为WORKING_DRAFT；source_snapshot绑定原始源稿哈希，run_root写本话工作绝对目录，panel_ids沿原序。panels每行含：

- panel_id；shot为原镜头记录，包含原文、身份/衣装、场景、动作/构图、连续性与风险；
- execution为实际包中不属于shot的输入字段，不得重复维护同名字段；packet_header保存原逐格包头部；
- shared为共用结构库，`{"$shared":"键"}`引用准确对象，identity_registry、visual_evidence_context、memory_applications、style_contract等可集中维护；派生时展开到原合同字段，实际prompt也展开适用规则和配饰位置约束；
- render_mode为structured_v2或preserved_import；dependencies登记确实影响输入的格ID，dependency_queries登记额外文件/目录查询。默认不增加相邻格串行依赖；需要相邻机位上下文时显式设置neighbor_context=true。

新内容直接在此主表创作，不先独立写镜头/提示词/审查表三份材料。已有未生产的候选可以一次导入；冲突字段先消解，不任选其一。导入拒绝有输出、在途或未知请求的生产记录，不把旧生产复制成新任务。

```text
production_runtime.py --state <状态> --action authoring-import --write <本话主表.json>
production_runtime.py --state <状态> --action draft-plan --panel-source <主表.json> --previous-derivation <上次派生记录.json> --write <变化范围.json>
production_runtime.py --state <状态> --action draft-derive --panel-source <主表.json> --previous-derivation <上次派生记录.json> --derivation-output <本话内新工作目录>
```

首次plan/derive省略previous-derivation。也可直接用panel_source.py、panel_derivation.py CLI，参数见help。新建主表遵守上述字段和现有镜头/包合同；执行者按本话实际字段填写，不要求使用者手写JSON。

structured_v2复用原v2确定性prompt编译函数与身份、物理优先级、画风和配饰执行块。机位角度/景别/比例、摄影机位置/朝向/高度、可见区域和镜头签名须明确，工具不猜缺项；从主表变更这些值后重新派生，不再手改输出prompt.txt。required_reference_aliases可显式选择本格必要参考；遗漏必要画风/人物/状态引用仍会被原门禁拒绝，不按五张预算截断。

preserved_import只保留已导入的实际文字，不冒充结构化重编译。创作输入变化后须切换structured_v2，或先由执行者实际编译并消解旧候选再重新导入。不能修改import_panel_key绕过检测，也不能把保留旧文字称为自动改好新镜头。导入不会新增任何用户审核节点。

## 派生与增量范围

工具产出镜头派生.json、每个变化格的manifest.json/prompt.txt/negative_prompt.txt、审查展示.json、工作绑定计划.json和派生记录.json。未变化格复用已核对文件哈希的原派生产物；不把所有旧文件复制到每个新目录。主表可编辑，派生目录是可丢弃的工作输出，不是批准或冻结版本。

工作绑定计划列准确新镜头与逐格包引用；执行者把引用同步到本话工作状态与真实语义审查，再使用原preparation-review入口。派生本身不改正式状态或伪造审查，原批准版本不覆盖。跨版本引用、缺少的审查和技术字段由当前执行者在原授权内闭合，不要求用户再批准绑定。

依赖指纹包含实际使用的主表字段/共享对象、工具版本、引用文件内容和传递JSON引用，以及明确声明的目录查询。缺文件也有观察记录；引用或符号链接目标变化使复用失效。目录扫描登记成员和文件内容，带符号链接目录改为明确文件查询；不在计时器上扫描。共用对象变化影响所有实际引用它的格；同衣装、场景或跨话上下文必须通过状态对象/文件引用绑定，不能只靠口头说“同上一话”。

重编译范围沿generation_dependencies、design_dependencies和显式dependencies传播；previous_panel_id仅作为比较关系，产生comparison_only_panel_ids并加入review_panel_ids，不因此重编译后续整话。普通相邻格不自动纳入；只有neighbor_context明确将邻格内容写入实际输入时才建立对应输入依赖。无法证明局部影响时保守扩大范围，不能提前放宽依赖。旧派生文件损坏、缺失或未完成也重新派生；失败格及其依赖保持pending，其他独立格继续。派生结束复核读取快照，发生变化则不发布成功回执，不重发生图。

input_semantics.py --state <状态> --panels <实际影响格...> 可仅核对选集，返回SCOPED_INPUTS_REVIEWED；不能当作整话通过。不带--panels仍全范围核对，正式冻结/接包沿用此路径。缓存只复用派生文件和原事务内计算，不跨命令缓存PASS、批准或实图QA。

## 参考与规则复用

规则在shared中集中登记，rule_memory按本格适用项编译具体约束，实际prompt保留完整执行文字。配饰的身体侧/位置/数量/遮挡仍由原appearance_lock编译，不因复用省略。

参考优先选实际可见且有明确职责的原资产。确实需要技术图集时：

```text
production_runtime.py --state <状态> --action draft-atlas --atlas-spec <来源裁区JSON> --atlas-cache <技术缓存目录> --write <图集候选引用.json>
```

spec.regions每项包含subject_id、asset_id、purpose(identity/costume_state)、source_file(path/sha256)、crop_rect_pixels，可带source_version。仅按原像素纵向拼接，不缩放、不重绘；按来源哈希、裁区、顺序、布局及工具版本复用。输出reviewed=false，原归属与可读性审核仍实际执行，不能把cache_reused当审图通过。超大图集要求减少实际必要区域，不无限堆参考。

## 少冻结与持续执行

工作阶段只改主表及真实受影响范围，不因普通字段同步、文案润色、展示格式改变就创建整套冻结快照或重新批准。冻结运行在启动时建立一次；实际调用绑定该attempt的实际prompt/参考/参数，正式交接再形成准确不可变版本。已调用/已批准版本保留，不用覆盖方式“回退”。

总控不因DRAFT_PARTIAL或普通警告结束轮次：先处理独立格，再按errors/pending闭环。共因可用task_coordination的work事件记录一次，work_id稳定复用，scope写实际范围，next_action写可执行动作；OPEN重复两次标记common_cause_diagnosis_due，应停止重复同一路径、集中诊断，而非再生一遍或问用户。RESOLVED引用现有实际修复证据；只有明确可选建议可blocks_delivery=false。不是每格强制增加一份工作项证明。

生产指标可附--draft-receipt <派生记录.json>和--atlas-receipt <图集操作回执.json>（可多次），报告实际编译/复用/同输入重复编译、图集新建/复用及已观察耗时。没有记录的审查复用、图集操作和等待时间保持未知，不填0，不把减少文档数量宣称成实际整体提速。

能力边界：本工具不保证宿主自动唤醒；无已验证自动化时，总控保持当前轮次协调到交付。任务未完成但存在可执行工作，进度消息后继续，不等待“继续”。
