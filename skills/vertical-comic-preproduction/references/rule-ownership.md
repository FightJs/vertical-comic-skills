# 规则归属与一次看图

首次进入当前运行读取本表一次；阶段切换读相应合同及阶段基准，专项正文按真实条件补读。读取扩展显式声明 stage_baseline_loading_v1；triggered_rules_v1 的执行匹配和原六项 QA 格式保留，不增加人工审查点。

| 内容 | 正式来源 | 执行入口 |
|---|---|---|
| 源稿锁定、参考依据、整话流程、人工审查、修正次数 | production-foundation.md、staged-workflow.md | 各阶段 Skill 与完整 staged_workflow 门禁，始终执行 |
| 格数/原序、文件哈希、实际输入、调用证据及版本 | 共享检查器代码与对应输入输出合同 | validate_preproduction、codex_reference_contract、execution_contract 等技术检查 |
| 按冻结审核模式检查实际图片 | reference-continuity.md、style_contract.py 与批准的逐格判据 | light_story_review_v1按light-review.md一次快速观察；仅全面审核使用dimension_review、style_review及六项检查 |
| 跨话跨作品的通用视觉标准 | 新任务默认总控assets/rule-memory内置+用户增补的合并索引与正文；显式memory_root/旧RV按原来源，均由哈希/签名绑定 | rule_memory.load-stage/load 管读取，select/check 管实际适用与执行；镜头、生成和实际图片验收分别落实 |
| 人物状态、房间布局、剧情、某格修正及用户例外 | 当前源稿、资产、镜头、QA 和原用户批准证据 | 当前生产 RV；不写入通用记忆 |
| 输入冲突时的处理顺序及可调整范围 | production-foundation.md 的 `physical_scene_priority_v1` | 输入审计、镜头、提示词编译与原 QA；不代替各 MEM 的实际判据 |

一条通用规则只维护一个 MEM ID 的正式正文；索引存机器可核对的阶段、触发、check ID、版本及正文哈希，正文解释具体可观察判据。Skill 和质量说明通过 ID 引用，不各自再写一套相反标准。技术代码负责结构与证据核验，不能凭 PASS 宣称自然语言或图像已经正确。

## 镜头规则与旧文档

相邻镜头以本批冻结的MEM-010版本为准：v2允许有叙事依据的同景别正反打与连续近景，优先保持物理连续性；旧v1冻结任务保留原双变化要求。MEM-007 负责实际可比较的相邻脸部微表情，MEM-003/005/009 负责各自空间、连续性与遮挡要求。具体判据和版本以本次实际索引/正文为准，本表不复制它们。

当前用户明确指令优先。源稿/批准状态与通用标准冲突时保留原文，集中处理受影响格；适用的原批准例外必须准确绑定规则版本、源文、格子和替代判据。规则并不授权改剧情、放宽裁切、移动家具或扩大批准。

## 触发覆盖

下面是前期规则选择与全面QA的覆盖要求；轻审核返图不补逐MEM记录或六项检查。基础六项 QA 不依赖记忆标签。结构上已明确可见的人物、背景锚点、场景或道具会派生 visual_subjects_present；真实前格派生相邻关系，可比较脸部由已有批准的比较记录确定。返修由 operation=repair 触发，不修改获批镜头标签。

人体、床、镜面、复杂肢体关系等语义不得仅凭角色 ID 或对白猜测。新任务全话 semantic_audit 中 rule_triggers 保留准确 matched_rules（memory_id/rule_signature），模板从当前命中集生成且不填 PASS；旧RV按原半话审计范围恢复。库中启用人体规则且本格有可见角色时，另核对 human_figure_visible：decision=APPLIES/NOT_APPLICABLE 与具体 evidence。APPLIES 必须与获批 memory_tags 一致；人手/局部人体仍适用其可见部分，不因脸在画外而排除。非人体角色等真实不适用情形说明依据，不能由脚本把所有角色默认当人。

阶段基准预读和是否实际执行分开。当前 MEM-005/006 按其 stages 预读一次，其余条目按命中读取；未命中者不新增执行或验收项。semantic_audit 只用轻量索引核对实际命中覆盖，执行者仍要检查语义分类；机器无法证明其自然语言判断正确。每格没有命中也保留 memory_tags=[]，不删来源跳过检查。完整字段与命令见 [rule-memory.md](rule-memory.md)。

