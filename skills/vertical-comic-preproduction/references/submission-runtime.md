# 准备输入与一次派发

新接包与新生产使用 `prepared_dispatch_v1`。每话启动固定执行器的 `generation_host.py serve --state <本话状态>`，JSONL 请求以 `request_id` 匹配响应，响应可以不按请求顺序返回。

1. 发送 `{"action":"prepare-inputs","request_id":"prepare","workers":"all"}`。公共输入核验一次，各格独立准备；调用不会生成图片，也不授予生产许可。
2. 准备期间可发送 `{"action":"ready-inputs","request_id":"ready"}` 取得已就绪、尚未登记的引用；不等待整话准备结束。未变输入续跑复用，变更后只请求准确受影响格。
3. 异步执行器设置 `protocol: "prepared_dispatch_v1"` 和 `onPrepareInvoke(ref)`。回调发送 `{"action":"claim-and-register","prepared_reference":ref,"request_id":"..."}`，返回准确 `{job, ack}`。必须直接返回宿主结果；禁止拼接或重放许可。
4. `invoke(job)` 和收图回调都使用这个最终 job。成功返回先用 `capture-return` 保全原图、原始返回和 attempt 身份并结算真实服务槽位；再用 `register-return` 正式登记。同话正式状态写入串行，收图使用独立有界 I/O；原 `save-return` 仍是兼容入口。

异步执行器可使用准备引用数组，也可用 `nextPrepared()` 持续提供就绪引用；只有准备结束、没有可能补入的恢复任务且队列为空才返回 null。服务容量由实际已核定租约限制；容量不足先等有请求结算，再派发未登记格。不要把全批预先登记成 IN_FLIGHT。

每次调用前仍核暂停、剩余有效时间、owner、容量、attempt和批准版本。普通派发不再 reserve→compile→submit，不外包 `production-global.lock`，不执行 `onInputHeadRefresh` 全状态重绑。输入变更提示重新准备准确范围，禁止悄悄退回完整预检循环。

## 整批固定启动入口

新 receive 返回 `batch_manifest`（整批执行清单.json）。优先加载其中固定执行器的 `batch_bootstrap.js`，一次启动整批；它组合 `batch_runner.js`、`batch_host_client.js` 和既有 source/bridge。编译、调用、保存、审核材料准备重叠；确认无图重试自动重进队列，暂空不是结束。不得逐格让模型拼命令。每话一个状态写入宿主；Agent按整话领取，在当前可用Agent容量内分配，独立格不设置固定波次。

分配给单个Agent的子清单保留本话条目并设置finalize_delivery=false，防止子任务提前封整批包；总控在各话完成后执行一次lean_delivery.py。一个宿主管理多话时则使用完整清单自动封包。

启动前沿[容量租约](batch-runtime.md)一次分配真实owner及本话额度。新额度按整话格数配置；已有生产额度及工具明确上限继续生效，不能擅自重置活动租约。新清单的max_inflight取本批全部源格数，表示任务范围上限，不宣称后端渲染通道数；没有用户硬上限时不要填固定小数。临时降档只写机器资源账，不把compile_workers改为1、不缩成单话清单、不把maxPending设为1。maxPending只用于真实工具限制或明确用户限制。若需自动恢复，在每个episode条目填写已有用户委托的 `recovery_authorization` 文件引用，覆盖 no_image_retry、network_failure_delivery、content_failure_delivery 及准确书话格；这是复用已有委托的技术登记，不新增询问。

固定启动模板（宿主工具函数名称以当前实际工具清单为准）：

```javascript
// 在可调用真实工具的执行宿主中求值固定 batch_bootstrap.js 得到 startComicBatch。
// nodeBinding 直接指向当前持久 Node 工具；imageBinding 直接指向实际生图函数。
const result = await startComicBatch({
  manifestPath: received.batch_manifest,
  node: nodeBinding,
  invokeImage: (args, job) => imageBinding(args),
  sourceLocator: actualExecutorLocator,
  onReviewBatchReady: (entries, materials, relay) => notifyActualReviewQueue(materials, relay),
  onProgress: notifyDisplayOnly
});
```

bootstrap通过持久Node的JSONL客户端批量转发请求、等待完成通知并集中收取返回，不逐格启动Python或让模型调度。Node通过文件模块import加载客户端，不使用eval或data URL模块；工具绑定给Node操作至少30秒的正常执行窗口，不用1秒超时。Node不调用生图；真实图像函数在支持它的宿主内调用。明确只支持串行工具的宿主使用现有channels分支；不得把同一串行工具重复命名冒充并发。

