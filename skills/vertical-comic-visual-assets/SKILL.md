---
name: vertical-comic-visual-assets
description: Lock episode-specific character identities, costume states, scenes and approved style examples; prepare only necessary missing assets for vertical-comic production. Use for reference selection, visual-basis review, or missing character/scene states.
---

# 条漫视觉基准与资产

新运行代表格接口稳定后，按[唯一主表与增量派生](../vertical-comic-preproduction/references/draft-authoring.md)维护创作输入，镜头/实际prompt/展示自动派生，只处理变化及真实依赖；工作草稿不反复冻结，正式调用与交接才绑定准确版本。

前期以[最小充分与集中收敛](../vertical-comic-preproduction/references/preparation-efficiency.md)为执行标准：普通格不反复润饰，先打通代表格，再用一次实际输入形成B/包合并审查；普通建议记录继续，技术问题在现有授权内修复，局部缺口不停止其他工作。

所有阶段启动与恢复即执行[阶段与交付进度](../vertical-comic-preproduction/references/review-progress.md)：总控汇报阶段、到本职责ZIP的百分比、进行事项、阻塞与下一步；正常制作每10分钟、仅服务等待每15分钟，重要变化立即报。显示独立于人工停点和少询问委托，子agent上报事实由总控合并；不为通知重跑检查、取消在途请求或改预算。阶段进度只能中途汇报；任务未完成且仍有可执行工作或子agent运行时，总控继续推进/等待并收敛产物，不能发送最终答复结束轮次，详见上述进度规则的“总控持续执行与子任务收敛”。

用户后续明确取消当前人工停点时，按[最新委托更新规则](../vertical-comic-preproduction/references/grouped-review.md#后续指令取消人工停点)更新当前运行授权；整体A也可由执行者内部审查，通过即继续，不因最初保留亲审而再次等待。

用户要求冲突按脚本处理或已选择脚本时，优先执行[脚本优先与补充状态免重复亲审](../vertical-comic-preproduction/references/grouped-review.md#脚本优先与补充状态免重复亲审)：自动补必要状态、内部审图并继续，不再次裁决或提交补充候选亲审。

用户已明确委托前期“仅在无法消解的剧本与资产冲突时询问”时，优先执行[前期最少询问规则](../vertical-comic-preproduction/references/grouped-review.md#前期仅询问无法消解的剧本资产冲突)：A、B、生图包与导出由执行者审核并记录决定，不再请求逐项确认；该委托不自动扩大到正文生产。

新整话按[服装配饰定位](../vertical-comic-preproduction/references/appearance-and-single-frame.md)在原appearance_details一次冻结衣装核心、首饰款式/总数量、角色自身左右及身体附着位置、清晰原板裁区；遮挡不推导不存在，未知不默认对称。具体穿戴属于本书生产记录，不写入通用记忆。

维护本话唯一visual_basis：人物身份、衣装状态、适用格、场景及批准画风，只制作必要缺失资产；不设计正文镜头或直接开始逐格生图。

共享合同在同级vertical-comic-preproduction。首次读[共同约束](../vertical-comic-preproduction/references/production-foundation.md)与[规则归属](../vertical-comic-preproduction/references/rule-ownership.md)；本阶段再读[身份确认](../vertical-comic-preproduction/references/identity-confirmation.md)及[资产流程](../vertical-comic-preproduction/references/stage-asset-production.md)。配置指定规则库时按[规则记忆](../vertical-comic-preproduction/references/rule-memory.md)只加载本阶段命中项。

新任务沿[整话异步](../vertical-comic-preproduction/references/episode-async.md)全话准备、逐格就绪。已有RV用原冻结快照和批准范围，不静默迁移。分工模式先读[双电脑交接](../vertical-comic-preproduction/references/split-production.md)；导出前执行[ZIP接包演练](../vertical-comic-preproduction/references/zip-handoff.md)，原批准不因路径变化重签。

1. 对照批准源稿核对称呼、身份关系、人物状态及真实可见范围；未知事实留缺口，不以模糊文字或一次性角色豁免掩盖。
2. 多话共用资产由总控冻结版本，各话只登记适用范围。场景参考证明布局，人物板证明身份/衣装，漫画样例证明画风，不能互相覆盖。
3. 按[实际执行质量](../vertical-comic-preproduction/references/execution-quality.md)复用scene_views、appearance_details与原source_region。选择正确子空间/方向；关键饰品登记清晰来源、款式和佩戴侧。有无与遮挡分开，不从低清或遮挡推导不存在。
4. 按[参考预算](../vertical-comic-preproduction/references/reference-budget.md)准备实际可用图片。每请求最多5条路径；同图合并用途，人物图集只做忠实原像素排布。除归属和像素一致，还实际看清本格所需脸、衣领和饰品；看不清先调整选区，不靠放大猜设计。
5. 只补确实缺失且影响当前格的资产，生成及修复实际携带批准画风；新图保持候选。独立资产可按实际容量并发，完整保存调用及未知结果。
   缺口按[补充与入库分流](../vertical-comic-preproduction/references/stage-asset-production.md#本批补充参考与资产入库)解决：完整必要资产、局部视角/状态、临时参考、一次性直接描述分别处理。旧索引断链不等于本批缺资产，不追索无关旧工程；已授权的资产候选生成不属于正文生图。保留用户指定的A审核与正式入库边界。
6. A材料列准确就绪/待补格、引用和状态；同版适用批准直接复用，新增内容按[合并审查](../vertical-comic-preproduction/references/grouped-review.md)处理。真实用户委托可支持执行者作范围内决定，但不能伪造逐项用户批准。

输出为权威visual_basis、准确参考及缺口、真实批准/委托决定证据。场景多视图、背景及细节操作见[视觉证据](../vertical-comic-preproduction/references/visual-evidence.md)和[背景模式](../vertical-comic-preproduction/references/background-treatment.md)，无需每格新增资产图或独立审查表。

前期资产观察须锁定本人物当前衣装及重要配饰的款式、总数量、角色自身佩戴侧、身体锚点/手指和真实附着方式；未知细节不凭对称推测。复用原appearance_details，跨格/跨话同状态沿同一依据，详见[服饰定位](../vertical-comic-preproduction/references/appearance-and-single-frame.md)。
