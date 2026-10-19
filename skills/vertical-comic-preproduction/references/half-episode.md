# 半话异步生产合同：half_episode_async_v1

本文仅供原先冻结为 `half_episode_async_v1` 的旧RV恢复。当前新RV使用 [整话异步生产](episode-async.md)。

启用readiness_policy=panel_readiness_v1时优先按 [全话准备、逐格放行](panel-readiness.md)：全话总览保持完整，就绪设计和完整输入按准确范围集中交B及包审，缺口列待补；当前半话获批独立格可先生成。前格设计未定及真实图片依赖继续等待，C/D仍须完整。本文全话准备一次不要求无关缺口清零；未声明该策略的旧RV继续原完整准备门禁。

新初始化的完整v2任务启用 episode_preparation_v1 与 incremental_runtime_v1：全话资产/A、镜头/B、语义/比例及生图包各准备一次；H001/H002只划分实际生图、自审、修正和连续性审查。每话H001完成立即交C，C获批后H002沿原全话批准依据推进。具体执行见 [增量执行](runtime-efficiency.md)；旧RV按其原冻结合同恢复。

新任务默认本模式。批次是每话的一半：源格数 N，第一半话 ceil(N/2)，第二半话剩余格；30格15＋15，35格18＋17，1格只有第一批。从真实批准源脚本提取格序，不根据大约格数计算。旧 batch5_v1 和未声明模式的单格任务保留原行为；切换需新RV及真实批准范围复核，不能把首五格批准扩成首半话批准。

新初始化同时启用 [scoped_half_review_v1](review-efficiency.md)。episode_preparation_v1先冻结完整话的A视觉基准、B镜头、语义核对和生图包；H001/H002只划分生成、逐图QA、返修和半话连续性。旧RV保留原半话准备合同。

固定流程：全话输入审计 → 全话必要资产与A → 全话镜头/语义/比例/依赖与B → 全话生图包确认 → H001并发生成、自审、必要修正 → C → 沿原批准全话依据生产H002并自审、必要修正 → D全话及跨话实图复核 → 逐格成品包。只有全话包首次生图前需要包确认；H002普通推进不重复A/B/包审查。

## 半话、依赖与并发

优化策略的build_plan仅使用完整只读源快照形成H001/H002；max_batch_size为ceil(N/2)，pilot_panel_ids为第一半话全部格。各半话状态停点在门禁中由批准镜头requires_state_review与新visual_state_keys首现计算，不写入可变全话计划。旧半话计划仍包含全话基准/镜头和state_barriers。仍维护 generation_dependencies，只引用前序实图，不把普通剧情顺序当依赖。

一个工作agent负责一话，当前半话的全部独立请求连续提交、同时在途；半话15张就目标15请求，不再固定10或5。五话总目标取当前活动半话请求容量之和，而非固定50。全局额度和每话额度同时约束，实际以当前工具容量为准；后端排队不等于服务器同时渲染。未知容量先核对实际接口/调度能力，在实际半话中依据反馈确认有效额度，不长期无依据退化成单张串行，也不虚报无限并发。

优化策略的新状态只暂停使用该状态及依赖它的后格，其他独立格可继续；user_required样图真实六项QA及单独用户确认后释放，B批准普通状态merge_into_C/D时真实QA后释放，明确高风险仍单独确认。旧未启用优化策略的屏障保持原全后序暂停。同批实图依赖的前置图一返回就检查，满足依赖后可继续提交，不等全批返回导致死锁。C仍覆盖整个第一半话；校准格合格图保留使用。

若新RV额外声明 `state_dispatch_policy: ordinary_state_parallel_v1`，已获B与包批准的普通 `merge_into_C/D` 状态可在首图QA前并发提交同半话其他格；首图优先自审，但只作质量反馈，不作普通后格提交门禁。明确高风险、`user_required`、`calibration_anchor` 与真实前格实图依赖照旧等待。状态失败要按实际影响范围诊断及局部暂停后续新提交；全半话QA、C/D和修正轮次不缩小。未声明此字段的RV沿原屏障恢复。

