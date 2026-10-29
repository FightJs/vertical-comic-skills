# 准备输入与一次派发

新接包与新生产使用 `prepared_dispatch_v1`。每话启动固定执行器的 `generation_host.py serve --state <本话状态>`，JSONL 请求以 `request_id` 匹配响应，响应可以不按请求顺序返回。

1. 发送 `{"action":"prepare-inputs","request_id":"prepare","workers":4}`。公共输入核验一次，各格独立准备；调用不会生成图片，也不授予生产许可。
2. 准备期间可发送 `{"action":"ready-inputs","request_id":"ready"}` 取得已就绪、尚未登记的引用；不等待整话准备结束。未变输入续跑复用，变更后只请求准确受影响格。
3. 异步执行器设置 `protocol: "prepared_dispatch_v1"` 和 `onPrepareInvoke(ref)`。回调发送 `{"action":"claim-and-register","prepared_reference":ref,"request_id":"..."}`，返回准确 `{job, ack}`。必须直接返回宿主结果；禁止拼接或重放许可。
4. `invoke(job)` 和保存回调都使用这个最终 job。`save-return` 传最终 job 文件、原始返回和真实调用/返回定位；保存优先于准备、预测及QA。同话状态写入串行，多话分别保存。

异步执行器可使用准备引用数组，也可用 `nextPrepared()` 持续提供就绪引用；只有准备结束且队列为空才返回 null。服务容量由实际已核定租约限制；容量不足先等有请求结算，再派发未登记格。不要把全批预先登记成 IN_FLIGHT。

每次调用前仍核暂停、剩余有效时间、owner、容量、attempt和批准版本。普通派发不再 reserve→compile→submit，不外包 `production-global.lock`，不执行 `onInputHeadRefresh` 全状态重绑。输入变更提示重新准备准确范围，禁止悄悄退回完整预检循环。

登记回执不是实际服务调用证据。登记后崩溃不能重复使用 fresh 回执；确认未调用/无图才走下文恢复入口，结果未知先对账。已返回先保存，暂停和超时不能丢弃迟到原图。

旧 `durable_image_submission_v1` 回调及历史记录仍可读取和恢复，不能将旧字段改名冒充新协议。资产调用保持原协议。以下为该兼容协议与恢复细则。

# 实际图片请求的统一提交登记

正文、正文返修、资产及资产返修均使用`durable_image_submission_v1`。async_generation.js必须提供onBeforeInvoke；不根据managed_submission_required或kind跳过登记。不要手写成功回执，也不要在回调中复用旧成功对象。执行器是受信执行接线，不是阻止任意代码直接调用图片工具的安全沙箱。

## 正文与返修

先从原运行入口领取真实许可，再compile原始job。job包含submission、准确attempt/轮次、实际参数及适用dispatch_receipt。candidate/input_audit不能提交。保留原始job JSON供登记及异常查证，不能删字段来兼容旧执行器。

onBeforeInvoke(job)执行普通入口：

```text
python -X utf8 -B <scripts>/production_runtime.py --state <状态文件> --action submit --job <原始单job.json>
```

受管运行使用managed_dispatch.py的`--action submit --arguments <参数.json>`，参数为`{"job": <原始job对象>}`；不得绕过authority直接调用普通CLI。两个入口共用原完整预检和原账本，在同一次状态提交中登记IN_FLIGHT与submission_registrations；不是第二套调用账。

宿主检查命令退出码并解析真实JSON，回调返回该对象，不能仅看退出码0就组装一个成功对象。只有首次SUBMISSION_REGISTERED、invoke_allowed=true和全部身份/输入字段匹配，执行器才立即invoke(job)。invoke只调用真实图像工具，onResult继续原返回保存协议。await整个执行器，未完成Promise不能随exec结束丢弃。

```javascript
await runHalfWave(jobs, confirmedConcurrency, invokeImageTool, saveActualReturn, {
  onBeforeInvoke: registerThroughActualCli,
  onReviewReady
});
```

registerThroughActualCli是宿主注入的真实CLI适配器：按当前job书话选择其owner状态，传入同一个job，检查退出码并原样返回登记JSON。CLI不能启动图像工具；登记回调不能自行生图。等待槽位后逐job登记，不预先批量登记所有排队任务。执行器复制并冻结实际job，登记和invoke使用同一份输入。

