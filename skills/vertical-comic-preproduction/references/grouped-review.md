# 合并审查与准确授权

新运行统一按[第一批生产决定](production-decisions.md)衔接审核、返修与交付：真实FAIL不改写，处理动作与交付结论分别记录；旧冻结合同不迁移。下文审核方法、源稿/批准/证据要求仍适用。

保留A、B与包、必要高风险状态、D。减少提问依靠合并展示、准确复用和明确技术授权，不减少逐图QA或默认增加返修次数。每话一份准确材料；不同话可以同次回复分别批准，不以等齐五话为屏障。

## 完整交付请求

用户要求“直接尽快生成完整交付包”时，以本次指定全部话/格的一份最终ZIP为完成条件。启动时核对源序、总格数和已有授权；只做安装、配置或前期的任务不因此启动正文。不要把已接受的少数图片打成阶段包作为默认交付；合格图在本地持续归集，进度照实报告，生产继续推进。仅用户明确要求部分交付时输出部分包，仍保留原完整任务及缺口。

尽早扫描全部指定范围的准备缺口、保留亲审项和旧运行兼容性，不把这些问题逐格拖到生产中才发现。明确委托已覆盖的阶段直接使用下述user_delegation_v1，记录执行者决定；没有覆盖的必要决定集中一次说明具体事项和建议方案，不为每个候选另起一次问询。已存在待答事件时合并诊断、引用原事件，不重复提问。

- 路径绑定、补齐材料、保持批准设计的技术修正由当前执行者处理并验证；不新增人工批准或转交前期负责人。
- 实际prompt/镜头/QA的修改先判断是否改变批准内容。仅同步已批准依据时保存差异和重检证据；确实变更时，有准确委托则执行者审查并登记决定，无委托才询问。不能仅因改了B/PACKAGE文件就认定必须用户亲审，也不能仅因“修错”就跳过真实包变更门禁。
- 状态实图和D有适用委托时由执行者真实看图决定；用户明确保留的亲审范围仍等待。不把本条或“尽快完整交付”本身当成追加预算、迁移旧协议或批准已拒绝方案的授权。
- 旧冻结入口不支持授权决定或必要兼容修正时，尽早形成具体迁移候选，核对在途/UNKNOWN、原图、历史预算和批准适用范围；不能只留一个WAITING_USER索引就结束完整任务，也不能修改冻结工具或伪造旧批准放行。需要用户决定的范围与原因集中列明。

一个局部问题只暂停该格及真实依赖；继续提交其他就绪格、审图、返修和准备成品。当前已无可执行工作才如实报告准确阻塞及所需决定；不把局部HOLD扩大成全批停止，不以联系表或压缩成功替代完整验收。返修次数和UNKNOWN沿原合同，完整交付要求不代表无限重试。

完整交付范围不变：全部指定源格须有准确采用图、完整真实QA、适用连续性比较、处理决定与D/委托决定，并核对源序/计数/哈希/CRC。新first_batch_production_v1可包含明确标注的人工后修及人工优先材料；完整加工材料已交齐不等于全部图片视觉合格。INCOMPLETE（缺图、未知、未审、未决或缺必要比较）不通过完整交付门禁，也不能用批准一份索引代替补齐。仅用户明确要求部分成果时另交部分材料并保留完整任务缺口。旧冻结运行继续原接受图与严格验收合同。无需另设“是否打包”停点。

## B和包一次回复

先保存production_runtime.py --action bundle的实际输出，再运行：

```text
python <scripts>/review_policy.py --root <本话RV> --state <生产流程.json> --bundle <本话相对包路径>
```

保存输出proposal作为待审成果，按items中的准确格号和artifacts展示。问题示例：“是否批准材料中的B镜头与生图包各自列明的范围？可分别批准或修改。”用户明确同时批准时，选择B、PACKAGE两个item_id；只批准B时仅选B。不能从一句无明确范围的“继续”补造两项批准。

真实回复记录为message={source_kind:user_message,quote:原文,source_locator:真实位置}，accepted_item_ids为明确选中项；运行：

```text
python <scripts>/review_policy.py --root <本话RV> --proposal <已展示proposal.json> --selection <真实回复及选择.json>
```

