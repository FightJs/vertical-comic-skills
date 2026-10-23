# 第一批逐格生产决定与交接

当前技能统一生产供人工继续加工的第一批独立逐格图片。不设置首批/精修模式，不承担第二、第三轮人工精修。新运行以production_policy=first_batch_production_v1绑定此版本；旧RV与已交付工具保持冻结，不补字段或重签哈希。

## 在原审核之后决定，不重做审核

继续使用现有六项、命中MEM、原尺寸及连续性真实观察。PASS/FAIL/未核实保持原样。生产决定引用原qa_report、image及attempt，不复制第二份观察。执行者判读图片并分类；程序只核来源、覆盖及约束，不宣称识别画面错误。

同图允许多个问题类别；优先级取最高未解决影响。三类都记录：

| 类别 | 范围 | 默认处理 |
|---|---|---|
| ①重大 | 身份、核心衣装/颜色、场景、画风、关键动作对象、主要连续性、明显多肢体/归属及整体结构 | 授权和预算内优先修复或重生，不逐张询问 |
| ②规则/物理/配饰 | 适用规则违规、局部接触承托、配饰及非重大空间构图偏差 | 根据实际影响与成本选择处理 |
| ③可留人工 | 局部指形、少量纹理或衣装细节等影响有限且自动修复收益低的问题 | 默认留人工，不生成自动修复请求 |

规则命中不等于必须重生。保留实际违规及依据，再决定动作；涉及身份、核心衣装、关键叙事的规则错误仍属①。修不好不能降级，不能改批准设计/MEM消除违规。文字不变，仍不加入气泡、对白排版等新生产范围。

## 第二类决定与根因

简记六项取舍：影响、分布、调整范围、保留风险、修复历史、人工成本。数量不是重生门槛：少量集中且易定位可合并一次local_edit；分散且影响整体可regenerate；很多轻微问题也可defer_manual；一个严重承托错误仍可能须重建输入。风险高于收益时保留较好版本；仅明显且难以取舍时needs_user。

批准依据正确但生成偏差：用原批准参考修复。最终输入矛盾：rebuild_inputs先修受影响A/B/包并核准；不得重复原矛盾请求。改变批准设计超出委托时集中交审；其余独立格继续。

## 一图一次合并修复

原常规预算仍最多一次自动修复，不要求用完。修前将全部已知问题分为fix_now（必须修）、opportunistic（可顺带）、manual（明确留人工）；列表互斥且完整。第三类默认只进manual。实际prompt包含目标、保留项、适用批准参考用途；改结构时还说明旧结构移除、新结构和连接，不为顺带小问题制造冲突。

优先顺序：阻塞真实依赖的重大错误 → 其他重大错误 → 独立格首轮 → 收益明确的普通修复。普通剧情先后不制造实图依赖；可交接的图不自动成为合格生成参考，仍保留原依赖/高风险准入。

regenerate仍是原格第二次attempt，operation=repair、repair_method=regenerate；不是新首轮。继续携全部适用批准参考，错误图不作为生成输入。repair_source保留原真实版本用于返后比较；保留特征、服饰纠正/保留、完整QA和历史预算要求不变。局部编辑为repair_method=local_edit并实际携清晰底图。重生与局部编辑都经原compile及批准门禁。

修后主问题已解决、仅剩局部偏差：记录后留人工，不自动第三轮。原问题无改善或整体退化：停止该方法，比较历史候选。仍有重大错误：保持①并列人工优先处理；只有重大问题值得继续、有实质不同可行方案、既有授权和预算均允许，才考虑准确追加范围，不自动扩大预算。

重复问题复用原episode_failure_diagnosis，stopped_methods列cause_key、method_key和evidence。新合同允许在超过5张前主动登记有真实失败依据的共因诊断；不增加生图门槛。后续同因同法被拦截；different_plan必须写实质变化，不能只强化措辞。不把个案自动写成全局硬规则。

## 在现有账本登记决定和采用版本

生产流程panels原行增加production_decisions={attempt_id:相对path/sha256}，adoption={attempt_id,decision:同一引用,reason}。执行status/output/attempt_history/UNKNOWN不变。决定文件携policy、panel_id、attempt_id、image、qa_report、reviewer、reason、action、issues及三个问题ID列表。每个issue写id、category=1/2/3、kind、certainty=confirmed/unverified、location、problem、target、basis、handling、observations（原单格QA item内JSON pointer数组）。所有原FAIL和未核实观察须有去向；inspection_plan仅组织观察，不是额外审核结论。类别和处理动作分别保存。

调用动作另记method_key、可复用cause_key、preserve_constraints；第二类附factors={impact,distribution,scope,preservation_risk,history,manual_cost}，各项一句短语即可。动作取complete/defer_manual/needs_user/stop_diagnose/local_edit/regenerate/rebuild_inputs/crop_candidate。已发现问题不得声明complete。

