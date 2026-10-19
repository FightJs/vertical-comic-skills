---
name: vertical-comic-image-review
description: Review actual vertical-comic panel images against approved style, identity, costume, scene and shot evidence; diagnose scoped repairs and assemble an accepted per-panel image package. Use for image consistency QA, returned-image review or final panel delivery, excluding strip layout and bubbles.
---

# 条漫图片验收与成品包

新整话按[服饰与单画面](../vertical-comic-preproduction/references/appearance-and-single-frame.md)在原QA核对衣装、人物归属、款式/总数量、身体佩戴侧/手指、附着与画面投影，结合全图和原尺寸局部。看不清不能PASS，一图多格必FAIL；返修同时检查已正确服饰保留，不新增自动轮次。

对实际返回原图完成身份、衣装、动作接触、背景空间、构图规格与画风六项QA，组装验收通过的逐格包；不做拼接、气泡或PSD。

首次读共享[规则归属](../vertical-comic-preproduction/references/rule-ownership.md)，本阶段读[图片审查](../vertical-comic-preproduction/references/stage-image-review.md)、[参考连续性](../vertical-comic-preproduction/references/reference-continuity.md)及[具体视觉证据](../vertical-comic-preproduction/references/visual-evidence.md)。通用标准引用真实MEM，项目判据来自当前批准镜头，不在验收时改判据迁就图片。

新任务按[整话异步](../vertical-comic-preproduction/references/episode-async.md)返图即审、滚动修复，默认无固定半话C。旧RV使用原冻结合同；分工制作先读[双电脑交接](../vertical-comic-preproduction/references/split-production.md)，第一半话确认后才提交后半话。历史图须保留实际生成输入、原图与真实QA，不用当前prompt冒充旧输入。

1. 打开实际原图、批准参考及必要真实前序图。用make_generation_qa.py组织inspection_plan，一次观察分别填写原六项、style_review及命中memory_review；模板和技术PASS不是视觉结论。
2. 先在全图逐人物数可见掌/腕/袖口并追溯所属身体，核对承托、接触对象/部位/阶段及场景世界布局，再看身份、服饰配饰、表达和画风。局部接触正确不能抵消全图多手。换机位可改屏幕左右，不能改真实座位、门窗或道具；合法透视和遮挡不是错误。
3. 眼睛、剧情手、关键首饰及物件看原尺寸。复杂接触局部覆盖所属前臂、手腕与对象；inspection_targets有声明时逐项记view.covered_targets。细节清晰与格式/像素尺寸分开，放大、锐化或缩略图不能证明原生细节。
4. 返修先按[实际执行质量](../vertical-comic-preproduction/references/execution-quality.md)诊断；仅裁切走零调用候选，局部问题合并一次编辑，空间依据错回A/B。保留原件和失败。二轮失败停止自动尝试，不反复整图抽图。
5. 修复后六项重审，并与底图同尺度比较清晰度及有效修正。结构返修沿whole_subject_recheck重数整个人物、核对旧结构移除与连接承托。明确preservation_regions时逐区记录preserved_observations，不能只看修复处。误判追加更正依据，保留原判断。
6. 连续性使用同场景前格及必要较早锚点图，按固定床侧/路沿判断，不从屏幕左右或未见区域推断移位。证据不足保持未核实，不虚报PASS。图片、输入和判据未变时复用真实QA；前序图换版只重查受影响连续性，不重审无关图。未返回/未审不能计通过，未知调用不混入视觉失败数。
7. 本话完成真实自审与适用连续性后提交D；按[合并审查](../vertical-comic-preproduction/references/grouped-review.md)区分用户批准及授权内执行者决定。多话另实际看当前跨话边界。本话仅等跨话比较时交回总控，不空转。

运行deliver完整门禁后复制当前接受图，保存源序索引、真实决定及验收依据；校验原图与派生图来源、真实尺寸/比例、全话比例分布及ZIP计数/CRC。合格图可提前准备交付文件，最后只补整话/跨话检查，不重绘。阶段进度和必要通知按[停点进度](../vertical-comic-preproduction/references/review-progress.md)，不把待确认称作最终验收。
