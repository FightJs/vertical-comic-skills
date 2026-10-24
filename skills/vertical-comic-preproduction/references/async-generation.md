# 实际异步提交

当前 `episode_async_v1` 也复用本页的工具异步调用、真实落盘、返图通知与异常处理；生产范围和滚动返修按 [整话异步生产](episode-async.md)，新请求 `batch_id=EPISODE`。下文H001/H002、C只适用于旧半话RV。

进入工具调用前读取本文和已安装 imagegen Skill。scripts/async_generation.js 提供可注入工具调用与结果落盘函数的执行器；它不是独立命令行生图后端，不选择模型，不改工具参数。当前整话模式先用 `episode_dispatch_queue.py` 批量领取真实空闲许可，再对领取格号运行runtime `compile` 完整预检。

1. 先核对真实本话整话计划与已批准依据，编译当前可执行集合的独立单格包，逐格运行完整generate门禁。所有实际参考使用明确本地路径，每格独立顺序/哈希，禁止“最近图片”。当前Codex入口每个请求最多5条参考路径，同文件多用途先合并；超限条目留待重编译，只派合格独立集合，见 [reference-budget.md](reference-budget.md)。新状态与实图依赖按 [整话异步生产](episode-async.md) 处理；旧半话RV按原计划。
2. 总控预留唯一许可，核定本话及全局剩余额度。待提交条目包含job_id/panel_id/batch_id/round_id/attempt_id，以及实际工具参数和包定位信息。预留不是发出请求，提交前正确登记IN_FLIGHT和实际请求证据。避免把调用计划记录成observed_tool_call。
3. 在functions.exec中加载async_generation.js函数体（通过文件工具读文本，或将完整函数体复制到该exec），注入invoke、onResult与onBeforeInvoke。onBeforeInvoke通过[统一提交登记](submission-runtime.md)调用真实登记入口；invoke只调用tools.image_gen__imagegen(job.arguments)，不能把登记隐藏在可省略的invoke约定中；onResult保存实际返回图路径、工具来源、输入/输出哈希、时间及结果，串行写本话状态，并把许可终结事件交总控更新。不要将返回base64全文打印到日志。
4. 调用await runHalfWave(当前就绪jobs,有效本话并发额度,invoke,onResult,{onBeforeInvoke,onReviewReady})；函数名沿用历史命名，当前jobs可来自整话EPISODE。执行器在同一轮启动多个invoke，等待所有任务收尾；不能for循环await上一张工具结果后再创建下一张请求，也不能发出Promise后结束exec导致请求被丢弃。它保持结果与源格对应，返回顺序不决定保存格号。onReviewReady在保存成功后发待审定位并yield；回调不占生图调用槽，不能在其中伪写图像PASS。agent打开原图及参考完成真实QA，单写队列保存审查结论。
5. exec可yield后用wait恢复该运行，期间仍保留未完成Promise。尚有就绪条目未发出时继续调度，不把单张生成的等待当本话唯一工作。等待时可以整理本话其他格输入和当前证据；需要前置实图的格按真实返回及时QA再形成下一就绪集合。单次执行器调用不要求所有格都无依赖。
6. 当前整话模式边返图边完整自审；整话收尾只补未审图和连续性，失败格按实际记录滚动返修。工具FULFILLED只说明函数返回，仍须核对是否实际有图；REJECTED记录真实异常，不自动重试。结果保存失败会停止提交余下条目，已在途任务仍收尾；NOT_DISPATCHED保持未提交，不能记为失败图或已生成。通知失败记review_signal_error并补通知/审查，不重发生图。结果未知先查证，禁止重复调用。旧半话流程按原轮次汇总。

当前返图即审、稳定A/B及QA复用见 [整话异步生产](episode-async.md)；旧半话记录见 [review-efficiency.md](review-efficiency.md)。onReviewReady可notify已保存包/图定位并await yield_control()让模型及时审图；不能在回调中阻塞到用户批准。执行器收尾等待全部通知；模型在yield期间审图，未完成Promise仍活着，随后用wait继续。生成/审查结果落盘都进入本话单写机制，共享control由总控更新。