输出各项独立普通proof，由本话唯一写入者保存并登记现有approval_index；原generate门禁仍逐项验证。脚本只核对结构与范围，不认证消息来源或替模型解读回复。旧文件不覆盖，不把待审proposal记成APPROVED。

维护中的新登记入口为`authority_updates.py --state <本话状态> --expected-state-sha256 <准确当前哈希> --changes <登记/撤销JSON>`，具体格式、兼容边界与撤销语义见[一致性协议：阶段3A](dispatch-consistency.md#阶段3a已接入的批准权威写入)。它保存原proof字节和新版索引，不解读用户回复，也不自动迁移活动RV或启用短锁。旧冻结运行继续原入口。

## 一事一问

每份准确proposal有内容绑定event_id。在本话现有审查记录保留event_id、status和真实问询调用定位；工具有稳定question_id时一并保存，没有则不臆造ID；再次展示前用--pending传入当前记录。KEEP_PENDING表示保留原待答问题，仅用普通进度消息补充材料，不调用问询工具重问，也不假定工具支持编辑原问题；ASK_READY_ITEMS才提交新问题。后续进度或同版本材料不重复调用问询工具。版本变化使事件变化，先说明差异并更新待答范围，不把旧答复扩大。

## 范围内直接执行

原图已有适用身份/衣装/场景及用途批准，路径迁移或忠实图集按既有技术合同核验即可，不为技术别名再问A。补回漏编译的原源/B要求，先核对与获批实际包是否不同；不能把真实包变更说成只换路径。

等比例尺寸归一、信息完整的矩形裁切在B与包时集中列为technical_operations事项，operations从equal_scale_normalize、information_preserving_crop、faithful_atlas、byte_identical_relocation选择，列准确格号、成果版本和constraints。只有真实批准后才能使用；review_policy.technical_errors核对授权类型、范围和版本。裁后保留必显信息、身份/衣装/接触、比例计划并重验，不用裁切隐藏错误。首次实际使用这些操作时仍遵守工具的编辑授权要求。

轻微取景容差只有事先明确批准才能由执行者裁定；用户已拒绝的具体方案不得被宽泛授权覆盖。新增身份、衣装、固定空间、剧情、对白、关键动作或额外调用预算仍需明确裁决。

高风险实图仍确认；当前已返回的多个状态可合并，关键依赖不为凑组等待。自动第二轮用完后，集中列真实失败图、原因、具体修复和每格追加次数供一次回复；不增加默认自动预算。D可合并当前完整就绪范围，分别记录真实批准。

## 用户明确委托执行者决定

当前新整话/逐格就绪入口可用user_delegation_v1：先忠实记录真实用户原文和source_locator，再明确书、话、逐话panel_ids、可决定phases、constraints，以及excluded_panel_ids/retained_user_phases。不从“继续”、配置开关或技术PASS推导授权；用户已拒绝的方案须保留在约束内。用户指令优先于本合同的默认亲审步骤。

委托记录是AUTHORIZED/source_kind=user_message；执行者的具体决定是AGENT_DECIDED_UNDER_USER_AUTHORITY/source_kind=agent_decision，引用authority的准确path/sha256，记reviewer/evidence、准确artifacts、phase和panel_ids，并原样保留authority_constraints。不得把决定改成用户APPROVED。字段示例见schemas.md。

review_policy.py对同一已保存proposal可用--selection、--authority、--reviewer、--evidence生成决定proof，selection仍准确选accepted_item_ids；随后按原approval_index登记。此入口核对结构和范围，不替模型认证消息或判断画面。亲审证明继续走原approvals，不混用两者。前格上下文同样按准确阶段和原格号验证。

technical_operations须在委托operations内且保留具体constraints。additional_repair须逐格绑定已明确获准的additional_attempt_ids，proposal/proof的attempt_ids保留准确次数与新编号；记录本身不创建attempt、不重置自动次数，也不绕过原追加执行门禁。旧版已冻结流程不因新proof格式自动升级。

最终B/包合并提交前须有[最终输入逐格审查](final-input-semantics.md)。执行者的REVIEWED是审查证据，不是用户APPROVED。差异明确区分画面变更、引用同步和正常实图补齐；仅真正变化与保留亲审范围请求决定，未变化依据复用适用原批准。