进入下一半话前，H001全部图与连续性均通过且C获批；H002从同一批准全话镜头/生图包选取，补齐已批准的真实前格依赖并重新运行实际调用门禁。新状态校准失败使后格未提交时进入STATE_FAILURE_HOLD；前置依赖失败则进入DEPENDENCY_FAILURE_HOLD，不虚构未提交格的失败或完整轮次。

## 自审与修正

身份、画风、衣装、动作接触、空间、构图规格全部逐张审查，另外核对规则记忆、批内及前后边界；缩略总览用于比较，疑点打开原图。实际看图者如实填写，切换Skill不是独立审查者。

失败按图片去重，不按错误条数计数。0失败且连续性通过放行；1–5失败先局部诊断；6张及以上先记录共因分析（参考、画风、衣装/场景状态、空间、提示词），再修失败格。新模式只允许一次自动修正，第一轮生成＋第二轮定向修正。CALL_FAILED/RESULT_UNKNOWN/CANCELLED单独统计并进入调用HOLD，不能当视觉失败或PASS。

第二轮只覆盖首轮失败集合，合格图片及其原请求/QA不重生成、不改写。修正约束进入实际prompt，operation=repair，每次携带原始批准样例和适用身份衣装/场景。保留全部首轮文件和记录。第二轮修正图每张完整重审；优化策略核对未变保留图原QA/内容指纹后复用，再补全半话连续性与边界检查。第二轮仍失败或异常则STOP_DIAGNOSE，禁止第三轮自动抽图。根因需要修改批准基准时回A/B处理受影响范围，不能擅改依据后继续。

## 状态和报告

生产流程保留 staged_comic_v1，新增/填写：

```json
{
  "execution_mode": "half_episode_async_v1",
  "optimization_policy": "scoped_half_review_v1",
  "state_dispatch_policy": "ordinary_state_parallel_v1",
  "preparation_policy": "episode_preparation_v1",
  "visual_basis": {"path": "00_输入审计/全话视觉基准.json", "sha256": "实际哈希"},
  "shot_manifest": {"path": "01_镜头改编_CANDIDATE/全话镜头.json", "sha256": "实际哈希"},
  "semantic_audit": {"path": "00_输入审计/全话语义核对.json", "sha256": "实际哈希"},
  "gates": {"visual_basis": {}, "shot_design": {}},
  "generation_packages": {"EPISODE": []},
  "batch_strategy": "half_episode",
  "review_policy": {"systemic_failure_count_gt": 5, "max_auto_correction_rounds": 1},
  "batch_plan": {"path": "00_输入审计/半话计划.json", "sha256": "实际哈希"},
  "round_reviews": {"H001": {"1": {"path": "06_图片验收/H001/首轮.json", "sha256": "实际哈希"}}},
  "batch_reviews": {}
}
```

空模板不填假引用。每格当前尝试字段为 panel_id、attempt_id（唯一非空）、round_id=1或2、status及既有 package_manifest/shot_subset/output/qa_report。PENDING→IN_FLIGHT→GENERATED→VISUAL_PASS或VISUAL_FAIL；异常状态CALL_FAILED/RESULT_UNKNOWN/CANCELLED。普通HOLD须解决，不能改成PENDING伪装新任务。

优化策略单格执行包另声明相同optimization_policy。每个单格执行包顶层 `round_context: {batch_id,round_id,attempt_id}` 与本格当前尝试对应，保留原镜头/身份/风格/规则合同。实际 generation_execution.attempt_id 与其一致。首轮失败另存 failure_diagnosis:{reviewer,evidence,layer}，在真实六项QA中明确FAIL项。不能只改状态虚增失败张数。

首轮结束运行 batch_round.py 建汇总模板：half_round_v1，包含准确书话/批次/首轮全部panel_ids、基准/镜头/策略版本、attempts源序快照、去重失败/合格/异常格号、strategy。status默认UNREVIEWED；实际核对汇总后填REVIEWED、reviewer/evidence。模板脚本不看图、不自动通过。

有失败时填 diagnosis:{reviewer,evidence,earliest_layer,requires_basis_change:false,repair_constraints:{失败格ID:[具体修正与保留原句]}}；SYSTEMIC_REPAIR另填common_cause_analysis。不需改基准必须真实确认，不填false来绕过冲突。