回执绑定任务、书话、job、kind、panel/asset、attempt、batch/round、适用许可和input_digest。registration_id只是本次持久化登记的身份，不是图像工具request_id；登记不冒充observed_tool_call。未启用限时也必须登记。计时检查不代替原批准、容量或实际输入预检。

## 资产

asset_tasks.py仍只审计visual_basis.asset_tasks。asset_runtime.py管理本批资产调用，唯一账本为本地职责`00_任务协调/asset_requests.json`；不替代资产需求、A批准或正式资产索引。临时补视角和状态也使用此入口。

调用定义使用asset_call_definition_v1，包含book_id、episode_id、asset_id、唯一attempt_id、operation=generate/repair/retry、visual_basis与authorization的本地path/sha256、reference_files及实际arguments。修图另有source_attempt_id和repair_evidence，诊断绑定asset_id、episode_id、source_attempt_id及具体evidence。已确定无图的失败可在原授权及预算内显式retry，另用retry_evidence绑定同样范围和no_image_confirmed=true；未知结果不能重试。执行器不自动重试。参考文件须来自实际核对的批准依据，最多五个不同路径；args只使用当前支持的prompt、referenced_image_paths及transparent_background。source need引用已有asset_tasks，不重新创造需求。

authorization引用真实用户委托证据，含source_kind=user_message、source_locator、quote、book_id、episode_ids、asset_ids、operations、max_asset_calls、max_inflight。执行者按已有委托、规则及实际核定容量填入准确范围；不伪造用户批准，不因登记这些技术字段新增询问。调用预算包含已经登记和未知的尝试，不因换定义文件或修图清零。

```text
python -X utf8 -B <scripts>/asset_runtime.py compile --run-root <本机职责RV> --definition <调用定义.json>
python -X utf8 -B <scripts>/asset_runtime.py submit --run-root <同一RV> --job <compile导出的job.json>
python -X utf8 -B <scripts>/asset_runtime.py save --run-root <同一RV> --registration-id <登记ID> --result <实际结果.json>
```

compile的stdout是job；由宿主保存，onBeforeInvoke调用submit并返回真实回执。资产job仍是kind=asset，以asset_id绑定，不伪造正文格号或许可。资产共用当前前期/生产职责时钟，不另开额度。候选成功返回记GENERATED，不自动记批准。

结果JSON含status=GENERATED/CALL_FAILED/RESULT_UNKNOWN、原attempt_id、response_evidence。成功另含output及request_evidence；原请求证据使用observed_tool_call、source_locator、attempt_id、准确arguments，原返回证据使用observed_tool_result、source_locator、attempt_id、status=COMPLETED、outputs。失败/未知使用真实observed_tool_error或observed_executor_outcome；CALL_FAILED证据须no_image_confirmed=true，否则按RESULT_UNKNOWN保存。所有文件引用path/sha256，不覆盖原证据。

## 暂停、晚返回与恢复

新运行的local_execution_context_v1明确本机owner和是否限时。限时缺账本/失去绑定/时间不确定不能按旧运行放行。计时在锁前、预检后提交前及提交后回执前核对；共享时钟不使不同话的图像请求串行。最后一次核对到服务接收仍存在宿主边界，不承诺原子撤回。

登记成功但回执丢失或执行器退出：先查询登记，不自动调用。普通`--action submission-status --job <原job.json>`，受管同名action经managed入口；它们永远invoke_allowed=false。ALREADY_REGISTERED也不允许再调用。

SUBMISSION_REGISTERED_NO_INVOKE表示登记已经落盘、当前适配器未向工具发起请求；保留原attempt/登记及可核查的执行器证据，通过下述“确认无图恢复”建立新尝试，不能手工退回PENDING或重用旧登记调用。无法证明是否调用时按RESULT_UNKNOWN保留占槽和预算。登记、实际调用、实际返回三个事实不能混记。

到期/暂停不拦已有返回、证据发布、QA和落账。正文沿原commit/save；资产save不调用计时门禁，相同结果重复登记幂等，冲突结果拒绝。资产未知结果保持原attempt与容量，查证后save须提供resolution引用，证据绑定registration_id、attempt_id、source_kind=observed_resolution、source_locator及目标结果的result_digest；不新增生图。

