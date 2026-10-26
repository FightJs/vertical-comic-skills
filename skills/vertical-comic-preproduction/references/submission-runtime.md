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

SUBMISSION_REGISTERED_NO_INVOKE表示登记已经落盘、当前适配器未向工具发起请求；保留原attempt/登记及可核查的执行器证据，按原失败/恢复协议处理，不自动退回PENDING、不自动释放许可或重发。无法证明是否调用时按RESULT_UNKNOWN保留占槽和预算。登记、实际调用、实际返回三个事实不能混记。

到期/暂停不拦已有返回、证据发布、QA和落账。正文沿原commit/save；资产save不调用计时门禁，相同结果重复登记幂等，冲突结果拒绝。资产未知结果保持原attempt与容量，查证后save须提供resolution引用，证据绑定registration_id、attempt_id、source_kind=observed_resolution、source_locator及目标结果的result_digest；不新增生图。

旧冻结工具、状态、预算及在途请求不热升级。旧job没有本协议时新版执行器明确拒绝；不得只补一个标志、复制新版脚本或重签批准来绕过。继续原冻结接线时按原合同并在每次实际调用前核对安装版时钟，其强制覆盖范围须如实报告；需要新协议的旧包另建明确适配/迁移候选，先验证原冻结门禁，不能默认宣称已支持。

## 接收端配套接线

receive通过generation_host.py inspect-runtime检查冻结能力与工具字节，给出准确submission_protocol和executor路径。`prepare-submit`对新版返回原submit回执；对明确支持的旧版只执行其原commit IN_FLIGHT并保留UPDATES_SAVED事实。旧接线将该动作放在旧冻结执行器的invoke回调内，再调用实际图片工具一次；不向旧执行器传需要新协议回执的onBeforeInvoke，不把旧回执包装成新回执。

新协议继续提供onBeforeInvoke并原样返回prepare-submit真实JSON，ALREADY_REGISTERED不调用。宿主在独立安装进程检查当前时钟，再由原冻结门禁决定；缺旧协议能力、未知状态或不兼容组合提前HOLD。已执行任务不复制新版脚本进入快照。