编译第二轮时，将原首轮快照完整放入该格attempt_history，保留原文件不覆盖；当前格改round_id=2、新attempt_id、新执行包，状态REPAIR_AUTHORIZED。首轮报告快照包含 panel_id/attempt_id/round_id/status/package_manifest/shot_subset/qa_report/output/failure_diagnosis/call_evidence中实际存在的字段，不能附带当前时刻无关字段。旧QA/返回仍绑定原调用，不补写成第二轮。

第二轮汇总的attempts覆盖全半话：合格保留格仍round1，修正格round2。绑定当前图/QA，全部为PASS后strategy=ALL_PASS。独立batch_review_v1连续性报告还须绑定本半话全部outputs与上一半话previous_outputs，包含plan中state_barriers；轮次汇总不能替代实际连续性检查。C覆盖基准、镜头、首半话所有当前outputs；D覆盖全话当前outputs。多话交付仍要原cross_episode_review_v1。

## 调度回执

复用 parallel_episodes_v1 单写总控。每个半话job新增 active_batch_id=H001或H002、max_inflight（正整数，不超过当前半话格数）；control.max_inflight为本任务实际核定的全局额度。

episode_preparation_v1的job.frozen_inputs冻结source_script/source_snapshot/visual_basis/shot_manifest；不使用frozen_halves。H001→H002只变active_batch_id及当前容量。最终cross_episode_review.episodes绑定全话visual_basis/shot_manifest与全部源序outputs/qa_reports。旧half_scoped_v1任务仍按其frozen_halves恢复。

每个permit和单格dispatch_receipt都增加batch_id/round_id/attempt_id，与执行包round_context一致。先RESERVED并逐格完整generate检查，提交前IN_FLIGHT；实际返回COMPLETED+output_sha256或准确异常状态及证据。并发数计算仍含RESERVED/IN_FLIGHT；同话同格不得有两个活动许可。原首轮完成许可永久保留，第二轮另领新许可，不能复用ID。

协调者可一次预留当前就绪请求的一组许可，减少逐张沟通，但每格仍检查实际输入。总控单写共享control；执行者串行落盘本话状态，工具调用并发。停止、更换agent/epoch后的旧返回仍按原carry_forward合同核对。等待C的job在调度中标WAIT_REVIEW，不领下一半话许可。

## 命令

```text
python <scripts>/batch_workflow.py --state <新RV>/00_输入审计/生产流程.json --write-plan <新RV>/00_输入审计/半话计划.json
python <scripts>/staged_workflow.py --state <新RV>/00_输入审计/生产流程.json --check generate --panel P001
python <scripts>/batch_round.py --state <新RV>/00_输入审计/生产流程.json --batch H001 --round 1 --contact-sheet <新RV>/06_图片验收/H001/半话总览.jpg
python <scripts>/batch_round.py --state <新RV>/00_输入审计/生产流程.json --batch H001 --round 1 --write <新RV>/06_图片验收/H001/首轮候选.json
python <scripts>/staged_workflow.py --state <新RV>/00_输入审计/生产流程.json --check status
```

新文件使用尚不存在的路径；上述命令不派agent、不调用生图、不授予批准。半话总览直接读取各格当前output及哈希，保持源序，不覆写已存在图；可在实际图都返回、尚未QA时生成审阅辅助，不填PASS。逐格QA仍使用各单格冻结执行包，不能用聚合总览报告代替。汇总只在本轮请求已终结且各图已真实审查后制作。实际工具并发执行另读 [async-generation.md](async-generation.md)。

v2新状态首格失败可使用严格单格校准报告进入本半话唯一第二轮，后格未提交不要求虚构其QA；全半话首轮汇总保留该格真实原FAIL，第二轮汇总保留已校准结果，禁止第三次自动修正。 详细字段、命令和恢复规则见 [生产兼容与提速](execution-compatibility.md)。

新runtime的H001→H002是本话调度变化：本话C通过、全话包对H002格仍适用且旧半话无在途许可时，总控单写更新active_batch_id及max_inflight；全话冻结依据保持不变，不增添frozen_halves。保留H001文件/QA/批准/历史许可及其他话状态。