审核通知提供真实原图路径、attempt、模板引用；审核者实际分组看图后，一次向对应宿主发送 `qa-save-batch` 和 observations 数组，每项沿轻审核观察格式。也可使用 `review-submit-batch`：提供prepare-qa产生的review_ticket与真实观察，工具自动回填attempt、模板及base_qa。只写观察、问题与处理意见，不手工编造身份/哈希。审核任务队列保留在Node的 `comicBatchRelays.get(relayKey).reviews`；不把通知发出当作已审。程序运行中可以通过对应clients.request提交观察；入口结束后将真实观察按话放入同一bootstrap的observationsByEpisode参数，数组项为{review_ticket, observation}；程序自动复用原宿主与缓存、保存观察、继续必要剩余格并封包，复用未变输入及已保存图片，不再次生图或要求重看已审图。

`CONTINUE_REQUIRED` 保留宿主，后续使用相同 manifestPath 自动复用，也可传返回的 relayKey。相同运行不并开第二个 writer；清单改变时拒绝复用。程序完成后自动关闭；用户明确停止或释放空闲宿主时调用 `startComicBatch({manifestPath,node:nodeBinding,closeOnly:true})`。进程确实退出时才重建，并沿原状态恢复；保留进程不代表继续计时，暂停与等待用户仍按原计时事件扣除。

宿主保留期间记录待登记的收图凭据；续跑只重放未登记返回，不扫描全部历史图片、不重新生图。大返回走batch_relay.js的有界分块落盘，不把整块base64嵌入Node工具代码；每块内容校验并可靠保存，Relay用请求ID和确认回执去重。失去通信回复只重放同一通信请求；已完成但未确认的回复保留，不能因此重发图像请求。重启找到完整的待保存收图封套时，只重放保全和登记；未完整上传的分块与未知请求保留为对账证据，不推断无图。收图在客户端按每话最多8个未完成保存排队，返回对象不预先重复序列化；生图通道仍持有至可靠保全。宿主的收图超额响应表示保留原返回后重试保存，不是无图或重新生图许可。控制消息不排在收图容量等待之后。准备就绪按修订号通知，等待不占状态写入者；旧冻结宿主仍走原有轻轮询。

真实宿主可提供结构化返回时，优先使用 `invokeEnvelope:(args,job)=>actualEnvelopeBinding(args,job)` 替代 invokeImage，返回 `{result,call_locator,result_locator,terminal?}`。terminal 必须来自实际观测，包含准确 attempt_id、registration_id、outcome、no_image_confirmed、source_kind、source_locator、evidence；Python入口核对身份和终态。实际调用抛错而携带原始结构化回执时，可用 `error.toolEnvelope` 原样传递。普通 timeout/网络异常不自动补写确认无图；保持 UNKNOWN，不能盲目重发。原始错误证据和既有重试上限不变。

所有材料齐备时自动调用 `lean_delivery.py` 封包并完成登记；未审、UNKNOWN或真实依赖未满足时返回CONTINUE_REQUIRED和准确缺口。补齐实际观察或修复意图后续跑同一入口，只准备剩余范围；不得静默退回旧终审链。运行中止后先由宿主重放原始收图，未知结果对账。

## 全机自适应并发

machine_resources.py在本机Skill管理目录维护短锁资源账，各话和各Agent共用编译worker、图片请求及活动Python宿主额度。默认起点为2/4/1，按可用内存、CPU、快照估算、返回峰值和输出磁盘实时调整；未知探测保守为1/2/1。这是全机额度，不是每话额度，也不是用户硬上限或服务许可。

资源持续健康60秒、有待处理工作时可小步试增，不必先等4张慢图完成。编译每次+1；图片低档+1、高档约+25%；宿主仅在现有话无法供足工作时请求增加。试增观察窗口至少60秒，并随实际请求耗时延长；只把可靠保存的独立图片或成功编译计入吞吐。足够样本未提高约5%则回退并逐步延长冷却（120秒起，最多900秒）；缺样本不宣称提速。空闲不重置成2/4；明确暂停后恢复只重开观察窗口，保留学到的额度、请求和已消耗任务时长。

