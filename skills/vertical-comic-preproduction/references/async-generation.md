# 实际异步提交

当前 `episode_async_v1` 也复用本页的工具异步调用、真实落盘、返图通知与异常处理；生产范围和滚动返修按 [整话异步生产](episode-async.md)，新请求 `batch_id=EPISODE`。下文H001/H002、C只适用于旧半话RV。

进入工具调用前读取本文和已安装imagegen Skill。scripts/async_generation.js是可注入工具调用与保存回调的执行器，不是独立命令行生图后端；它不选择模型、不修改工具参数。

新正文按[准备输入与一次派发](submission-runtime.md)启动每话常驻宿主，使用已准备引用和 `onPrepareInvoke`。调用形式：`await runHalfWave(refs, limit, invoke, onResult, {protocol:'prepared_dispatch_v1', onPrepareInvoke, onReviewBatchReady})`；也可传空refs与nextPrepared持续消费就绪队列。invoke只调用实际tools.image_gen__imagegen(job.arguments)，onResult使用同一最终job保存原返回、来源定位及文件。不能手写许可、把准备记录当执行job或打印base64全文。

实际参考保持本地准确路径、顺序和哈希，每请求最多五条；超限修输入，不静默截断。真正需要前格图的依赖只阻塞相关格。总控核定实际容量、一次分配租约；每个空闲worker在调用前一次登记，不能先批量标记IN_FLIGHT。

执行器同时启动允许的请求，持续await全部Promise，yield后用wait恢复同一cell。不能逐图await后才创建下一请求，也不能结束exec丢弃在途Promise。每话保存串行、多话独立；返回持久化后释放槽位，不等待QA。保存失败停止新调用，已在途仍收尾。FULFILLED不等于有图；未知先查证，确认无图按正式恢复入口处理。

每图快速实际观察一次，只因严重剧情问题开启至多一轮质量返修。onReviewReady/onReviewBatchReady只通知定位并yield，不伪写PASS，不阻塞到用户批准。通知失败补通知/审查，不重发生图。

当前返图即审、稳定A/B及QA复用见 [整话异步生产](episode-async.md)；旧半话记录见 [review-efficiency.md](review-efficiency.md)。onReviewReady可notify已保存包/图定位并await yield_control()让模型及时审图；不能在回调中阻塞到用户批准。执行器收尾等待全部通知；模型在yield期间审图，未完成Promise仍活着，随后用wait继续。生成/审查结果落盘都进入本话单写机制，共享control由总控更新。

onResult必须完成真实持久化，不是只notify一条“完成”。执行器单写落盘队列只串行保存，不把图像调用变回串行。跨话控制文件仍总控单写，不能在多个worker回调中直接覆写。每个agent只运行自己的一话，其他话并发由总控分配。

scripts/async_generation.js的单元测试使用假invoke验证请求重叠、乱序绑定、额度、拒绝与落盘故障；测试不证明真实后端吞吐。实际生产记录submitted_at/returned_at以及可见服务端标识，区分本地调用并发、工具排队与服务器渲染；没有实测不能宣称固定倍速或75张同时渲染。

正文、资产候选和返修均使用共享执行器；资产job登记kind=asset/asset_id/job_id/attempt_id。保存完整可序列化异常字段及原始返回，transport_status与是否有图分别核对，不能丢allSettled拒绝原因。连续三次连接/解码服务异常默认停新的派发、收尾已在途、余格保持NOT_DISPATCHED，不自动重试；跨话同源故障由总控暂停该服务。明确参数拒绝与结果未知按真实证据区别处理。详见 [执行兼容合同](execution-compatibility.md)。

新runtime执行器优先使用 onReviewBatchReady(entries)，options.reviewGroupSize来自runtime.review_group_size，reviewMaxWaitMs为runtime.review_max_wait_seconds乘1000；回调通知并yield，不等待人工批准。每个最终job由onPrepareInvoke返回实际参数，依赖/校准格review_priority优先即时通知。结果单写保存后，真实QA用commit集中更新；总控根据本话checkpoint完成即交审，不等待其他话。

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

新正文、返修使用onPrepareInvoke返回的最终job；旧协议和资产使用原始编译job及真实onBeforeInvoke；缺登记接线、审计/候选job及登记回执不符时，执行器不触达图片工具。不能用手写成功对象替代登记。协议、CLI及恢复见[统一提交登记](submission-runtime.md)。

## 接包执行器选择与保存

按receive返回的runtime_compatibility选择冻结executor及submission_protocol，onBeforeInvoke规则只适用于durable_image_submission_v1；prepared_dispatch_v1按本页使用onPrepareInvoke；已验证旧普通job沿其冻结invoke接线，具体见submission-runtime.md。不要让执行者临时修改回执格式。实际返回交给generation_host.py save-return，先持久化再排QA。

新策略每话可启动`generation_host.py serve --state <准确本话状态>`，通过JSONL复用冻结workflow_session与有界validation_pool；请求与响应保留request_id。工作进程不能换话、换工具链，reserve/submit仍即时核对时钟及审计写冲突。旧运行不因启动常驻包装器获得新版缓存合同。进程本身不调用图片工具，服务回调仍由宿主注入。