## 全面审核的一次观察（仅full或原冻结合同）

make_generation_qa 生成 inspection_plan，将原基础 QA、命中 memory_review 和例外替代检查按观察对象组织。它绑定实际图片和源执行包，仅用于安排一次看图；status 初始 UNREVIEWED，不参与放行。

打开当前原图、批准参考及必要的真实前格，一次观察覆盖所有适用目标。原 style_review、dimension_review、memory_review、手工可见性检查仍逐项记录判据和具体证据。相同观察可写入多个确实被它证明的项；身份通过不证明道具通过，生成前记录不证明返回图通过，未观察项不自动填 PASS。清单显示 PASS 也不能覆盖原字段的 FAIL/UNREVIEWED。

## 复用与版本

同一 gate/批量预检进程按实际索引内容哈希复用解析和匹配；选择缓存只记命中集，不缓存检查结论。正文在同 agent/运行/版本中按既有 load 缓存复用，实际哈希仍校验。图片、前格、输入、规则版本或判据变化时由内容绑定 QA 复用检查失效，重新核对受影响项。

维护前先归类，再修改正式来源；重复方法合并既有规则。当前规则版本以实际索引为准；读取策略不授予画面通过，也不改变并发额度。旧 RV 保持原证据，升级在新 RV 核验工具版本、规则签名及受影响依据，不改旧哈希或补造批准。

visual_evidence_v1负责把本话具体布局、状态、细节预期和图片观察绑定到现有记录；通用方法继续以MEM-002/003/004/005/006为正式来源。生产只读规则库。本次维护更新规则版本后，旧RV须用原工具/规则快照恢复或显式迁移，不能重签旧哈希。

物理与连续性方法分别维护在MEM-001/002/005/006/009，MEM-010 v2维护叙事驱动的相邻镜头判据。提示词模块在prompt-package.md，背景字段合同在shot-framing.md/schemas.md；编译器只查执行文字与依据一致性。生产只读规则库，冻结旧RV不自动重签或迁移。

最终prompt与全部执行判据的一致性由[final-input-semantics.md](final-input-semantics.md)维护，input_semantics.py验证内容绑定和少数确定矛盾；仍由执行者逐格阅读与看参考。MEM-007负责表情变化原则，不负责给每格指定专注/闭嘴等默认状态。

## 按任务读取，不全量加载

- 授权与取消停点：读[合并审查](grouped-review.md)，最新明确委托按原范围覆盖旧停点；脚本优先及最少询问的具体边界均在该处。
- 总控启动、恢复与中途进度：读[进度](review-progress.md)和[恢复](task-recovery.md)；阶段完成不冒充整个任务交付，仍有可执行工作时继续。
- 新任务输入审计：读[输入审计](stage-input-audit.md)；只查本次来源和实际需求。
- 字段查询与失败定位：按需查[数据合同](schemas.md)和[质量门禁](quality-gates.md)，不把这些文档重复抄入每格。
- 用户需要调用示例：读[使用指南](usage.md)。确需补资产时读[资产细节](asset-production.md)；叙事表达难题查[编剧方法摘录](screenwriting-distillate.md)。
- 只有旧包迁移或修复才读[旧包修复](legacy-package-repair.md)、[返修合同](repair-contract-v2.md)和[旧提示词阶段细节](stage-prompt-package.md)；这些文档不能替代当前整话流程。
- 新版分工和接包统一使用[整话交接](split-production.md)。旧半话规则只按已验证旧包及原冻结版本启用，不因分工自动回退。

## 空间规则的选择与执行

MEM-003维护固定结构/唯一机位，MEM-009维护叙事与展示取舍，MEM-006维护真实承托，MEM-004维护有限返修。新相关格沿schemas.md的selected_relation_ids选择关系；各阶段只读取命中规则。spatial_contract.py共用选择、投影版本与返修范围核验；它不读像素、不替代语义审查、不新增用户停点。具体场景事实留RV，生产规则库只读。