旧包数据经[统一导入入口](execution-compatibility.md)保留原证据与原时钟，后续使用固定当前执行器。未支持的格式在接包阶段明确诊断，不执行旧代码或现场复制补丁。

## 接收端配套接线

旧包数据经[统一导入入口](execution-compatibility.md)保留原证据与原时钟，后续使用固定当前执行器。未支持的格式在接包阶段明确诊断，不执行旧代码或现场复制补丁。

旧durable协议提供onBeforeInvoke并原样返回prepare-submit真实JSON；新prepared协议使用本页开头的onPrepareInvoke，ALREADY_REGISTERED不调用。常驻宿主检查当前时钟及固定执行器门禁；未完成导入、未知状态或不兼容组合提前HOLD。已执行任务不复制新版脚本进入快照。


## 确认无图恢复

已确认的执行约定：用户要求完整成品包时，为补齐既定源格所必需的确认无图重试，以及已验证的当前数据导入与恢复入口，默认自主完成，不逐格、逐次再问。该约定来自用户明确指令：“这种类型的问题不用询问，我要最终不缺少的成品包”。运行记录绑定启动时实际任务委托及本约定，自动填写准确书话/格号；仅显式预算、权限或用户保留事项超出时再处理实际缺口。该指令不改变创作内容、用户保留亲审范围或服务内容限制。不将恢复约定解释为无限调用或批准新的创作方案。

先核查实际执行器、服务回执和落盘。NOT_INVOKED须有invocation_started=false的实际执行器证据；REJECTED_NO_OUTPUT/FAILED_NO_OUTPUT须确认服务没有返回图片；RESULT_UNKNOWN只有实际查证为RESOLVED_NO_OUTPUT后可恢复。超时、文件暂缺及“可能没调用”都不能证明无图。已有图片先恢复落盘，不重复生成；服务内容限制不能靠同请求重发绕过。

正式入口不调用生图，只记录并开放新尝试：

```text
python -X utf8 -B <scripts>/production_runtime.py --state <状态> --action recover-no-image --expected-state-sha256 <当前哈希> --recovery-request <请求JSON>
```

请求只含稳定request_id、panel_id、original_attempt_id、evidence及authorization两项path/sha256引用。证据JSON绑定book_id、episode_id、panel_id、attempt_id、round_id，含no_image_confirmed=true、outcome、source_kind、source_locator、evidence文字和非空evidence_files。身份从当前状态/job提取；观察和来源必须来自真实记录。授权JSON保存source_kind=user_message、source_locator、quote、book_id、episode_ids、panel_ids、operations=[no_image_retry,compatibility_execution]，范围从实际用户任务读取，不让用户手填技术JSON。

无图历史单独保存到no_image_history；原尝试、失败、登记和租约事件保留。新attempt不增加round_id、不消耗唯一质量返修轮次；实际调用次数和有效时钟均不清零，暂停继续不计时。返回NO_IMAGE_RETRY_READY后只为该格新attempt准备输入，再claim-and-register；旧durable协议沿原领取/compile/submit入口，恢复回执本身invoke_allowed=false。重复request_id幂等；旧回执/晚返回不能覆盖新attempt。受管运行用managed_dispatch.py --action recover-no-image --arguments，参数expected_sha256和request；workflow_session使用同名action，字段expected_state和recovery。

连续两次无图重试仍失败时，不继续同方法盲重发：补充diagnosis={cause,remediation,evidence:{path,sha256}}，实际排查技术原因并继续其他就绪格；相同诊断不能无限重复使用。有效预算耗尽时保存证据和缺口，不能伪造完整交付或重新开时钟。

### 旧包在途请求保全

```text
python -X utf8 -B <安装scripts>/generation_host.py recover-no-image --state <原状态> --expected-state-sha256 <当前哈希> --recovery-request <请求JSON>
```

旧包数据经[统一导入入口](execution-compatibility.md)保留原证据与原时钟，后续使用固定当前执行器。未支持的格式在接包阶段明确诊断，不执行旧代码或现场复制补丁。

新版本交付保留无图恢复证据，最终仍须每个源格都有实际采用图；无图、未知结果或坏文件不因恢复记录存在而通过。
