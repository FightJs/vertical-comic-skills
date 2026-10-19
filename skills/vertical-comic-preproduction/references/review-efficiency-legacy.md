# 审查与批准复用：scoped_half_review_v1

本文仅供原先冻结为 `scoped_half_review_v1` 的旧RV恢复。当前新RV使用 [整话异步生产](episode-async.md)。

启用readiness_policy=panel_readiness_v1时优先按 [全话准备、逐格放行](panel-readiness.md)：全话总览保持完整，就绪设计和完整输入按准确范围集中交B及包审，缺口列待补；当前半话获批独立格可先生成。前格设计未定及真实图片依赖继续等待，C/D仍须完整。本文全话准备一次不要求无关缺口清零；未声明该策略的旧RV继续原完整准备门禁。

新初始化的完整v2任务启用 episode_preparation_v1 与 incremental_runtime_v1：全话资产/A、镜头/B、语义/比例及生图包各准备一次；H001/H002只划分实际生图、自审、修正和连续性审查。每话H001完成立即交C，C获批后H002沿原全话批准依据推进。具体执行见 [增量执行](runtime-efficiency.md)；旧RV按其原冻结合同恢复。

新任务同时声明 `execution_mode: half_episode_async_v1` 和 `optimization_policy: scoped_half_review_v1`。本合同改变输入冻结范围、局部暂停和审查调度；六项逐图质量、原稿锁定、真实参考、规则记忆、实图依赖、第一半话C、最终D和最多一轮自动修正继续执行。未声明优化策略的旧RV仍按原门禁恢复；未知策略必须HOLD，不能降级。

## 固定流程与人工审查

审计完整源稿/准确格序 → 整话必要资产与A → 整话镜头/语义/比例与B → 整话生图包确认 → H001并发提交、返图即审、必要修正 → C第一半话 → H002沿原批准包生产与审查 → D全话及跨话比较 → 逐格成品包。

新增包确认及等审消息首行按 [review-progress.md](review-progress.md)。原8阶段编号保持；第2/3/6/8和包构建完成需要人工确认时显示简短进度。一次准备齐再提交审查，适用同版本/范围批准和明确依赖补齐方案复用，常规修正不另加逐图停点。

整话A/B和生图包维护一套总览集中审查；启用readiness时按准确就绪范围先批准、待补差异集中增补，H001/H002各自保留实际请求、QA和修正记录。C获批后H002直接使用原批准全话依据。各话有批准就独立推进。第一半话未获C前，只能准备第二半话输入，不能提交第二半话生图。

给用户的每次审查包包含源序联系表、批准样例对照、复用依据、具体新增差异/未解决问题、建议可批准的精确话/格/版本范围。只让用户回答需要判断的项目；提供明确的整批确认句。用户沉默、技术PASS和待审模板都不是批准。不额外派独立审查agent占用各话执行者；同一agent实际看图就如实记录。

## 全话准备与批准索引

`episode_preparation_v1` 在输入审计后为每话准备一份视觉基准、一份覆盖源格序的镜头、一份全话语义核对与一份全话生图审查包。必要人物/衣装/场景资产在A前集中补齐；全话比例计划在B前完成。H001/H002仅是生图、逐图QA、修正及半话连续性窗口，不各建资产或镜头版本。

生产流程根字段使用 `visual_basis`、`shot_manifest`、`semantic_audit`、`gates.visual_basis` 和 `gates.shot_design`；`generation_packages.EPISODE` 登记整话包文件引用。`half_inputs/half_gates` 仅供未迁移旧RV恢复。全话镜头必须准确覆盖完整源序、锁定原文并声明 `preparation_policy: episode_preparation_v1`；每个实际单格执行包也绑定该策略。

A实际批准覆盖源文件、源快照、根visual_basis；B覆盖根visual_basis、根shot_manifest、语义审计及全话比例计划。全话包批准覆盖该包、根visual_basis及根shot_manifest，未声明readiness策略时panel_ids须涵盖整话；启用时须准确覆盖此次实际批准范围。C覆盖H001实际图；D覆盖完整话及跨话需要的真实图。A/B/包可合并展示但分别存真实用户消息及成果版本；生产授权和技术PASS不能替代任何批准。

`approval_index_v1` 可登记 visual_basis、shot_design、generation_package、state_review、pilot、final 的原始批准引用。索引只供检索，不扩张原消息的格范围或改写哈希。新模式先检查根gates的直接证据，再查索引；任何批准必须与当前文件哈希和准确源格范围相符。C通过后H002复用上述全话依据，不重新索取A/B/包批准。真实变更只对受影响的基准、镜头或包重审；旧RV不因配置更新自动迁移。

## 局部HOLD与新状态

局部问题写进本话 `holds`，要有实际影响范围和非空evidence。例如后半话服装问题：

```json
{"scope":"panels","panel_ids":["P021","P022","P023"],"evidence":"实际核查表中的缺口与受影响格，待批准衣装参考"}
```

允许scope=half（half_ids）、panels（panel_ids）、states（state_keys）。book/episode、未分范围的旧HOLD、缺依据/无效范围均按全局或当前半话HOLD处理，不能默认无影响。真实实图依赖继承暂停。启用readiness时，B就绪选集的镜头与必要资产须完整，其他格显式待补；未启用时全话B前须完整；生产中出现新增局部问题时，仅暂停受影响格和真实依赖，回到相应依据版本处理。

共享control.holds/job.status=HOLD仍是整个调度任务暂停；局部衣装缺口不要误写成全话任务HOLD。本半话被暂停的格和依赖它的格不能领许可；启用readiness时其他获批独立格在准备阶段即可继续。输出eligible_panel_ids与blocked_panel_ids供总控调度，不能把局部阻塞当作整批通过。

