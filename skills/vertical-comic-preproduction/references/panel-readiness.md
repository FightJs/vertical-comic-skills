# 全话准备、逐格放行

新运行优先按[第一批前期提速](preparation-efficiency.md)执行最小充分设计、代表格接线、单次B/包展示及问题分级处理。可选润饰不产生HOLD；真实缺口在现有委托内修复，局部问题只影响真实依赖，其他工作继续。正式输入与接包要求仍按原合同。

新配置使用 `readiness: {"policy":"panel_readiness_v1"}`，初始化到生产流程、全话镜头和执行包的 `readiness_policy`。当前配套 `episode_preparation_v1`、`episode_async_v1`、`scoped_episode_review_v1`，保持一套全话源序、镜头和比例计划；旧半话配套仅用于原RV恢复。不能在运行中的旧文件直接加字段或改工具哈希。

## 各阶段做什么

| 阶段 | 固定行为 | 减少等待的方式 |
|---|---|---|
| 1 输入审计 | 核对本批源稿、完整格序、批准来源和缺口 | 一次登记准确受影响格、状态及真正依赖；不为一格缺口把整话改成调度HOLD |
| 2/A 视觉基准 | 核对实际身份、衣装、场景与画风 | 原批准适用就复用；缺状态只阻塞使用该状态的格 |
| 3/B 镜头及生图包 | 一次准备全话总览，集中展示镜头与实际输入，分别记录批准 | 总览保留全部源格；就绪范围先交审，待补范围明确列出；候选设计可审，未满足全部条件的格仍不可调用 |
| 4 整话生图 | 按完整预检和真实许可提交 | 整话获批独立格持续提交；实际依赖格等真实前格QA |
| 5 自审及修正 | 返图保存后增量六项QA、适用记忆和连续性 | 未变真实QA复用；合格图保留；依赖/校准图优先审；仍最多一轮自动修正 |
| 6 整话连续性 | 全部源格真实图、QA与相邻格连续性 | 局部先审，整话最后核对；未变图复用内容绑定QA |
| 7/D 成品验收 | 全话实际图、比例分布、连续性及适用跨话实图比较 | 待处理清零后交付；不能把局部放行当整话验收 |

## 两种就绪与依赖

`production_runtime.py --action readiness`只读导出：`ready_for_review_ids`为本话设计可审范围，`prepared_panel_ids`为本地准备及设计边界检查通过范围，`blocked_panel_ids/blockers`列缺口。它不检出实际可调用许可，也不授予批准。`bundle`核对实际输入，`compile`再执行完整提交门禁，只有输出jobs可按真实许可进入生图工具。

上一话批准设计暂未交接，只形成本话首格的 `boundary_comparison` 缺口。本话首格自身设计已明确、局部核对已完成时，可将其设计随B交审；缺少上一话比较仍阻塞首格调用。后格以已获批的本话设计作机位/空间上下文，可以独立推进；不把缺少跨话比较推断为人物或空间都未知。

`generation_dependencies`表示真正需要前格实际图片；它继承任何前格调用HOLD。`design_dependencies`及同场景的 `continuity_contract.scene.previous_panel_id`继承未确定的设计；人物站位、空间、裁切尚未定时，依赖后格不能抢跑。设计比较依据、真实图片依赖分别核对，禁止全部清空或标“新场景”绕过。

局部HOLD在新整话模式声明 `scope=panels/states`、准确 `panel_ids/state_keys`及非空evidence；旧 `scope=half` 迁移时须明确映射到格。首格只有缺上一话比较时，可另声明 `dimension=boundary_comparison`；该标记不能替代实际诊断，其他同时存在的设计/状态HOLD仍继承。无范围、无依据、书话/源序/共同画风/全话比例错误按原全局门禁处理。

例如28格中只有P001缺跨话比较、P009缺本格批准，其余26格中设计、上下文、批准及输入独立齐全的格可先提交；有真实依赖的格继续排除。D仍等待全部28格及连续性，不删P001/P009，不补造QA。

## 候选上下文与真实批准

镜头准备读取本话候选设计时，可用 `continuity_context.py --candidate`；必须是当前运行、同一本话根目录和完全相同四项冻结来源。候选上下文不写APPROVED、不伪造B。旧话来源仍须真实A/B；实际生成时当前话来源也须真实A/B及准确来源格范围。

