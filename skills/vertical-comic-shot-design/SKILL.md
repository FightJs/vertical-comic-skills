---
name: vertical-comic-shot-design
description: Design approved-script-driven per-panel shots, crop and physical continuity for vertical comics. Use for shot review, camera design, spatial verification and optional composition aids after visual identities/states are confirmed.
---

# 条漫镜头与空间设计

新运行代表格接口稳定后，按[唯一主表与增量派生](../vertical-comic-preproduction/references/draft-authoring.md)维护创作输入，镜头/实际prompt/展示自动派生，只处理变化及真实依赖；工作草稿不反复冻结，正式调用与交接才绑定准确版本。

前期以[最小充分与集中收敛](../vertical-comic-preproduction/references/preparation-efficiency.md)为执行标准：普通格不反复润饰，先打通代表格，再用一次实际输入形成B/包合并审查；普通建议记录继续，技术问题在现有授权内修复，局部缺口不停止其他工作。

所有阶段启动与恢复即执行[阶段与交付进度](../vertical-comic-preproduction/references/review-progress.md)：总控汇报阶段、到本职责ZIP的百分比、进行事项、阻塞与下一步；正常制作每10分钟、仅服务等待每15分钟，重要变化立即报。显示独立于人工停点和少询问委托，子agent上报事实由总控合并；不为通知重跑检查、取消在途请求或改预算。阶段进度只能中途汇报；任务未完成且仍有可执行工作或子agent运行时，总控继续推进/等待并收敛产物，不能发送最终答复结束轮次，详见上述进度规则的“总控持续执行与子任务收敛”。

用户后续明确取消当前人工停点时，按[最新委托更新规则](../vertical-comic-preproduction/references/grouped-review.md#后续指令取消人工停点)更新当前运行授权；整体A也可由执行者内部审查，通过即继续，不因最初保留亲审而再次等待。

用户要求冲突按脚本处理或已选择脚本时，优先执行[脚本优先与补充状态免重复亲审](../vertical-comic-preproduction/references/grouped-review.md#脚本优先与补充状态免重复亲审)：自动补必要状态、内部审图并继续，不再次裁决或提交补充候选亲审。

用户已明确委托前期“仅在无法消解的剧本与资产冲突时询问”时，优先执行[前期最少询问规则](../vertical-comic-preproduction/references/grouped-review.md#前期仅询问无法消解的剧本资产冲突)：A、B、生图包与导出由执行者审核并记录决定，不再请求逐项确认；该委托不自动扩大到正文生产。

新整话按[服饰与单画面](../vertical-comic-preproduction/references/appearance-and-single-frame.md)逐细节区分自身佩戴侧、本机位投影和遮挡；镜面另给反射依据。每格只选一个连续画面，脚本双格择关键一幅、另一幅忽略，原稿不改，B的动作/人物/裁切同步选定范围。

从锁定脚本、确认身份/衣装/场景及批准画风设计全话镜头；保留源格号、事件、对白与必显信息，只适配机位、取景和可见表现。

首次读共享[共同约束](../vertical-comic-preproduction/references/production-foundation.md)和[规则归属](../vertical-comic-preproduction/references/rule-ownership.md)，本阶段读[镜头流程](../vertical-comic-preproduction/references/stage-shot-design.md)、[裁切](../vertical-comic-preproduction/references/shot-framing.md)与[空间连续性](../vertical-comic-preproduction/references/visual-continuity.md)。规则正文按实际命中加载，不复制成新判据。

新任务按[整话异步](../vertical-comic-preproduction/references/episode-async.md)准备完整源序、镜头和候选实际包；普通格准确就绪即可放行。旧RV按原冻结合同；分工制作先读[双电脑交接](../vertical-comic-preproduction/references/split-production.md)，显式保留半话停点，不整话自动派发。

先从动作及真实物理条件推导机位，执行[可实现性与输入质量](../vertical-comic-preproduction/references/execution-quality.md)：谁的哪条肢体接触哪个对象/部位、动作阶段、承托和遮挡是什么；当前裁切能否同时容纳并辨认。坐标可相对表达，不编参考无法证明的几何。困难接触先修镜头，不交模型自行补猜。

写明摄影机位置/高度/朝向、景别、比例、逐人物身体范围、视线、背景锚点及必显信息。世界站位与屏幕左右分开，画外/遮挡不等于离场。简单手势不套复杂接触模板，非剧情手不强求五指全露。只有确有需要才做站位图或干净目标机位构图图；辅助图不是空间正确或新身份的证明。

同次核对肢体任务、全身扭转、承托、持续在场人物，以及摄影机/头部/目光和物件正反面是否相容；抽象信息表达不自动画成实物。狭小空间已建立后优先评估足够表达剧情的连续近景。相邻镜头按冻结MEM-010版本执行，新v2不强制机位与景别同时变化。

使用现有visual_evidence及framing_feasibility记录，按[原尺寸与连续性合同](../vertical-comic-preproduction/references/visual-evidence.md)列关键观察目标。为复杂接触可在原check添加inspection_targets，覆盖所属前臂、手腕、接触点和对象；普通格不增加局部框。

全话B前完成[比例计划](../vertical-comic-preproduction/references/frame-ratio-plan.md)，保留六种比例和竖版>75%要求；按内容选择，不为变景别或交错牺牲接触、裁切和物理成立。背景按[背景模式](../vertical-comic-preproduction/references/background-treatment.md)保必要锚点和清晰主体，不要求每格全套家具。

generation_dependencies只记录真实前图依赖，普通剧情先后不自动串行；requires_state_review、calibration_anchor及用户明确实图停点照范围保留。semantic_audit按真实规则命中及人体适用性核对，缺口仅阻塞受影响格。B与候选生图包按[合并审查](../vertical-comic-preproduction/references/grouped-review.md)一次展示、分别记录决定；技术PASS不授予生产批准。新增身份或真实改基准回A，批准变化只重审受影响部分。

新运行按[最终输入语义审查](../vertical-comic-preproduction/references/final-input-semantics.md)执行：先审设计，再核对完整实际prompt、参考和判据；前期闭合后交接，接包只复查实际变化与新实图。审查沿用semantic_audit，不新增用户停点、不热改旧冻结包。

前期完成[逐格输入收敛](../vertical-comic-preproduction/references/final-input-semantics.md#前期收敛按包执行v2)：确定设计连续性、验收比较与真实实图依赖；规则落实为本格约束。配饰区分身体自身侧与画面投影，明确锚点、遮挡及可见数量，不为展示配饰改变动作或裁切。