B逐格明确 `state_review_policy`：

| 值 | 行为 |
|---|---|
| user_required（缺省） | 新状态首次实图六项QA通过后，仍需真实单独用户批准；只有使用该状态及依赖它的后格等候，其他场景可继续 |
| merge_into_C | 仅H001普通新状态，经B明确批准后，样图六项QA通过即可释放同状态后格；最终由C一起人工审查 |
| merge_into_D | 仅H002普通新状态，经B明确批准后按上述方式释放；人工审查合并到D |

新RV若在使用配置和生产流程中同时声明 `state_dispatch_policy: ordinary_state_parallel_v1`，上表两项普通状态的“样图QA后释放”改为：B及逐格生图包批准、实际输入和许可齐全后，同半话后格可以与首图同时提交。首图仍是优先返图自审和连续性校准锚点；图片返回前不得记QA通过。`user_required`、`requires_state_review:true`、`calibration_anchor:true` 和真实 `generation_dependencies` 继续执行原屏障。共享状态出现实际失败时，立即诊断并按证据对尚未提交的受影响格建立局部HOLD；在途结果继续收集和审查，不以自动改标记或重复提交掩盖问题。旧RV未声明新字段时保持上表原行为。

明确 `requires_state_review:true` 的高风险图只能user_required，不可合并。新身份、重大衣装/伤势、复杂空间关系等需要用户首次实图判断时应标高风险。不能生成后为了速度修改获批字段。默认仍保留单独停点；C不隐式替代user_required，也不能借第一半话末格进入H002绕过确认。合并只减少人工往返，样图QA及真实前格实图依赖照常执行。

## 返图即审与避免重复验收

`runHalfWave(jobs,limit,invoke,onResult,{onReviewReady})` 的onResult先串行保存真实结果/证据；保存成功后onReviewReady发待审通知/刷新队列并yield给模型。通知不占生图调用槽，其他invoke继续运行。回调不能伪造看图结论；真正审图由agent用实际原图及批准参考完成，再串行保存QA/进度。仍有在途Promise时保持exec存活并用wait恢复，不能为审图结束执行器。总控共享control依然单写，审图与返回回调不得同时覆盖本话状态。

初次生成和每张修正图都完整审身份、画风、衣装、动作接触、空间、构图规格及命中规则。可以用所选已返回格的联系表减少打开成本；疑点/细节看原图，不要求未返图先出现。所有请求终结后只补尚未审完的图，并做整半话连续性、边界和轮次汇总。

对未变的合格保留图沿用原始实际QA。复用前机器核对当前图片、冻结包、实际prompt_file、参考/批准/调用返回证据、QA及命中规则版本；任一失效重审受影响项。当前镜头/基准适用性、dispatch与连续性仍单独校验。更换基准或修改设计不能靠旧QA放行。

`review_reuse.py` 写出的候选只是原QA复用定位，不是APPROVED/PASS凭据。staged_workflow只在一次门禁运行中对真实通过且内容指纹相同的QA记忆结果，重复调用免除重复深校验；不相信持久缓存标记。新agent仍读取必要实际参考，缺少可复用真实看图记录必须审图。

```text
python <scripts>/review_queue.py --state <本话>/00_输入审计/生产流程.json --batch H001 --write <本话>/06_图片验收/H001/待审_新版本.json
python <scripts>/review_reuse.py --state <本话>/00_输入审计/生产流程.json --panel P001 --write <本话>/06_图片验收/P001_复用候选_新版本.json
```

以上命令只写新审阅辅助文件，不调用生图、不改状态/批准、不代替六项目视检查。流式待审与轮次汇总是不同用途：未终结请求不计入完整轮次，仍按0/1–5/超过5失败策略及最多一轮修正收尾。合格图保留，返修图全部六项重审，最终D之前不能称已验收成品。

## 旧RV迁移

配置更新只影响新初始化。旧任务按原冻结记录恢复，不在生产中原地加标记。用户明确迁移时建新RV，复制源快照、适用真实批准和原请求/输出/QA（保留文件与相对引用），建立并冻结一份覆盖全话的视觉基准、镜头、语义核对和生图包，记录原来源；旧epoch回执按carry_forward核对。旧半话镜头与新全话镜头不是相同文件版本，须审查新增冻结范围及设计差异；首三/五格批准不扩成半话C或全话A/B/包批准。未变的原图可复用，缺真实QA则补审，不能补写成新生成。迁移不需改源脚本或规则库。

收益主要来自减少重复审查、无关暂停和人工往返；脚本测试验证调度/门禁，真实服务渲染与返修率仍须按submitted_at/returned_at、QA和批准时间实测，不承诺固定倍速。

v2在共享execution_contract.py中一次预检本批就绪格，复用同一进程内内容绑定QA；全话语义核对一次冻结。准备/候选不再当作可生产完成；设计上下文不造成无必要的前格生图串行。 详细字段、命令和恢复规则见 [生产兼容与提速](execution-compatibility.md)。

本批新增进程内规则路由复用：索引内容哈希未变复用解析，阶段/实际画面/标签未变复用命中集；不缓存检查结论。批量预检报告显示rule_routing_reuse_statistics。QA模板提供单次观察清单，原判据分别核对，阶段基准按读取合同预读、专项正文按命中补读；规则变化只使受影响内容复用失效。 归属与正式来源见 [rule-ownership.md](rule-ownership.md)。

新runtime的H001→H002只更新本话job.active_batch_id和实际容量；全话frozen_inputs保持原版本，不新增frozen_halves。C通过、全话包适用且旧半话无在途许可后进行，保留H001历史与其他话状态。