onResult必须完成真实持久化，不是只notify一条“完成”。执行器单写落盘队列只串行保存，不把图像调用变回串行。跨话控制文件仍总控单写，不能在多个worker回调中直接覆写。每个agent只运行自己的一话，其他话并发由总控分配。

scripts/async_generation.js的单元测试使用假invoke验证请求重叠、乱序绑定、额度、拒绝与落盘故障；测试不证明真实后端吞吐。实际生产记录submitted_at/returned_at以及可见服务端标识，区分本地调用并发、工具排队与服务器渲染；没有实测不能宣称固定倍速或75张同时渲染。

正文、资产候选和返修均使用共享执行器；资产job登记kind=asset/asset_id/job_id/attempt_id。保存完整可序列化异常字段及原始返回，transport_status与是否有图分别核对，不能丢allSettled拒绝原因。连续三次连接/解码服务异常默认停新的派发、收尾已在途、余格保持NOT_DISPATCHED，不自动重试；跨话同源故障由总控暂停该服务。明确参数拒绝与结果未知按真实证据区别处理。详见 [执行兼容合同](execution-compatibility.md)。

新runtime执行器优先使用 onReviewBatchReady(entries)，options.reviewGroupSize来自runtime.review_group_size，reviewMaxWaitMs为runtime.review_max_wait_seconds乘1000；回调通知并yield，不等待人工批准。每个job由production_runtime compile导出实际参数，依赖/校准格review_priority优先即时通知。结果单写保存后，真实QA用commit集中更新；总控根据本话checkpoint完成即交审，不等待其他话。

长请求传 `onLongRequest(job,item,level,{event_id})` 并从runtime.watchdog设置requestWarningMs/requestEscalationMs；见 [执行者两级监控](worker-watchdog.md)。通知回调与原调用独立，不能释放槽位、取消Promise、重复派单或把超时计作视觉FAIL。总控用实际event_id去重；有在途请求时继续提交其他合格独立请求。


## 低开销显示与让出控制

新运行必须接入`onProgress(event)`显示回调；参数在程序接口中保留可选，以兼容原调用方。正常间隔`progressIntervalMs=600000`，仅服务等待`serviceProgressIntervalMs=900000`，本地轻检查`progressPollMs=30000`。回调仅汇报内存中的提交/在途/返回/保存数量及变化信号，不重读全部输入。它不是图片QA，不记录watchdog真实进展。未接回调的旧执行器保持原行为。

在现有异步exec中接入如下回调（与onReviewBatchReady并存）：

```javascript
onProgress: async event => {
  notify({type: 'comic_display_tick', ...event});
  await yield_control();
}
```

`notify`是向当前任务交回显示事件，子agent不直接发五份用户总摘要；总控按review-progress的due规则决定是否发言。收到事件后结合最新持久化事实刷新/显示，不能把计数信号当成图片已落盘证据。exec必须持续await执行器；让出后用wait恢复**同一个cell**，不要结束原exec、重建Promise或重复提交。首次yield后wait窗口设为工具支持的短窗口（建议30秒），不运行额外sleep轮询。启动/收尾及派发停止也会发观察信号，通知异常只记录progress_signal_errors，不改变已保存结果或补发生图。回调须及时返回，不在其中等待人工答复。

采用自定义通知配置时，将progress.active_seconds、service_wait_seconds、yield_seconds分别乘1000传入progressIntervalMs、serviceProgressIntervalMs、progressPollMs；省略时使用内置默认。

30秒检查不等于每30秒调用模型或发消息；有due事件时才notify/yield。工具不支持中途让出时，在恢复控制后补发当前摘要，不能声称严格定时。原始服务请求、保存单写、QA队列、许可及UNKNOWN处理保持原合同。


总控任务记录、真实等待、收尾检查与中断恢复统一见[任务协调与恢复](task-recovery.md)。新运行最终交付使用task_coordination.py finish-check，不能以进度摘要、子任务口头完成或等待超时结束轮次。

正文、返修及资产均须使用原始编译job和真实onBeforeInvoke；缺登记接线、审计/候选job及登记回执不符时，执行器不触达图片工具。不能用手写成功对象替代登记。协议、CLI及恢复见[统一提交登记](submission-runtime.md)。