使用原CAS锁保存不可变决定文件引用，原状态留runtime_history：

```text
python <冻结scripts>/production_runtime.py --state <本话状态> --action decisions-register --decisions <本话相对登记提案.json> --expected-state-sha256 <当前hash>
```

登记提案：panels=[{panel_id,decision:{path,sha256},adopt:true,adoption_reason}]；可以一次登记多格。只决定暂不采用时adopt=false。更改决定另存文件，保留旧字节和状态历史；不修改原QA。存在真实在途/未知请求时，采用旧图也不闭合该请求。

选择优先比较重大问题数量、核心一致性/连续性、清晰度与完整结构、人工接手成本。不得默认最新。采用首轮图时必须绑定首轮QA与首轮遗留问题；返修结论不能套用，已耗额度不回退。

## 人工交互

第三类、明确路线的第二类、授权内纠偏、已批准技术操作及修后轻微残留，不逐格提问。needs_user仅用于tradeoff/design_change/additional_budget/user_reserved，另写recommendation。使用production_runtime --action production-questions只筛选真实待决项，输出图、格号、一句话问题、推荐动作和内容绑定event_id；用--pending读取原合并审查的event_id/status待答记录去重，已有问题返回KEEP_PENDING。没有待决项返回NO_PRODUCTION_QUESTION，不新增审批阶段。原A/B、用户保留高风险和D不变；新分工没有默认半话确认，旧包仍按原冻结窗口。

## 第一批交接

完整交付仍覆盖本次全部指定话/格并最终交一份ZIP，不以少量图片阶段包结束任务。四种结果独立于审核：DELIVERABLE可交付；MANUAL_RETOUCH可交付人工后修；MANUAL_PRIORITY重大问题未解决、仅供加工；INCOMPLETE缺图、未知、未审、未完成处理或必要比较。重大问题不能自动标成可用，未核实疑点不让人工据此误改。

采用原batch_review_v1及cross_episode_review_v1比较记录，准确绑定采用图；允许其真实FAIL，不能改成PASS。源稿、批准、引用哈希、真实执行、完整观察、历史/预算不符仍阻止导出。缺必要比较记未完成。INCOMPLETE保留在诊断索引，不通过完整deliver/默认导出；仅用户明确请求部分材料时，准确保存D/委托决定并以panel_delivery.py --partial --export显式导出，结果仍为不完整，保留缺口与原任务；即使已有D决定也不把缺图、UNKNOWN、未审或未决问题变成完成。MANUAL_PRIORITY可作为准确标注的加工材料交接，但不计视觉合格。只把新的阶段交接接入deliver，原VISUAL_PASS及下游参考门禁不放宽。

```text
python <scripts>/production_runtime.py --state <本话状态> --action delivery-review --write <本话新交接审查.json>
```

保存后沿原D/用户委托，对该索引及artifacts准确作决定。可使用review_policy.proposal的原phase=final，格号覆盖完整源序；批准候选加工材料不等于批准全部图片可用。将delivery_review={path,sha256}加入上面的登记提案，可panels=[]只登记索引。改变图片/QA/决定/采用理由/未完成范围会使索引失效，原批准不扩大。

```text
python <scripts>/staged_workflow.py --state <本话状态> --check deliver
python <scripts>/panel_delivery.py --state <本话状态> --review <本话相对交接审查.json> --export <新的话交付目录>
```

导出器不修改账本、不调用生图、不烧标记。每话独立图片、全源格交付索引、六列问题表（格号/图片、类别、位置、当前问题→正确目标、优先级、处理情况）。链接指实际采用图，重大未解决置顶；主表只列该采用版本的剩余问题，已解决问题在历史。缺图/未知仍保留源格去向。可用数、人工后修数、人工优先数与未完成数分别报告，不把整包叫全部可用。

## 输入与效果边界

沿用background-treatment及final-input-semantics：建立场景、出入/位置变化和环境线索保必要实景；已建立空间的表情反应近景优先评估场景同色留白/简化。保留承托接触遮挡及剧情物；色调光向连续，不扩大取景或缩小人物制造无效留白。开批一次核对裁切与衣装/垂手/道具、机位可见性、道具状态、参考姿势干扰和首轮/返修五路径预算；提前准备忠实图集，不删批准参考。

先已有材料只读回放和隔离测试，覆盖三类决定、重生、止损、旧图采用、局部等待、UNKNOWN、预算和全源序。代码通过不代表实图质量或总效率提升。提问、调用、重复失败和等待按真实事件统计；没有观测留未知，不把决定数冒充实际调用数。

## 坐标局部编辑

需要局部结构修复时按[坐标引导返修](coordinate-repair.md)选择coordinate_local_edit；在原issues写repair_scope，沿原观察说明适用性与输入疑点。整体空间错误另行处理，局部可修不降低原category。
