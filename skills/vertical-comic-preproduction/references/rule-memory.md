# 阶段触发的通用规则记忆

当前新任务每话一次完成A/B及全话语义核对，规则记忆按阶段与实际画面条件命中；H001/H002仅拆分生图、返图QA和返修。C覆盖第一半话，D覆盖全话；局部暂停、未变QA复用和唯一自动修正预算继续执行。旧half_scoped_v1、batch5_v1和单格RV按其原批准范围恢复。共同输入、画风、规则及逐图QA约束不变。

## 边界与读取

规则归属、正式来源与一次看图流程见 [rule-ownership.md](rule-ownership.md)。基础六项 QA 和固定合同始终执行；MEM 条目提供适用的视觉标准，技术 PASS 不能替代命中规则验收。读取扩展显式声明 `loading_policy: stage_baseline_loading_v1`，现有执行合同与原 QA 字段保留。

第三输入是用户给出的 `规则记忆路径` / 配置 `inputs.memory_root`。它只存可迁移到不同话、不同作品的制作方法、触发条件与检查动作。书名、人物名、某话服装/伤势/站位、特定剧情和某格返修记录不得入库；它们留在源脚本、资产、镜头、连续性和本次验收记录。旧目录名 `98_记忆更新` 不意味着其中内容可以复制进本库。

已存在且未声明 memory_source 的旧任务按原合同恢复。新任务使用用户配置时将同一 memory_source 写入生产流程、根全话批准镜头和每个执行包。旧任务启用记忆须建新RV并复核受影响镜头与批准。

启动读轻量索引，不全量读正文。进入阶段先运行 `load-stage`，读取该阶段 active 且 `load_policy=stage_baseline` 的正文；其余 `on_match` 条目等真实画面条件命中再读。每格仍按实际画面填 `memory_tags`（没有适用标签也要填 `[]`），逐格 `load` 取阶段基准和实际命中的并集，已读版本不重复返回正文。完整正文在每个执行 agent、本次运行、当前版本中只加载一次，阶段切换复用同一缓存；机器仍检查实际正文哈希。换 agent、新运行或上下文恢复而正文已不可用时使用新 run-id 或 `--reload`，不能凭磁盘“已读”标记假装记得。

`load_policy` 只决定何时读，不决定规则适用性。MEM-005、MEM-006 当前在镜头、生图、验收阶段预读；其他八条按命中加载。无人体的空景不会因为预读 MEM-006 就增加人体执行记录。`select`、semantic_audit.matched_rules、memory_applications 和 memory_review 仍只列真实条件命中的规则；各项检查与当前图片判据不变。输入审计与视觉资产阶段目前无基准条目，不预读上述正文；实际索引另有条目时按其 stages/load_policy 路由。

`primary_stage` 是责任阶段，`stages` 是需要执行的阶段。比如床规则归生图负责，在镜头阶段先准备站位图，生图阶段落实约束，图片验收阶段看实际结果。是否命中以当前真实索引为准；条目可声明输入审计/视觉资产阶段并由阶段执行者运行独立 check，不能只加名字却不接执行步骤。

关键词只用于召回：仅查 event_text、framing、可见人物/锚点、遮挡字段，不查对白/心声。结构已明确的可见人物、场景/锚点或道具会派生 visual_subjects_present；真实相邻关系使用同一 rule_tags 入口。人体/床/镜面等语义由执行者核对；符合床上画面就标 person_on_bed，即便只写“卧榻”。仅关键词误召回可说明原因排除；语义标签命中不能如此豁免。脚本不能证明语义分类或图片正确。

## 数据与落盘合同

各根清单顶层：

```json
{"memory_source":{"policy":"triggered_rules_v1","loading_policy":"stage_baseline_loading_v1","root":"/绝对路径/规则记忆","index":"记忆索引.json"}}
```

索引顶层 `loading_policy` 必须与 memory_source 和配置 memory.loading_policy 一致。读取扩展下每条必填 `load_policy`（stage_baseline/on_match），其他原字段 id/title/version/status/scope/primary_stage/stages/admission/trigger/requirements/file 保留。即使阶段预读也必须有非空实际触发条件；candidate/disabled 不预读、不执行。正文路径局限库内，file.sha256 绑定实际正文；rule_signature 包含读取策略及整条元数据，修改须提高 version。通用性仍需 admission.portable=true、contains_story_facts=false 及人工依据。

旧来源与旧索引均不含 loading_policy 时按原“命中才读”恢复。只在一端新增/删除字段、未知合同或规则缺 load_policy 均 HOLD；不自动探测并升级冻结任务。更新库后，旧 RV 不能通过删除字段继续用新索引。迁移在新 RV 中核验受影响版本、执行记录、例外与原批准；需要继续旧合同则使用其未改动的原索引/正文来源。不得改旧证据哈希或补造批准。

每格的 `memory_tags` 属于 B 镜头审查内容，执行包原样继承。初始标签包括 person_on_bed、multi_person_contact、camera_change；返修包另外用 `operation: repair` 自动触发 image_repair，不改剧情原文或批准标签。

单格执行记录结构（示意，哈希/证据必须真实）：

```json
{
  "memory_tags": ["person_on_bed"],
  "memory_applications": {
    "generation": [{
      "memory_id": "MEM-001", "rule_version": "1.0.0",
      "rule_sha256": "当前正文哈希", "rule_signature": "select返回的签名",
      "decision": "APPLIED", "reviewer": "实际执行者", "evidence": "当前镜头与站位图对应依据",
      "checks": {"support_surface": {"status": "PASS", "evidence": "本格具体核查依据；其余要求项也须逐项填写"}},
      "artifacts": [{"kind": "spatial_diagram", "file": {"path": "refs/站位.svg", "sha256": "实际哈希"}, "reviewed": true, "evidence": "实际核对的承托、高度、遮挡与机位关系"}],
      "prompt_constraints": ["确实出现在本格实际prompt中的约束原句"]
    }]
  }
}
```

