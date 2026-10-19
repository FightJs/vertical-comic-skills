---
name: vertical-comic-panel-generation
description: Compile frozen generation inputs and generate vertical-comic panels with mandatory approved style-image inputs. Use for whole-episode asynchronous production and rolling repairs, episode-parallel production, legacy resume or scoped repairs; requires approved visual basis and shots.
---

# 条漫逐格生图

新整话按[服饰与单画面](../vertical-comic-preproduction/references/appearance-and-single-frame.md)编译实际prompt并携带清晰衣装/配饰参考，最多5条路径不静默删关键来源。一图只生成一个连续画面，未选场面不进入绘图指令；返修明确改哪些细节、保留哪些细节，失败图不作款式权威。

从获批视觉基准和镜头编译实际请求、生成并保存逐格原图。先读已安装imagegen Skill与当前工具定义，再读共享[生图合同](../vertical-comic-preproduction/references/generation-io.md)、[Codex输入](../vertical-comic-preproduction/references/codex-imagegen.md)和[异步执行](../vertical-comic-preproduction/references/async-generation.md)。首次运行同时读[规则归属](../vertical-comic-preproduction/references/rule-ownership.md)，规则按阶段和命中加载。

新任务按[整话异步](../vertical-comic-preproduction/references/episode-async.md)与[逐格就绪](../vertical-comic-preproduction/references/panel-readiness.md)执行；旧RV继续原冻结快照。分工模式先读[双电脑交接](../vertical-comic-preproduction/references/split-production.md)与[直接交付](../vertical-comic-preproduction/references/direct-delivery.md)，仅提交当前获批半话。接包通过不等于生图放行。

1. 从本批快照运行production_runtime.py --action compile，批量预检当前就绪格。复用权威源序、visual_basis和shot_manifest，不另造镜头、参考或审批账本。
2. 实际prompt按[提示词合同](../vertical-comic-preproduction/references/prompt-package.md)写本格画面事实，去除重复与相反旧指令；身份、衣装、场景方向、接触、裁切及批准画风进入真实输入。按已有检查条件编译肢体归属、自然持物、人物视线与物件正反面，不整套堆砌负面词。元数据签名、预算与审批状态不当作绘图指令。
3. 每请求最多5条真实本地参考路径，同图合并用途。实际数组/编号、prompt.txt和JSON一致，完整门禁核对当前场景选区及关键细节确实携带。全景/全身参考不扩大取景，失败图不成为身份或画风来源。
4. 用本话[容量租约](../vertical-comic-preproduction/references/batch-runtime.md)领取唯一回执，完整预检后一次提交。独立格持续并发，高风险、校准及真实前图依赖按准确范围等待；状态保存串行。共享async_generation.js注入真实调用与持久化，未结束Promise保持存活；乱序返回按话/格/轮次/attempt保存。
5. 返回原件、真实请求/响应及图片立即落盘后释放生图槽，通知[图片验收](../vertical-comic-image-review/SKILL.md)。回调不能填视觉PASS。记录实际提交、返回、保存和QA时间；服务未公开的时间留未知。
6. 失败先按[实际执行质量](../vertical-comic-preproduction/references/execution-quality.md)分流：仅裁切不生图；局部错定向编辑；空间/动作/参考错先修输入；重复失败停止诊断。用repair_input_guard.py核对真实底图与待修迁移要素。肢体改姿同时说明旧结构移除、新结构及连接，不只新增一条正确手臂。
7. 原格最多一轮自动修正，超过5张真实失败先原子登记共因诊断。修正绑定真实失败、新包和具体约束，保留有效修正；额外授权单独记次数，不重置旧历史。未知请求先查证，不按超时重发或占用返修轮次。

B和实际包按[合并审查](../vertical-comic-preproduction/references/grouped-review.md)准确决定；明确用户委托可由执行者在范围内作有证据决定，不伪造用户逐项批准。原比例、源稿和身份资产不因模型失败擅自放宽。最终由验收阶段完成实际QA、连续性和逐格成品包。
