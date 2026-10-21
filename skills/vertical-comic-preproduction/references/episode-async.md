# 整话异步生产：episode_async_v1

新运行统一按[第一批生产决定](production-decisions.md)衔接审核、返修与交付：真实FAIL不改写，处理动作与交付结论分别记录；旧冻结合同不迁移。下文审核方法、源稿/批准/证据要求仍适用。

新RV显式使用 `preparation_policy=episode_preparation_v1`、`readiness_policy=panel_readiness_v1`、`execution_mode=episode_async_v1`、`optimization_policy=scoped_episode_review_v1`、`execution_contract=comic_execution_v2` 和 `runtime.policy=incremental_runtime_v2`。每话一名唯一执行agent，最多按配置同时运行多话；整话 `batch_plan` 只有 `EPISODE`，格号与原稿顺序一一对应。旧半话RV继续按原冻结合同，不把H001/H002、C或批准范围直接改名为EPISODE。

默认亲审节点为A视觉基准、B镜头与全话生图包分别批准、实际高风险新状态的单独确认、D整话/跨话最终验收。明确用户委托覆盖的节点按[完整交付请求](grouped-review.md#完整交付请求)记录执行者决定，不再重复等用户；保留亲审项和旧冻结合同不自动取消。没有固定半话C停点。普通新状态只有在B明确 `merge_into_D`、批准依据和本格生图包齐全时才可并发；`user_required`、`requires_state_review`、`calibration_anchor` 和真实 `generation_dependencies` 仍等待相应实图/批准。首现状态与实图依赖锚点优先返图自审，不等待普通格逐张返回才提交后续独立格。

每次调度先运行readiness/status，列出整话eligible_panel_ids和逐格阻塞理由。新配置按[批次运行](batch-runtime.md)由总控一次分配容量租约，本话用episode_dispatch_queue.py在租约内批量领取唯一回执，再运行production_runtime.py --action compile --panels完整预检，通过后登记提交窗口并立即实际调用。真实返回保存和证据核验后，本话原子登记图片与COMPLETED回执，不逐请求等根节点同步。编译失败且确定未进入提交窗口的预留可显式释放；未知请求继续占槽并查原请求。旧未启用租约的RV保留总控单写permit及双哈希CAS，不静默迁移。普通独立格按核定容量持续补入；一个请求最多五条参考，与实际在途容量无关。保存回调不填QA或用户批准。

```text
python <scripts>/episode_dispatch_queue.py --state <本话/00_输入审计/生产流程.json> --expected-state-sha256 <当前状态sha256> --expected-control-sha256 <当前调度控制sha256>
python <scripts>/production_runtime.py --state <生产流程.json> --action compile --panels <上一步reserved中的格号>
```

B阶段只为真实有风险的格填写镜头 `production_risks`：`lower_edge`（画面下缘）、`action_target`（动作对象）、`support_contact`（承托接触）、`prop_count`（道具数量）；每项写 `{kind, constraint}`。单格包复制相同清单，实际prompt逐字包含具体约束，候选包和请求预检核对。没有该风险的格保持空清单，避免统一叠加长提示词。

首轮失败格经实际QA和最早失败层诊断后可单格开启唯一第二轮，不等整话首轮结束。执行层返修写 `episode_repair_v1` 文件：`panel_id`、与当前失败行相同的 `failed_attempt` 快照、`route=targeted_image_repair`、`reviewer`、`evidence`、非空 `repair_constraints`、`new_attempt_id`、`new_package_manifest`、`new_shot_subset`。新包的 `round_context` 为 `EPISODE/2/new_attempt_id`，实际prompt逐条包含修正约束，原失败记录保留于attempt_history；用 `production_runtime.py --action repair-authorize --repair-authorization <本话相对路径> --expected-state-sha256 <当前状态哈希>` 原子登记。参考、镜头、画风依据错误先回对应A/B/包，不写成执行返修。累计超过5张实际视觉失败时，先写 `episode_failure_diagnosis_v1` 文件，含当前书话、`status=REVIEWED`、`reviewer`、`evidence`、`common_cause` 和覆盖当前失败格的 `reviewed_failure_panel_ids`，用 `production_runtime.py --action diagnosis-record --diagnosis <本话相对路径> --expected-state-sha256 <当前状态哈希>` 原子登记；再继续失败格返修。独立首轮请求不必停。第二轮仍失败停止该格并诊断，不发第三轮。调用失败/结果未知不计入五张视觉失败。

返修若实际携带失败图，先按 [生图合同的返修输入冲突预检](generation-io.md#返修输入冲突预检) 填 `repair_focus`，核对失败图用途与真实失败项不互相冲突；接触关系修正写可观察的人物和手臂路径。`repair-authorize` 与随后每次调用前都会拦截冲突和过期流程文字，不消耗请求额度。旧RV人工额外补救先用同一脚本检查，但不把旧授权、轮次或QA自动迁移到整话模式。

批量许可生成的返修派发包仅添加 `dispatch_source_package` 与一次性 `dispatch_receipt`；校验器逐字段比对原授权包，不允许借派发换prompt或参考。

派单支持`--max-count <本次最多领取数>`：在实际剩余容量内按源序检查未领取候选，足够即停止；遇到局部输入问题继续寻找后续可派格。全话批准、状态屏障和真实依赖仍先核验。具体缓存边界、计时与原双锁范围见[runtime-efficiency.md](runtime-efficiency.md#派单按容量预检)；不为优化自行添加覆盖所有话和只读编译的全局串行封装。

所有源格的图片/审核/未完成去向均登记后，`batch_reviews.EPISODE` 记录整话真实连续性核对；D还核对全话画幅分布、实际跨话图、原批准样例、身份/衣装/场景及最终图片哈希。未返回、未审或局部HOLD不能计为可用图；第一批交接索引仍须列出这些格。交接按源序保存采用图片及问题表，不拼接、上气泡。

迁移旧RV时新建RV，先解决在途/未知请求和旧HOLD，再将H001/H002格号映射为新EPISODE源序；复制原请求/图/QA/批准证据及真实哈希，保留旧attempt和自动返修预算。旧C仅是历史审查，不扩大为新整话或D批准。用当前共享检查器一次核对源号、参考别名、派生尺寸和回执，再冻结工具版本；不在各话复制临时检查器。共享脚本或五个SKILL入口变化会改变toolchain哈希，不能改旧RV的哈希假装通过。

生产复盘至少记录：首轮实际就绪格数、容量空闲到提交的时间、实际在途峰值、提交到返图时长、首轮QA通过率、返修张数、人工等待时间与整话到D的墙钟时长。整话池扩大只是减少人为停点；服务吞吐与成图质量须由真实试运行验证。

新初始化整话RV默认visual_evidence_v1，具体合同见 [空间、细节与原尺寸审查](visual-evidence.md)。设计连续性不自动成为generation_dependencies；普通格持续并发，实际连续性比较可后补但必须完成才验收。局部质量缺口只暂停准确影响范围，不新增全话人工停点。

## 固定运行与合并审查

新任务先读[批次运行](batch-runtime.md)和[合并审查](grouped-review.md)。新租约策略由总控一次分配容量，本话领取与提交回执、登记真实返回并释放已完成槽位，不逐请求根握手；本页旧总控permit调度仅供未启用租约的RV。B与包同次审查分别记录决定，高风险实图与D均须真实审查；适用委托内由执行者决定，保留亲审项才等待用户。

现有就绪集合保持异步，不为全话普通镜头增加锚点串行屏障。当前方向/状态已有足够证据时直接编译；确实需要真实前图才能确定的接触、空间或高风险状态才保留依赖。返回落盘与QA队列分离，技术上下文HOLD先诊断输入，不能触发整图返修。真实事件与未知结果处理见runtime-efficiency.md、batch-runtime.md。


需要短锁派单时，先读[一致性协议](dispatch-consistency.md)。新协议默认关闭；只有显式准入且保存器接好submit/evidence/save/recover的租约运行可用。候选input_read_head不能启用生产路径；普通及不支持运行继续原合同。
