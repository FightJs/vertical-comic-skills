---
name: vertical-comic-panel-generation
description: Compile approved inputs and generate first-batch comic panels with scoped, prioritized repairs and approved visual references. Use for whole-episode asynchronous production and rolling repairs, episode-parallel production, legacy resume or scoped repairs; requires approved visual basis and shots.
---

# 条漫第一批逐格生图

所有阶段启动与恢复即执行[阶段与交付进度](../vertical-comic-preproduction/references/review-progress.md)：总控汇报阶段、到本职责ZIP的百分比、进行事项、阻塞与下一步；正常制作每10分钟、仅服务等待每15分钟，重要变化立即报。显示独立于人工停点和少询问委托，子agent上报事实由总控合并；不为通知重跑检查、取消在途请求或改预算。

用户已明确委托前期“仅在无法消解的剧本与资产冲突时询问”时，优先执行[前期最少询问规则](../vertical-comic-preproduction/references/grouped-review.md#前期仅询问无法消解的剧本资产冲突)：A、B、生图包与导出由执行者审核并记录决定，不再请求逐项确认；该委托不自动扩大到正文生产。

本技能负责供人工继续加工的第一批独立逐格图片。新运行先读[生产决定与阶段交接](../vertical-comic-preproduction/references/production-decisions.md)：沿用真实审核，逐问题分三类，按影响/成本决定一次合并修复、重生或留人工；采用版本与原QA绑定，交付附简明问题表。旧RV按冻结合同，不热替换工具或规则。


新整话按[服饰与单画面](../vertical-comic-preproduction/references/appearance-and-single-frame.md)编译实际prompt并携带清晰衣装/配饰参考，最多5条路径不静默删关键来源。一图只生成一个连续画面，未选场面不进入绘图指令；返修明确改哪些细节、保留哪些细节，失败图不作款式权威。

从获批视觉基准和镜头编译实际请求、生成并保存逐格原图。先读已安装imagegen Skill与当前工具定义，再读共享[生图合同](../vertical-comic-preproduction/references/generation-io.md)、[Codex输入](../vertical-comic-preproduction/references/codex-imagegen.md)和[异步执行](../vertical-comic-preproduction/references/async-generation.md)。首次运行同时读[规则归属](../vertical-comic-preproduction/references/rule-ownership.md)，规则按阶段和命中加载。

新任务按[整话异步](../vertical-comic-preproduction/references/episode-async.md)与[逐格就绪](../vertical-comic-preproduction/references/panel-readiness.md)执行；旧RV继续原冻结快照。分工模式先读[双电脑交接](../vertical-comic-preproduction/references/split-production.md)与[直接交付](../vertical-comic-preproduction/references/direct-delivery.md)，仅提交当前获批半话。接包通过不等于生图放行。

1. 从本批快照运行production_runtime.py --action compile，批量预检当前就绪格。复用权威源序、visual_basis和shot_manifest，不另造镜头、参考或审批账本。
2. 实际prompt按[提示词合同](../vertical-comic-preproduction/references/prompt-package.md)写本格画面事实，去除重复与相反旧指令；身份、衣装、场景方向、接触、裁切及批准画风进入真实输入。按已有检查条件编译肢体归属、自然持物、人物视线与物件正反面，不整套堆砌负面词。元数据签名、预算与审批状态不当作绘图指令。
3. 每请求最多5条真实本地参考路径，同图合并用途。实际数组/编号、prompt.txt和JSON一致，完整门禁核对当前场景选区及关键细节确实携带。全景/全身参考不扩大取景，失败图不成为身份或画风来源。
4. 用本话[容量租约](../vertical-comic-preproduction/references/batch-runtime.md)领取唯一回执，完整预检后一次提交。独立格持续并发，高风险、校准及真实前图依赖按准确范围等待；状态保存串行。共享async_generation.js注入真实调用与持久化，未结束Promise保持存活；乱序返回按话/格/轮次/attempt保存。
5. 返回原件、真实请求/响应及图片立即落盘后释放生图槽，通知[图片验收](../vertical-comic-image-review/SKILL.md)。回调不能填视觉PASS。记录实际提交、返回、保存和QA时间；服务未公开的时间留未知。
6. 先依据三类生产决定选择留人工、一次合并局部修复或一次重生；仅值得处理的问题才用额度。需要调用时再按[实际执行质量](../vertical-comic-preproduction/references/execution-quality.md)分流：仅裁切不生图；局部错定向编辑；空间/动作/参考错先修输入；重复失败停止诊断。用repair_input_guard.py核对真实底图与待修迁移要素。肢体改姿同时说明旧结构移除、新结构及连接，不只新增一条正确手臂。
7. 原格最多一轮自动修正，超过5张真实失败先原子登记共因诊断，重复低收益策略可提前停止。修正绑定真实失败、新包和具体约束，保留有效修正；额外授权单独记次数，不重置旧历史。未知请求先查证，不按超时重发或占用返修轮次。

B和实际包按[合并审查](../vertical-comic-preproduction/references/grouped-review.md)准确决定；明确用户委托可由执行者在范围内作有证据决定，不伪造用户逐项批准。原比例、源稿和身份资产不因模型失败擅自放宽。最终由验收阶段完成实际QA、连续性、采用版本选择及第一批逐格图片和问题表。

新运行按[最终输入语义审查](../vertical-comic-preproduction/references/final-input-semantics.md)执行：先审设计，再核对完整实际prompt、参考和判据；前期闭合后交接，接包只复查实际变化与新实图。审查沿用semantic_audit，不新增用户停点、不热改旧冻结包。

生产使用[已收敛逐格包](../vertical-comic-preproduction/references/final-input-semantics.md#前期收敛按包执行v2)的完整prompt与实际参考，不重新设计或临时追加未经审查的绘图块。真实依赖只按批准范围补齐，保留prepared_input_digest以核对实际输入；运行许可仍实时检查。
