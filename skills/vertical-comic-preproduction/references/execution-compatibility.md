# 生产兼容与提速合同

当前新RV按 [整话异步生产](episode-async.md) 使用 `episode_async_v1`、`scoped_episode_review_v1`、`incremental_runtime_v2`：全话总览保持完整，就绪设计和完整输入按准确范围交B及包审；总控批量领取真实空闲permit后完整预检；整话完成后交D。本文源号、图集、前格上下文、日志与规则合同继续适用。下文涉及H001/H002、C、`half_episode_async_v1` 的段落只供旧RV恢复，不用于新RV发令。

当前全话准备启用 `episode_preparation_v1`、`panel_readiness_v1` 和 `comic_execution_v2`。按 [全话准备、逐格放行](panel-readiness.md) 审查准确范围；前格设计未定、真实实图依赖及高风险新状态继续等待。冻结共享脚本及五个Skill入口的真实哈希，所有阶段使用同一源稿、批准依据和逐格记录。旧RV不自动升级，不用各话临时复制的检查器。

## 一次准备完整话

先确定完整本话真实源序及范围，再核对原图、实际批准和各格衣装/场景。联系表用于定位，身份和空间关键细节须打开原图及实际选区。历史批准外链丢失记追溯限制；有适用原批准和原图时不自动判成未批准。本话必要缺项须在全话A/B前解决；其他作品缺项不扩大阻断。

episode_preparation_v1每话完成一次 `semantic_audit_v1`，绑定source_snapshot、根visual_basis、根shot_manifest及完整panel_ids，放在生产流程根semantic_audit。逐格记录REVIEWED、真实reviewer/evidence及六项具体核对；模板默认UNREVIEWED。旧half_scoped_v1的half_inputs[H001/H002].semantic_audit仅用于原RV恢复。

语义核对由执行者完成，随 A/B 现有审查包一起展示，不新增人工停点。原批准已覆盖完全相同基准与镜头时，技术核对报告可随原证明复用；报告本身仍须实际审查及版本核验。候选已保存、文件齐全和技术 PASS 均不表示已完成视觉核对。

```text
python <scripts>/execution_contract.py --state <本话/00_输入审计/生产流程.json> --batch EPISODE --write-semantic <本话/00_输入审计/全话语义核对.json>
python <scripts>/execution_contract.py --state <生产流程.json> --batch-preflight
```

全话语义报告保留完整源序并登记真实哈希；启用readiness时已核对范围可先交B，待补项维持真实未审状态和HOLD，不补写PASS。未启用时须完成全话语义核对再冻结A/B。随后在一个进程批量预检当前整话实际就绪格并复用未变QA，只提交完整generate门禁PASS的格。预检不生图、不授予批准。

## 源格号只做无损技术映射

源快照保留脚本原格号、原序、全部原文字段及脚本哈希；source_adapter.py 另建执行快照，例如 E023-P001→P001，id_mapping.pairs 保留准确一对一对应。原快照不覆盖。P001 本来就是源号时也登记恒等映射。原编号冲突或属于别话时 HOLD，不自动改号。

```text
python <scripts>/source_adapter.py --root <本话> --source-snapshot <本话/源快照.json> --episode E023 --write <本话/执行源快照.json>
```

生产 state.source_snapshot 指向派生快照；shot、单格 panel、进度和历史 attempt 同时记录 panel_id 与 source_panel_id。源全文仍在 locked_script，不能把显示编号替换当成改剧本。原批准只通过已验证的技术映射复用，原证明文件不改；同话 E023-P001 与 P001 可准确匹配范围，不能扩到其他话或其他格。最终交付清单列原格号与成品对应。

## 前格设计上下文与前格实图

单格包的 `continuity_context` 指向 `approved_shot_context_v1` 文件，准确绑定当前书话/格、真实 episode_order、sources 和 entries。source 登记原话 root、episode_id、源脚本/快照、批准基准/镜头文件及原 visual_approval/shot_approval；只放真实前序镜头。跨话来源须由总控放入 state.continuity_sources，原文件版本保持不可变。

```text
python <scripts>/continuity_context.py --state <生产流程.json> --panel P002 --write <本话/本格包/前格上下文.json>
```

构建器只引用原批准全话镜头，不复制图片、不生成前格输出。将真实path/sha256注册进单格执行包和镜头选集；跨半话/跨话前格仍使用批准设计上下文，真实实图依赖另行补齐。同场换机位不得写new_scene绕过。

