# 规则归属与一次看图

首次进入当前运行读取本表一次；阶段切换读相应合同及阶段基准，专项正文按真实条件补读。读取扩展显式声明 stage_baseline_loading_v1；triggered_rules_v1 的执行匹配和原六项 QA 格式保留，不增加人工审查点。

| 内容 | 正式来源 | 执行入口 |
|---|---|---|
| 源稿锁定、参考依据、半话流程、人工审查、修正次数 | production-foundation.md、staged-workflow.md、half-episode.md | 各阶段 Skill 与完整 staged_workflow 门禁，始终执行 |
| 格数/原序、文件哈希、实际输入、调用证据及版本 | 共享检查器代码与对应输入输出合同 | validate_preproduction、codex_reference_contract、execution_contract 等技术检查 |
| 基础图像质量：身份、衣装、动作、空间、构图、画风 | reference-continuity.md、style_contract.py 与批准的逐格判据 | 原 dimension_review、style_review 及六项实际看图检查，始终执行 |
| 跨话跨作品的通用视觉标准 | 用户指定 memory_root 的实际索引与 MEM 正文，二者由哈希/签名绑定 | rule_memory.load-stage/load 管读取，select/check 管实际适用与执行；镜头、生成和实际图片验收分别落实 |
| 人物状态、房间布局、剧情、某格修正及用户例外 | 当前源稿、资产、镜头、QA 和原用户批准证据 | 当前生产 RV；不写入通用记忆 |
| 输入冲突时的处理顺序及可调整范围 | production-foundation.md 的 `physical_scene_priority_v1` | 输入审计、镜头、提示词编译与原 QA；不代替各 MEM 的实际判据 |

一条通用规则只维护一个 MEM ID 的正式正文；索引存机器可核对的阶段、触发、check ID、版本及正文哈希，正文解释具体可观察判据。Skill 和质量说明通过 ID 引用，不各自再写一套相反标准。技术代码负责结构与证据核验，不能凭 PASS 宣称自然语言或图像已经正确。

## 镜头规则与旧文档

当前库启用 MEM-010 时，相邻镜头按该规则及原范围用户例外执行；旧“同景别正反打可直接通过”的说明仅属于其原冻结合同。MEM-007 负责实际可比较的相邻脸部微表情，MEM-003/005/009 负责各自空间、连续性与遮挡要求。具体判据和版本以本次实际索引/正文为准，本表不复制它们。

当前用户明确指令优先。源稿/批准状态与通用标准冲突时保留原文，集中处理受影响格；适用的原批准例外必须准确绑定规则版本、源文、格子和替代判据。规则并不授权改剧情、放宽裁切、移动家具或扩大批准。

## 触发覆盖

基础六项 QA 不依赖记忆标签。结构上已明确可见的人物、背景锚点、场景或道具会派生 visual_subjects_present；真实前格派生相邻关系，可比较脸部由已有批准的比较记录确定。返修由 operation=repair 触发，不修改获批镜头标签。

人体、床、镜面、复杂肢体关系等语义不得仅凭角色 ID 或对白猜测。新任务全话 semantic_audit 中 rule_triggers 保留准确 matched_rules（memory_id/rule_signature），模板从当前命中集生成且不填 PASS；旧RV按原半话审计范围恢复。库中启用人体规则且本格有可见角色时，另核对 human_figure_visible：decision=APPLIES/NOT_APPLICABLE 与具体 evidence。APPLIES 必须与获批 memory_tags 一致；人手/局部人体仍适用其可见部分，不因脸在画外而排除。非人体角色等真实不适用情形说明依据，不能由脚本把所有角色默认当人。

阶段基准预读和是否实际执行分开。当前 MEM-005/006 按其 stages 预读一次，其余条目按命中读取；未命中者不新增执行或验收项。semantic_audit 只用轻量索引核对实际命中覆盖，执行者仍要检查语义分类；机器无法证明其自然语言判断正确。每格没有命中也保留 memory_tags=[]，不删来源跳过检查。完整字段与命令见 [rule-memory.md](rule-memory.md)。

## 一次观察、分别判断

make_generation_qa 生成 inspection_plan，将原基础 QA、命中 memory_review 和例外替代检查按观察对象组织。它绑定实际图片和源执行包，仅用于安排一次看图；status 初始 UNREVIEWED，不参与放行。

打开当前原图、批准参考及必要的真实前格，一次观察覆盖所有适用目标。原 style_review、dimension_review、memory_review、手工可见性检查仍逐项记录判据和具体证据。相同观察可写入多个确实被它证明的项；身份通过不证明道具通过，生成前记录不证明返回图通过，未观察项不自动填 PASS。清单显示 PASS 也不能覆盖原字段的 FAIL/UNREVIEWED。

## 复用与版本

同一 gate/批量预检进程按实际索引内容哈希复用解析和匹配；选择缓存只记命中集，不缓存检查结论。正文在同 agent/运行/版本中按既有 load 缓存复用，实际哈希仍校验。图片、前格、输入、规则版本或判据变化时由内容绑定 QA 复用检查失效，重新核对受影响项。

维护前先归类，再修改正式来源；重复方法合并既有规则。本次仅新增读取策略，十条正文、触发和判据不变，索引条目版本更新为 1.1.0。配置只增加 memory.loading_policy，并发额度继续沿用。旧 RV 保持原证据，升级在新 RV 核验工具版本、规则签名及受影响依据，不改旧哈希或补造批准。

visual_evidence_v1负责把本话具体布局、状态、细节预期和图片观察绑定到现有记录；通用方法继续以MEM-002/003/004/005/006为正式来源。生产只读规则库。本次维护更新规则版本后，旧RV须用原工具/规则快照恢复或显式迁移，不能重签旧哈希。

通用提示词优化维护：MEM-004/005/006同步更新为1.2.0，其余条目保持实际版本。提示词模块在prompt-package.md，背景字段合同在shot-framing.md/schemas.md；编译器只查执行文字与依据一致性。生产只读规则库，冻结旧RV不自动重签或迁移。
