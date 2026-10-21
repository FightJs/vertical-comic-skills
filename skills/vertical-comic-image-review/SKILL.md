---
name: vertical-comic-image-review
description: Review actual comic images against approved evidence, preserve truthful QA and connect production decisions to annotated first-batch per-panel delivery. Use for image consistency QA, returned-image review or final panel delivery, excluding strip layout and bubbles.
---

# 条漫图片审核与第一批交接

所有阶段启动与恢复即执行[阶段与交付进度](../vertical-comic-preproduction/references/review-progress.md)：总控汇报阶段、到本职责ZIP的百分比、进行事项、阻塞与下一步；正常制作每10分钟、仅服务等待每15分钟，重要变化立即报。显示独立于人工停点和少询问委托，子agent上报事实由总控合并；不为通知重跑检查、取消在途请求或改预算。阶段进度只能中途汇报；任务未完成且仍有可执行工作或子agent运行时，总控继续推进/等待并收敛产物，不能发送最终答复结束轮次，详见上述进度规则的“总控持续执行与子任务收敛”。

用户已明确委托前期“仅在无法消解的剧本与资产冲突时询问”时，优先执行[前期最少询问规则](../vertical-comic-preproduction/references/grouped-review.md#前期仅询问无法消解的剧本资产冲突)：A、B、生图包与导出由执行者审核并记录决定，不再请求逐项确认；该委托不自动扩大到正文生产。

本技能负责供人工继续加工的第一批独立逐格图片。新运行先读[生产决定与阶段交接](../vertical-comic-preproduction/references/production-decisions.md)：沿用真实审核，逐问题分三类，按影响/成本决定一次合并修复、重生或留人工；采用版本与原QA绑定，交付附简明问题表。旧RV按冻结合同，不热替换工具或规则。


新整话按[服饰与单画面](../vertical-comic-preproduction/references/appearance-and-single-frame.md)在原QA核对衣装、人物归属、款式/总数量、身体佩戴侧/手指、附着与画面投影，结合全图和原尺寸局部。看不清不能PASS，一图多格必FAIL；返修同时检查已正确服饰保留，不新增自动轮次。

对实际返回原图完成身份、衣装、动作接触、背景空间、构图规格与画风六项QA，组装带准确交付结论和问题表的第一批逐格包；不做拼接、气泡或PSD。

首次读共享[规则归属](../vertical-comic-preproduction/references/rule-ownership.md)，本阶段读[图片审查](../vertical-comic-preproduction/references/stage-image-review.md)、[参考连续性](../vertical-comic-preproduction/references/reference-continuity.md)及[具体视觉证据](../vertical-comic-preproduction/references/visual-evidence.md)。通用标准引用真实MEM，项目判据来自当前批准镜头，不在验收时改判据迁就图片。

新任务按[整话异步](../vertical-comic-preproduction/references/episode-async.md)返图即审、滚动修复，默认无固定半话C。旧RV使用原冻结合同；分工制作先读[双电脑交接](../vertical-comic-preproduction/references/split-production.md)，第一半话确认后才提交后半话。历史图须保留实际生成输入、原图与真实QA，不用当前prompt冒充旧输入。

1. 打开实际原图、批准参考及必要真实前序图。用make_generation_qa.py组织inspection_plan，一次观察分别填写原六项、style_review及命中memory_review；模板和技术PASS不是视觉结论。
2. 先在全图逐人物数可见掌/腕/袖口并追溯所属身体，核对承托、接触对象/部位/阶段及场景世界布局，再看身份、服饰配饰、表达和画风。局部接触正确不能抵消全图多手。换机位可改屏幕左右，不能改真实座位、门窗或道具；合法透视和遮挡不是错误。
3. 眼睛、剧情手、关键首饰及物件看原尺寸。复杂接触局部覆盖所属前臂、手腕与对象；inspection_targets有声明时逐项记view.covered_targets。细节清晰与格式/像素尺寸分开，放大、锐化或缩略图不能证明原生细节。
4. 真实审核后先引用原观察分类并决定动作，第三类默认留人工、第二类按收益取舍；需要返修才按[实际执行质量](../vertical-comic-preproduction/references/execution-quality.md)诊断；仅裁切走零调用候选，局部问题合并一次编辑，空间依据错回A/B。保留原件和失败。二轮失败停止自动尝试，不反复整图抽图。
5. 修复后六项重审，并与底图同尺度比较清晰度及有效修正。结构返修沿whole_subject_recheck重数整个人物、核对旧结构移除与连接承托。明确preservation_regions时逐区记录preserved_observations，不能只看修复处。误判追加更正依据，保留原判断。
6. 连续性使用同场景前格及必要较早锚点图，按固定床侧/路沿判断，不从屏幕左右或未见区域推断移位。证据不足保持未核实，不虚报PASS。图片、输入和判据未变时复用真实QA；前序图换版只重查受影响连续性，不重审无关图。未返回/未审不能计通过，未知调用不混入视觉失败数。
7. 本话完成真实自审与适用连续性后提交D；按[合并审查](../vertical-comic-preproduction/references/grouped-review.md)区分用户批准及授权内执行者决定。多话另实际看当前跨话边界。本话仅等跨话比较时交回总控，不空转。

新运行按生产决定合同运行deliver及panel_delivery，复制准确采用版本，保存完整源序索引、四种交付结论、六列问题表、真实决定及审核依据；校验原图与派生图来源、真实尺寸/比例、全话比例分布及ZIP计数/CRC。合格图可提前准备交付文件，最后只补整话/跨话检查，不重绘。阶段进度和必要通知按[停点进度](../vertical-comic-preproduction/references/review-progress.md)，不把待确认称作最终验收。


完整生产任务按[完整交付请求](../vertical-comic-preproduction/references/grouped-review.md#完整交付请求)收敛：逐图检查和真实决定照常完成，授权内审查由执行者闭环；合格图本地归集，全部指定话/格通过完整交接门禁后交一份最终ZIP；准确区分加工材料交齐与全部图片视觉合格。用户未要求时不先交少量图片阶段包，不用“已生成”代替“已验收”。

返图按[前期收敛的检查目标](../vertical-comic-preproduction/references/final-input-semantics.md#前期收敛按包执行v2)审核：inspection_plan显示对应规则约束、配饰身体锚点与本镜头可见数量，分别写回原QA。原图观察不能被前期PASS替代；返修后同时核对已正确配饰及遮挡没有被改变。