`generation_dependencies` 和 `dependency_outputs` 继续只表示真正需要已验收前格图片的依赖；这种图片必须实际随调用携带。仅需前格设计核对的镜头不添加图片依赖，避免整话串行。

相邻关系由源序/真实上下文派生 adjacent_panel_pair。共同人物脸部是否可比较须逐人写 `adjacent_face_comparison[人物ID]={face_comparable:true/false,evidence:具体可见范围依据}`；可比较时派生 same_character_adjacent_expression。镜头、生图和实图验收用同一派生结果匹配记忆，漏手填标签不能规避规则。false 须有真实裁切/遮挡理由，不能用来跳过脸部检查。

## 多人忠实参考图集

每请求最多五条实际参考路径。先去重同一原图多用途；仍超限时制作 `faithful_atlas_v1` 技术图集，按真实裁区原尺寸粘贴批准人物/衣装，不重绘、不缩放、不改变原资产。多人图集不成为新的多人角色资产，也不产生新视觉批准；单人物状态板规则继续适用。

图集 reference_images 条目含 reference_kind=faithful_reference_atlas、derivation_policy、实际 path/sha256、subject_ids、逐人 subject_states、subject_asset_ids[人物ID][identity/costume_state]、reviewed/reviewer/evidence 和 source_regions。每个 region 含 subject_id、purpose、原 asset_id、source_version、source_file={path,sha256}、crop_rect_pixels=[x0,y0,x1,y1]、assembly_region=[x0,y0,x1,y1]。裁区按实际像素，归属不重叠；每个绑定用途都核验原批准资产、版本、状态与逐像素对应。登记源图文件时可引用包内已核对硬链接（同文件系统、仅只读使用），保留原路径/哈希，不批量复制资产。

图集须在B冻结前准备；shot.planned_identity_assets 登记同一图集别名/逐人物原资产映射及来源，shot.reference_bindings 与执行包保持一致，设计核验和最终编译均核对实际裁区。不能在B后随意换别名导致绑定失配。图集只承担 identity/costume_state；批准画风样例仍直接传入，不能把图集升为 style。人物脸/衣装不清楚、裁区不适用或目标细节被切掉时继续 HOLD。实际 prompt 明确每人对应区域及用途，重编 reference_usage_block、身份块和序号。只压缩文件数量，不降低必需参考信息；需要重绘的合并板仍走真实候选批准。

## 新状态首格校准修正

仅在 B 已批准 requires_state_review/calibration_anchor 的格或真实新状态屏障发生首轮 VISUAL_FAIL 时，允许创建单格 `state_calibration_round_v1` 候选；不要求尚未提交的整半话先有 QA。

```text
python <scripts>/calibration_repair.py --state <生产流程.json> --panel P001 --write <本话/06_图片验收/P001_校准报告.json>
```

实际审失败图并写 REVIEWED/reviewer/evidence 和 diagnosis：earliest_layer、requires_basis_change=false、repair_constraints={P001:[具体修正及保留约束]}。需要改批准基准时返回受影响 A/B，不能局部修图掩盖。

state.calibration_reviews[P001] 登记真实报告哈希。原首轮记录放 attempt_history，当前改 REPAIR_AUTHORIZED、round_id=2、新 attempt_id；新包 operation=repair，保留原镜头，calibration_repair={policy:state_calibration_repair_v1,panel_id,source_review_sha256,source_attempt_id}、repair_source_output 指向原失败图。原批准 bindings 完整保留，仅追加已核验失败图的动作/空间/构图用途；参考预算仍五条，画风/身份/衣装不得被失败图代替。

修正使用本半话唯一第二轮预算。第二轮 FAIL 或未知停止诊断，不能改称新校准重置轮次。首轮半话汇总保留原校准 FAIL；第二轮汇总引用实际校准 round2 及其他保留的 round1，约束与原校准诊断相同。高风险仍须原实图确认；普通 B 批准合并状态按 C/D 原策略处理。

## 通用记忆与本次例外

生产对规则库只读，当前话剧情/人物状态不入通用库。真实用户批准的规则例外另放本次生产证据，用 `scoped_rule_exception_v1`：rule_id、当前 rule_signature、stages、book_id、episode_ids、panel_ids、status=APPROVED、source_kind=user_message、source_locator、quote、evidence_root 和真实 artifacts；locked_script_sha256 使用 rule_exception.locked_hash(panel) 绑定准确原文。waived_checks[阶段] 明确替换的原规则检查，alternative_checks[阶段] 明确替代判据。