- `shot_design` 记录在当前批准镜头的相应 panel.memory_applications 中，辅助图路径相对本话 RV 根。不能在获批文件中静默补写记录；镜头变更应刷新相应版本/批准依据。
- `generation` 记录在冻结执行包的 panel.memory_applications 中，辅助图路径相对包根。可复制同一已核对站位图到包内 refs 后记录实际哈希，不每格重画。同图复用必须说明适用性。
- 返回图的记录放 QA 报告该格 `memory_review` 数组，不使用旧 generation 判定冒充。格式同上，另必填当前 `image_sha256`。make_generation_qa.py 自动列出 UNREVIEWED 项，实际看图后填写。
- 所有 requirements.checks 都应 PASS＋具体 evidence，必需 artifacts 须存在、哈希正确且已目视核对。generation 的 prompt_constraints 必须逐句存在于实际 prompt。validate_panel 另保证提交 prompt 与文件/工具请求一致。
- 图片完整验收仍包含六项质量、相邻格/批次/跨话连续性。规则通过不替代 A/B/C/D 和新状态用户确认。
- 缺记录、版本过期、缺站位图或实际提示词未落实等返回 MEMORY_HOLD，暂停受影响格/话。缓存命中绝不自动填写 APPLIED/PASS。

全话 semantic_audit 的 checks.rule_triggers 登记准确 matched_rules=[{memory_id,rule_signature}]，共享模板按完整源格序与真实上下文生成。启用人体规则且有可见角色时填写 human_figure_visible 决定与具体依据；APPLIES须与冻结memory_tags一致。无命中也记录空matched_rules，不能泛写“规则检查PASS”。

同一 gate/批量预检进程复用索引解析与匹配，实际索引内容哈希每次核验，正文实际哈希继续检查；此缓存不保存检查结论，规则/输入变化重新匹配。make_generation_qa 的 inspection_plan 只组织一次观察，逐项结果仍写原三类 QA 字段，清单不授予放行。

## 命令

以下 `python` 指支持当前脚本且安装 Pillow 的 Python；脚本都在本 Skill 的 scripts。

```text
python <scripts>/rule_memory.py --root <规则库绝对目录> --loading-policy stage_baseline_loading_v1 --mode validate-library
python <scripts>/rule_memory.py --root <规则库绝对目录> --loading-policy stage_baseline_loading_v1 --stage generation --mode load-stage --cache <本次工作目录>/cache/<run-id>/<worker-id>.json --run-id <本次运行ID> --worker-id <实际执行者ID>
python <scripts>/rule_memory.py --root <规则库绝对目录> --loading-policy stage_baseline_loading_v1 --stage generation --manifest <冻结执行包JSON> --panel-id <真实格号> --mode load --cache <同一缓存JSON> --run-id <同一运行ID> --worker-id <同一执行者ID>
python <scripts>/rule_memory.py --root <规则库绝对目录> --loading-policy stage_baseline_loading_v1 --stage generation --manifest <冻结执行包JSON> --panel-id <真实格号> --mode select
python <scripts>/rule_memory.py --root <规则库绝对目录> --loading-policy stage_baseline_loading_v1 --stage generation --manifest <冻结执行包JSON> --panel-id <真实格号> --mode check --artifact-root <执行包根>
```

load-stage 不接收单格输入，返回 matched_for_execution=[]，memories 的 read_reasons=stage_baseline 仅记录读取理由。逐格 load 的 matched_for_execution 才列实际命中，stage_baseline/matched_condition 可同时成立。READ_REQUIRED 返回实际正文，CACHED_IN_THIS_RUN 仅说明同一缓存已返回过该版本；两者都不批准图片。旧库命令省略 --loading-policy。

新合同优先用 manifest/panel-id，来源必须与冻结 manifest 完全一致，并从真实前格派生标签；没有前格上下文的单格方法不替代全包连续性检查。panel 参数是单格对象，不是含 panels 数组的整包。shot_design 的 artifact-root 为本话根；image_review 独立 check 需把 QA 记录映射到单格 memory_applications.image_review 并提供当前 image_sha256，日常生产直接运行 staged_workflow 完整门禁。缓存各 worker 单写，不能放规则库或覆盖输入；阶段入口与逐格读取共用缓存，不每阶段创建新 run-id。

## 写入与迭代

生产 agent 对规则库只读。新失败留在本次 QA/修复记录，不能自动追加通用记忆。确有迁移价值时，先去掉全部作品/人物/话格事实，形成规则提案，再经用户授权维护规则库。新增规则先 candidate，完成通用性、冲突、触发与误触发检查，再明确启用为 active；停用保留版本记录，设 disabled。

修改正文或触发/要求时更新 version、重新计算正文 sha256，运行 validate-library，再用命中与不命中样例验证。维护修改不要发生在未协调的在途请求中；总控冻结当批规则版本，先收回在途结果，改版后只重新审核受影响结果及下游批准。

记忆是补充规则，不可覆盖当前用户明确指令、锁定脚本或批准资产。发现冲突记录依据并交总控按授权范围处理；不能以规则名义擅改剧情/风格。不得把计划图当风格参考，不得虚构工具支持硬位置控制。

v2真实上下文派生相邻/脸部可比标签参与镜头、生图、实图验收匹配。实际用户批准的单格例外放本次生产文件，绑定规则版本和源文哈希并验替代判据；通用库保持只读。 详细字段、命令和恢复规则见 [生产兼容与提速](execution-compatibility.md)。