每2秒内复用系统采样。内存/换页、待保存字节、落盘积压、磁盘异常时减少新增派发。已调用的请求继续保存；UNKNOWN保留原attempt和生产槽。普通资源等待计入有效运行，暂停/等用户仍不计时。进程创建资源失败的降档反馈回同一资源账，健康后仍可自动试增，不把较小worker数固化到整批。

batch_runner保留完整源格范围；先复用能供足就绪格的宿主，再按缺口启动下一话。batch_host_client先通过轻量资源协调子进程取得全机宿主额度，才启动本话Python，不再同时启动全部大宿主。只回收没有准备、在途、待保存请求的空闲宿主；普通空闲30秒释放占用，未变编译结果从磁盘复用。死去的父进程仍有存活子进程时，不抢回资源额度。

机器许可逐请求检查，JS调用能力不冻结在启动时的临时探测值。正式容量租约使用[同owner调整](batch-runtime.md#同owner动态调整)，保留lease_id/epoch/attempt；调低先限制新领取，槽位不能低于现有活动或UNKNOWN数量。真实工具上限、生产许可、当前批准和明确用户限制仍有效；资源恢复不需要额外询问。

查看machine_resources.py输出中的limits（当前目标）、hard（硬件估算界限）、active（实际占用）、pending_bytes/oldest_capture_seconds（收图积压）及tuning/history（试增、冷却和限制原因）。batch_runner进度同时包含待准备话数和就绪队列；bootstrap返回实际host_snapshot。没有真实吞吐样本时不能承诺最优值或节省比例。

图片获得可靠保存回执后清除内存base64，只保留证据定位；保存/登记失败不重新生成。安装仅影响新冻结运行。旧运行恢复沿原导入入口保留全部范围、许可、请求及预算；不能直接修改正在运行的冻结脚本。此前应急生成的单话/1并发清单不会因安装被自动替换，恢复时使用核实后的原整批范围，不把应急数字误认成用户永久要求。

## 并行编译与流式输入

仅进程启动失败、内存/系统资源耗尽时将失败池并行数减半，保留已完成结果，只重排未完成格；普通语义错误不冒充资源不足。

每话由唯一 owner 批量调用一次 `prepare-inputs`；内部使用多个进程并行核验和编译，默认 workers=all，表示准备全部待编译格；实际进程数先取得全机共享资源额度，绝不按格数直接启动进程。公共批次快照每个 worker 接收一次，任务只传格号；待处理任务最多为已获全机额度的 worker 数，完成一格就持久发布一格。稳定期间复用编译池；压力变化或跨话公平调度时先停止补充任务、排空当前池再调整大小，成功项不重做。未变输入与确认无图的技术重试复用现有编译内容。

多子agent分别处理各话时，共用本机machine_resources.py额度，不能每话独占一份机器容量。workers正整数仍是请求上限；all也服从资源控制。编译并发与真实图片调用额度分别管理，不能互相推定。编译先行提供可用输入，生图按共享租约持续补位；真实前图依赖仍等待，不靠删除依赖提速。

同一固定执行器提供 `prepared_input_source.js`，求值后得到 `createPreparedInputSource`。它接收实际 JSONL 客户端的 `request` 函数（按 request_id 匹配并返回真实 result），立即启动批量准备，同时提供 `nextPrepared`。后者不会把暂空当作结束；只在准备返回、最终就绪快照核对且队列清空后返回 null。内部每次只核验一小批尚未取走的引用，默认1秒低频检查暂空队列，不等待整话编译完成。

```javascript
const source = createPreparedInputSource({
  request: requestThisEpisodeHost, // 已连接当前唯一宿主的真实JSONL请求函数
  workers: allocatedCompileWorkers,
  bufferSize: Math.max(1, 2 * confirmedConcurrency)
});
const results = await runImageToolBridge({
  run, jobs: [], confirmedConcurrency, transport, host,
  options: {...existingOptions, nextPrepared: source.nextPrepared}
});
await source.completion; // 持续收尾准备，不随exec结束丢弃在途工作
const preparation = source.snapshot();
```

`request` 必须允许 prepare-inputs 和 ready-inputs 同时等待、正确接收乱序响应；不能用逐请求等待的客户端把它们重新串行化。上例是与既有桥接器的接线，仍须接入真实工具、持久保全及登记；单元测试不证明宿主已完成真实接线或服务端吞吐。

`ready-inputs` 可传 `panels`、`limit` 和 `exclude_record_digests`；仅跳过消费者已领取到本地队列的准确记录，变更后的新记录继续可见。排除记录不授予生图许可，调用前仍走完整的 claim-and-register。一个 source 只对应一话的一次准备选集；依赖解除或局部修改后为准确范围重新准备。EOF只表示该次输入流结束，必须检查 snapshot 的 blocked_panels、invalidated、preparation_error 与最终缺格，不能当成完整交付。

容量不足时异步执行器保留原未登记引用、释放本地通道并低频重新领取；不丢格、不创建新attempt、不算生图重试。后续暂停、时限或撤销仍由每次领取实时检查。

登记回执不是实际服务调用证据。登记后崩溃不能重复使用 fresh 回执；确认未调用/无图才走下文恢复入口，结果未知先对账。已返回先保存，暂停和超时不能丢弃迟到原图。

旧 `durable_image_submission_v1` 回调及历史记录仍可读取和恢复，不能将旧字段改名冒充新协议。资产调用保持原协议。以下为该兼容协议与恢复细则。

## 固定调用适配入口

新生产加载同一固定执行器内的 `async_generation.js` 和 `image_tool_bridge.js`，把求值所得函数分别作为 `run` 与 `runImageToolBridge`。用后一入口连接真实工具和每话 JSONL 宿主，不在运行中临时拼整话登记/整话统一收图循环。

`runImageToolBridge({run, jobs, confirmedConcurrency, transport, host, options})` 的接线合同：

`jobs` 汇集本批已就绪的各话引用，`host` 按 job 书话路由到对应唯一 owner。不能先 await 一整话结束才启动下一话；分属真实独立宿主时也应先启动各通道，再共同等待。需要流式准备时沿用 `options.nextPrepared()`，暂时无就绪格须等待准备事件，只有准备完成且无可派发任务才返回 null；阻塞/缺图仍交回总控处理。

- `transport.kind="concurrent_requests"` 用一个实际异步invoke函数同时管理多个请求；可传工具明确的maxPending上限。请求槽是客户端概念，不冒充服务物理通道。
- 兼容 `transport.channels` 是当前可实际使用的调用通道清单，每项为 `{id, invoke(job)}`；一个通道同一时刻最多保留一个调用。不能把同一串行宿主重复命名为多个通道；本地租约上限不证明服务并发。全话可以准备，不能全话提前登记。
- `transport.source_locator` 定位当前真实执行器。`invoke(job)` 原样使用最终 `job.arguments` 调用当前可用图片工具，返回 `{result, call_locator, result_locator}`；只有宿主提供真实开始/完成事件时才附 `native_started_at/native_completed_at`。本地 Promise 创建时间不冒充服务开始。
- `host.prepare(ref)` 按书话路由到唯一 owner 的 `claim-and-register`，原样返回响应；HOLD 响应抛出其中真实 error，不伪造成功。准备引用先跨话交错，再获取可用通道、登记、立即调用。
- `host.recordInvocation(job,event)` 发送 JSONL `invocation-event`，返回真实响应。该记录只说明本地调用请求已登记，不授予第二次调用许可。
- `host.capture(job,packet,item)` 将最终 job 与原始返回写入文件，向对应宿主发送 `capture-return`：`job`、`raw` 为文件路径，附 `call_locator`、`result_locator` 和 `observed:{returned_at:item.returned_at,native_started_at:packet.native_started_at,native_completed_at:packet.native_completed_at}`，原样返回 `RETURN_CAPTURED` 回执。`host.register(job,capture,item)` 发送 `register-return`，传回执的 `capture` 引用并原样返回结果。收到可靠保全回执即可释放本地通道，正式登记在后台进行；待登记上限默认为 8，达到上限才等待。
- `host.save(job,packet,item)` 处理失败或未知结果，也保留供旧宿主使用。失败与未知必须通过既有证据/解析入口落账后，才能分别返回 `FAILURE_RECORDED/UNKNOWN_RECORDED`，不能仅凭 Promise rejection 认定无图。
- 每话宿主启动时重放已保全但未登记的返回，也可发送 `recover-returns` 显式重放；单格登记失败只留待重放并继续独立格。已保全原图不能重新生图；结果未知先查证，不能因执行器终止或超时认定无图。公共磁盘无法保全时停止新调用，保留 `bridge_packet`。
- 可选 `transport.checkStatus(job,event)` 和 `host.collectAvailable(...)` 只接宿主实际支持的查询/收图能力。默认 5 分钟查状态、10 分钟定位慢请求，继续仍可用的独立通道；不虚构取消能力，不回收未知服务许可，不超时重发。

若宿主只提供一个不可分离的串行调用通道，本地代码不能强制它并行。使用一个真实通道并明确报告限制；增加 JSON 中的数字不能作为并发验证结果。没有宿主身份或持久保存接线时，不把候选适配器宣称为已验证生产链路。

`ready-inputs` 暂时无 job 不代表整话完成；同时检查 `preparing`、`preparation_complete`、`preparation_error` 和 `blocked_panels`。准备完成后仍有缺图/等待项须进入对应恢复或依赖处理，不静默结束任务。

# 旧提交协议与资产调用兼容入口

旧冻结正文及资产调用使用`durable_image_submission_v1`；新正文走上文prepared_dispatch_v1，不重复下述reserve/submit。async_generation.js必须提供onBeforeInvoke；不根据managed_submission_required或kind跳过登记。不要手写成功回执，也不要在回调中复用旧成功对象。执行器是受信执行接线，不是阻止任意代码直接调用图片工具的安全沙箱。

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


### 网络错误最多重试四次

正文生图无论处于首批、中途还是尾部：实际工具明确返回网络错误，且已确认该调用无返回图时，首次调用后最多自动重试4次（累计最多5次确认网络失败）。同一源格跨会话、输入版本和技术attempt累计，不清零。每次失败保存原始错误并立即走现有recover-no-image；网络错误在额度内不再要求追加长诊断、重写提示词、转参考格式或重新审核整话，未变输入复用，其他格继续。技术重试不增加质量返修轮次；时钟、暂停、当前许可与容量限制继续生效。

接到本默认流程的任务时，启动阶段一次性将真实任务委托和本约定绑定到准确书话/源格，恢复授权operations记录no_image_retry及network_failure_delivery。已有用户明确采用此约定的运行直接补齐准确授权，不逐格询问；不得伪造用户原话或把历史普通重试授权冒充缺格交付授权。用户明确要求绝不缺图时不得自动套用缺格豁免。

第五次确认网络失败后，工具返回NETWORK_RETRY_EXHAUSTED，保留CALL_FAILED、原调用和耗时，不再创建下一attempt，不在最终打包前追加第六次调用。按授权保留源格编号，交付已有图及网络缺格说明；NETWORK_FAILED只表示缺格处置闭合，不是图片生成或QA通过。索引、问题总览CSV和问题明细CSV写明累计失败次数、最后原始错误和“工具返回网络错误，服务端根因未证实”，不造空白占位图。最终完成是“已有图片及授权缺格清单已交付”，不能宣称全部图齐全。

图像服务明确返回内容审核拒绝且该 attempt 已确认无图：保全原始响应或错误、准确 attempt 和返回定位，确认是实际内容审核拒绝后，不重试该格，继续其他格，最后在成品包的缺格和问题表中按原错误汇报；`CONTENT_REFUSED` 不代表有图或 QA 通过。按用户本次现有指示自动记录覆盖该话该格的用户原话及 `content_failure_delivery` 授权，不再逐格询问；调用 `recover-no-image` 并传入已结算终态 `terminal` 和对应授权，工具生成并校验处置凭据。结果未知、普通输入错误、假造或其他 attempt 的错误不得归入此类。

非网络错误继续按准确错误类型处理；不将未知结果、服务内容限制、保存失败或普通输入错误归入网络缺格。未实际调用不占网络失败次数。此恢复入口不直接调用图像服务，执行器按回执领取新attempt；不得在transport里另套绕开账本的重试循环。

先核查实际执行器、服务回执和落盘。NOT_INVOKED须有invocation_started=false的实际执行器证据；REJECTED_NO_OUTPUT/FAILED_NO_OUTPUT须确认服务没有返回图片；RESULT_UNKNOWN只有实际查证为RESOLVED_NO_OUTPUT后可恢复。超时、文件暂缺及“可能没调用”都不能证明无图。已有图片先恢复落盘，不重复生成；服务内容限制不能靠同请求重发绕过。

正式入口不调用生图，只记录并开放新尝试：

```text
python -X utf8 -B <scripts>/production_runtime.py --state <状态> --action recover-no-image --expected-state-sha256 <当前哈希> --recovery-request <请求JSON>
```

请求只含稳定request_id、panel_id、original_attempt_id、evidence及authorization两项path/sha256引用。证据JSON绑定book_id、episode_id、panel_id、attempt_id、round_id，含no_image_confirmed=true、outcome、source_kind、source_locator、evidence文字和非空evidence_files。身份从当前状态/job提取；观察和来源必须来自真实记录。授权JSON保存source_kind=user_message、source_locator、quote、book_id、episode_ids、panel_ids、operations包含no_image_retry；适用本节网络缺格约定时同时包含network_failure_delivery；适用内容审核拒绝缺格约定时包含content_failure_delivery；确需兼容执行时增加compatibility_execution，范围从实际用户任务读取，不让用户手填技术JSON。

无图历史单独保存到no_image_history；原尝试、失败、登记和租约事件保留。新attempt不增加round_id、不消耗唯一质量返修轮次；实际调用次数和有效时钟均不清零，暂停继续不计时。返回NO_IMAGE_RETRY_READY后只为该格新attempt准备输入，再claim-and-register；旧durable协议沿原领取/compile/submit入口，恢复回执本身invoke_allowed=false。重复request_id幂等；旧回执/晚返回不能覆盖新attempt。受管运行用managed_dispatch.py --action recover-no-image --arguments，参数expected_sha256和request；workflow_session使用同名action，字段expected_state和recovery。

非网络错误连续两次无图重试仍失败时，不继续同方法盲重发：补充diagnosis={cause,remediation,evidence:{path,sha256}}，实际排查技术原因并继续其他就绪格；相同诊断不能无限重复使用。有效预算耗尽时保存证据和缺口，不能伪造完整交付或重新开时钟。

### 旧包在途请求保全

```text
python -X utf8 -B <安装scripts>/generation_host.py recover-no-image --state <原状态> --expected-state-sha256 <当前哈希> --recovery-request <请求JSON>
```

旧包数据经[统一导入入口](execution-compatibility.md)保留原证据与原时钟，后续使用固定当前执行器。未支持的格式在接包阶段明确诊断，不执行旧代码或现场复制补丁。

新版本交付保留无图恢复证据，最终仍须每个源格都有实际采用图；无图、未知结果或坏文件不因恢复记录存在而通过。

常驻宿主的 `recover-no-image` 可接收 `panel_id`、`terminal`、`authorization` 和原有 `expected_state`，由工具自动生成恢复身份与稳定请求 ID。`terminal` 是内容绑定的真实终态文件，必须包含准确 attempt、registration_id、无图结论与来源定位；工具保留内容限制标识和未知解析原证据。该入口仍要求先结算实际失败/解析未知，不把网络报错直接升级成无图证明。旧 `recovery` 请求格式继续可用。


## 审核后立即衔接（v2026.10.31.2）

新运行启用 `observed_followup_v1`。沿用 prepare-qa → review-submit-batch；票据列出首状态屏障、受影响格及已登记证明中的可用委托。审核者在同次实际看图后可附 `state_review: {verdict: "PASS", observed: "实际观察", authority: {path, sha256}}`。程序复用 review_policy 的准确委托决定和 authority_updates，不将普通 QA PASS 冒充首状态通过。用户保留亲审和已撤销授权继续阻塞。

完全相同的票据和观察可重放：已提交 QA 的身份存于原格记录，后续放行失败只重放衔接。修改观察必须使用新票据及当前 QA 引用。严重问题的 repair_request 绑定原图、原 attempt、QA、诊断、修复目标及保留约束；沿现有准确范围输入和 repair-authorize 入口继续，不手工拼 repair-plan 的诊断路径，不凭请求自动增加尝试。

新 `observed_repair_window_v2` 在严重问题 QA 成功保存时记录有效运行起点；准备审核材料不启动返修窗口。起点与原 attempt 一同持久化，重启、重放、诊断改字不重置。暂停按原任务时钟排除，内部等待计时。旧运行已有窗口保持原规则。

审核回调完成后，batch_runner 比较批准/采用修订并重新打开受影响待生产源；不等待其他慢请求返回。进度中的 scheduling 区分机器额度、清单额度、租约限制、实际在途及阻塞原因。tool_capacity 未知时为 null；不得将本机额度称为服务能力。