shot 与执行 panel.rule_exceptions 登记该文件 path/sha256。执行记录被替代项写 USER_EXCEPTION、原 exception 引用及具体依据；替代项逐项 PASS/evidence。验收模板仍为 UNREVIEWED。例外不改原文、不免身份/衣装/画风/空间/裁切和真实调用 QA、不扩大批准到其他格或作品。规则变版/源文变化重新核对适用性。

## 所有生图入口用同一记录与并发执行器

正文、资产候选和返修均用 async_generation.js 并注入真实 invoke/onResult。资产 job 使用 kind=asset、asset_id、job_id、attempt_id；正文/返修带 panel_id/batch_id/round_id。实际参数、输入文件哈希、提交/返回时间、原始返回和异常对象须保存。不要用 allSettled 后只保留“无图”，也不要打印完整图片 base64。

工具 FULFILLED 不代表有图；isError 返回、无结果、保存失败分别记录。错误 message、stack、code/status、真实 request_id、cause 与可序列化正文完整落盘，展示可摘要。解码/连接错误保守记结果未知；先核对真实输出/服务证据，不能直接重发。明确输入拒绝和确无图另记 CALL_FAILED，不能计成视觉失败。

连续三次观察到服务连接/解码错误，执行器停止当前派发器的新提交，已在途仍收尾，余格 NOT_DISPATCHED；默认不自动重试。多个话出现同源服务异常时总控暂停该服务新派发；独立健康入口按真实依据继续。这个阈值是服务熔断，和“超过五张视觉失败”分别记录。

## 冻结与恢复

每话执行者只写本话，总控只写shared control。全话准备使用一套source_script/source_snapshot/visual_basis/shot_manifest；启用readiness时先绑定含明确待补范围的真实版本，后续变更由总控核对许可及影响再绑定新版本；H001→H002只变当前活动批次和额度，不重冻资产镜头。真实修改共用基准时总控核对在途与历史许可，按parallel_dispatch合同更新精确冻结清单。

旧RV使用原冻结策略。启用新全话准备应在新RV核对在途/未知结果、保留原调用与成功图，建无损源号映射、全话语义核对、真实前格上下文与当前共享工具哈希，复用适用原批准并集中审新增差异。不能只添标记或补造QA。

读取扩展显式使用stage_baseline_loading_v1，索引新增load_policy，执行合同与QA格式保留。semantic_audit.rule_triggers须绑定准确matched_rules版本清单；启用人体规则且有可见角色时明确人体适用性及依据，APPLIES须有冻结标签。执行合同依旧核验共享工具真实哈希；旧RV不只添字段或改原哈希，使用新RV复核新增记录与适用依据。 归属与正式来源见 [rule-ownership.md](rule-ownership.md)。

读取来源在配置、state、镜头及执行包中一致绑定；阶段入口load-stage、逐格load共用当前agent/运行缓存。预读不扩展执行命中、批准或例外范围。旧来源不含loading_policy时只接受同样未升级的索引；读取策略/版本变化在新RV重新核验受影响规则签名、例外与批准依据。字段与命令见 [规则记忆](rule-memory.md)。

旧runtime的H001→H002只在C通过、全话包适用且旧半话无在途许可后更新本话active_batch_id与实际容量。当前整话模式仅用 `active_batch_id=EPISODE`，不增加frozen_halves，保留全话frozen_inputs版本与其他话状态。

启用readiness的上下文可用shot_approvals保留多份原范围B证明；shot_approval可为null，原证明不合成或扩张。加载时逐个来源格核对原消息范围与适用冻结设计。--candidate只读本话完全相同四项冻结来源；旧话及实际调用仍须真实批准。

## 本批运行版本

新配置的batch_snapshot_v1按[批次运行](batch-runtime.md)冻结五件套和实际规则正文；只校验实际执行快照，不因安装目录更新要求本批迁移。旧RV继续原toolchain合同。

新交接中的规则例外可用 `evidence_root_mode=exception_relative_v1`，`evidence_root` 为例外 JSON 所在目录内的相对目录（同目录填 `.`），`artifacts` 相对该目录。先完整保留原批准依据再创建候选，不修改已批准例外。移动后仍按原哈希核验；不允许 `..`、绝对路径或符号链接逃逸。旧绝对 evidence_root 保持原行为，不能宣称已可移植；包外迁移候选须重验。

所有新编译的正文、返修和资产job使用[统一提交登记](submission-runtime.md)，onBeforeInvoke必传；kind=asset不再跳过登记。旧冻结job缺协议时拒绝混用新版执行器，不补标志绕过。