保留一份完整全话总览，不为每格复制竞争镜头文件。B按实际可审的设计范围获批，包按完整技术预检后的输入范围获批；两者不能互相替代。首格设计可审、但跨话比较待补时，B材料和HOLD必须同时写明，不能声称该格完整规则执行已经通过。

新全话候选包继续 `scope=episode`、`panel_ids=完整源序`，另有 `coverage`、`approval_panel_ids`、`pending_panel_ids`、`design_review_panel_ids`、`blockers`、`candidate_technical_errors`。只有 `approval_panel_ids`内的输入或精确实图依赖补齐方案可作为包批准范围；未填包、未审语义、未准备依赖方案的格列待补，不拖住其他完整输入。若没有完整可审输入，直接报缺口，不索取空包批准。

每份原用户批准的 `panel_ids`与索引检索范围都须准确。可合并多份原批准覆盖不同格，但不能扩大任何单份批准。补齐时集中交审新增差异，不增加逐图固定人工停点。上一话的B真实批准就绪后由总控登记 `continuity_sources`，保留原来源、消息、文件哈希与话序；不要等待上一话D或最终图片包才交接设计。实际跨话图片比较仍留D。

## 未变范围复用

保留原批准文件、原镜头文件和原包，不覆盖或重新签名。补齐其他格或首格上下文后，检查器逐项比较本格设计及所有共同设计头：来源、身份注册、状态、参考、画风、记忆来源等。仅当其不变时，原批准可在原范围继续适用；当前实际输入仍全门禁核对。变了本格机位、prompt、参考、身份状态或共同依据，则回受影响B/包/A审查。

`generation_packages.EPISODE`可登记多份保留的原包引用。实际调用必须与其中某份已批准包的准确本格签名一致，或严格按该包批准的实图依赖槽补齐。新的总览不能改变旧包批准。全话比例计划仍完整核验，保持竖版严格大于75%和交错分布。

只读检查事务内复用文件哈希、JSON和成功的忠实图集像素核验；图集键包含当前工具、人物用途、原资产、裁区和实际像素版本。失败不缓存，事务内文件变化立即拒绝旧证明；下一事务重新检查。不跨进程持久信任，不缓存模型视觉结论或生成用户批准。

## 固定入口和进度

~~~text
python <scripts>/production_runtime.py --state <本话生产流程.json> --action readiness
python <scripts>/production_runtime.py --state <本话生产流程.json> --action bundle --write <本话/04_B提示词包_CANDIDATE/全话生图审查包_新版本.json>
python <scripts>/episode_dispatch_queue.py --state <本话生产流程.json> --expected-state-sha256 <当前状态哈希> --expected-control-sha256 <当前调度哈希>
python <scripts>/production_runtime.py --state <本话生产流程.json> --action compile --panels <已领取许可的格号> --write <本话/04_B提示词包_CANDIDATE/整话实际就绪调用_新版本.json>
~~~

有已完成的精确实图依赖方案时，bundle加 `--dependency-plan <本话相对路径>`；未完成的方案对应格保持待补。candidate输出不能送入实际工具。工具版本更新须由总控在新RV重新绑定真实冻结来源及许可，保留旧epoch和carry_forward证据，不能改旧回执让它看起来获批。

进度同时报准备可审/待补数、实际提交/返回/合格数和缺口格号。例如：

~~~text
【E025｜B待审】全话28格总览｜当前可审输入26/28，P001/P009待补｜状态：待批准就绪范围｜下一步：批准后提交独立格
~~~

批准后实际提交数按真实调用写，缺口继续单列；不要再用“候选准备完成、全话HOLD、正文0”代替各范围状态。bundle的 `preparation_check_elapsed_seconds`与compile的 `preflight_elapsed_seconds`只计检查器耗时；人工等待、生图提交/返回、保存与实际QA用原真实时间戳记录，不将检查耗时冒充前期创作时间或服务耗时。

跨话前序镜头设计未定与实际图片比较待补必须分开。只有真实generation_dependencies等待已验收前格图片；仅待最终比较不得新增图片输入依赖。待比较图可保存本地观察但最终通过前须完成原真实比较；独立就绪格持续生成。

v2最终输入审查明确区分静态准备闭合、等待真实参考、可以提交。prepared_panel_ids本身不证明实际输入已审；正式前期交付须同时检查final_input_semantics覆盖全部源格，pending_real_reference_review_ids只表示已审补齐方案尚待实际图片。生产前继续实时门禁，独立格可并行；详见[最终输入收敛](final-input-semantics.md#前期收敛按包执行v2)。
