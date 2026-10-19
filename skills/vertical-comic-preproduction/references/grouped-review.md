# 合并审查与准确授权

保留A、B与包、必要高风险状态、D。减少提问依靠合并展示、准确复用和明确技术授权，不减少逐图QA或默认增加返修次数。每话一份准确材料；不同话可以同次回复分别批准，不以等齐五话为屏障。

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
