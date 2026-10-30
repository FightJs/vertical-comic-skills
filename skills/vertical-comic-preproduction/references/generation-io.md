# 生图输入输出与成品合同

接包用途优先按[免外部配置接包](quick-start.md#接包生产免外部配置)路由：只提供正式包路径及可选输出位置，书话/脚本依据/必要资产从包内读取，不进入首次前期配置、prepare或主表重建。历史usage_config_path只作来源记录；接收与生产不重新加载前期电脑配置。环境、有效生产授权、真实依赖及包内审核合同仍适用。

当前新任务按 [整话异步生产](episode-async.md) 冻结资产、镜头、比例、语义核对和全话生图包，已就绪格跨全话持续提交，没有固定半话C。下文H001/H002与C只适用于旧RV；真实参考、逐图六项QA、规则、依赖与轮次要求继续执行。

批次模式遵守 [按话并行与五格批次](execution-compatibility.md)。批次只改变调度和复核时点，每格仍使用下面完整输入、独立调用及输出证据。

## 每格输入

新模式全话生图包在B阶段构建并提交用户确认；整话范围内的已批准独立格持续提交。公共输入准备时核验，实际提交只核本格版本、真实依赖与动态调用身份；旧RV保留原批准范围后导入当前执行器。

| 项目 | 来源与固定要求 |
|---|---|
| 格身份与原文 | 源话号/格号、源版本、locked_script；保留全部原文和格序 |
| 镜头 | 批准的 camera/framing：焦点、裁切、比例、位置、可见面、遮挡和必显信息 |
| 人物及状态 | 原 character_bindings/scene_binding/continuity_contract；当前服装先选定 |
| 实际参考 | reference_images 的路径/版本/哈希/归属；reference_bindings 指定用途与允许迁移内容 |
| 画风 | approved_style_v1，实际批准样例、批准证据和具体风格特征 |
| 规格 | frame_ratio、ratio_tolerance、输出用途，以及明确的最小或精确像素要求；数值由项目/用户规格确定，不猜测 |
| 操作 | 首次/返修、尝试 ID、修改目标、保留内容；实际支持的工具能力 |
| 执行文本 | camera_execution_block、content_execution_block、reference_usage_block、style_execution_block 合成一个最终 prompt |

新建包另声明 `input_priority_policy: physical_scene_priority_v1`；每格实际 prompt 包含物理与固定场景约束。人物、衣装、表情、动作目标和结果及批准画风同为硬要求；机位、景别与裁切只在满足这些依据时调整。有获批冲突处理才携带 `visual_resolution`；无冲突的格不增加记录或审查停点。参考图职责、冲突判断和 HOLD 处理见 [共同约束](production-foundation.md)。

多人接触或递接若容易反转主动者，B镜头的 `production_risks.action_target` 写清主动人物、使用的手/臂、接触对象与部位、从肩肘到接触点的可见路径，以及不得出现的反向动作；分别核对每个人的动作，不把同一句双人动作复制成两人的独立姿势。裁切用于避免多余肢体/物体时，应区分“必须保留的动作或空间信息”和“期望的取景边界”：用户明确接受更宽裁切后，先更新本格批准范围与验收判据，再重验现图，不为低优先级取景单独消耗返修调用。动作主体、接触关系和必显信息仍须通过。

固定类别不等于固定图数。按本格需要选择干净构图（可选）、方向场景、可见人物身份/当前衣装、必需细节、批准画风样例。每类职责写进实际 prompt，并按真实数组序号编号；同图多用途可复用一个输入。多状态人物板明确当前状态，局部参考保留忠实来源，不脑补低清细节。上一格只可提供已核对的连续性信息，不能逐格替代原始身份/画风依据。

Codex本地参考入口目前已实证每次最多5条路径。编译时同一文件只注册一个别名，身份/服装/画风用多条绑定；超过5个不同必需来源先处理参考预算HOLD，不截断实际数组或删必需依据。细节与历史审计/当前新请求区分见 [reference-budget.md](reference-budget.md)。本限制与整话实际在途并发数无关。

## 画风可执行合同

manifest 和每格声明 `style_policy: approved_style_v1`。每格 `style_contract`：

```json
{
  "book_id": "本书真实ID",
  "reference_aliases": ["@STYLE_APPROVED"],
  "traits": {
    "linework": "根据实际样例填写线稿特征",
    "face_proportions": "根据实际样例填写五官比例",
    "hair": "根据实际样例填写发束画法",
    "coloring": "根据实际样例填写上色特征",
    "shading": "根据实际样例填写阴影方式"
  }
}
```

这是字段示例，不可把示例文字当作真实特征。每个别名必须在实际 reference_images，reference_kind 为 approved_comic_sample 或 approved_character_board，并有 style 用途绑定。正常优先携带批准条漫样例并结合人物板；无批准条漫样例时先让用户明确批准人物板作为当前试产风格依据，不擅自降级。

每个风格引用增加包内 `approval_evidence` 文件引用。该 JSON 含 status=APPROVED、source_kind=user_message、source_locator、quote、book_id、approved_sha256（被批准原图/明确批准的派生引用哈希数组）。真实批准范围不匹配则 HOLD。来源、文件哈希和批准记录不能证明模型一定遵循风格。

调用 `style_contract.style_block(style_contract)` 编译 `style_execution_block` 并写入实际 prompt。traits 中不重复资产理论，只写本书可观察的特征。二维样例不允许漂移为真人/半写实 CG；其他书按其实际批准风格，不统一套动漫要求。

内置入口实际使用 prompt、referenced_image_paths、transparent_background。工具当前定义优先；不假设有 seed、参考权重、ControlNet、独立负向或硬尺寸参数。输出比例和像素要求需要验收。并行执行须使用明确本地 referenced_image_paths，不使用 num_last_images_to_include 或“最近图片”，避免跨任务参考混淆。风格文件必须真实传入，不能只在提示词中提名字；修图也持续带原始批准样例和适用人物/衣装依据，旧错误图不能成为风格来源。

## 返修输入冲突预检

返修携带失败图（`@REPAIR_TARGET` 或 `role=repair_target/edit_target/failed_image`）时，单格包增加 `repair_focus.failed_transfers`，从本次真实视觉失败中列需要纠正的具体要素，如 `crop`、`composition`、`pose`、`contact`、`gaze`。若用户调整了低优先级裁切的批准范围，先更新批准/QA，再确定实际仍失败的要素。失败图绑定不得允许迁移这些要素，且须在 `forbidden_transfer` 明确列出；只允许迁移实际未出错且有用的部分。失败图是编辑底图，不是错误姿势或裁切的权威。若无可安全继承的构图用途，不为保留失败图而虚构 `framing` 绑定；改用适用批准参考与干净站位依据，必要时走相应资产/镜头阶段。

当 `failed_transfers` 含 `contact`，`repair_focus.action_contact` 逐项填 `actor`、`target`、`actor_limb`、`target_part`、`visible_path`、`forbidden_reverse`，六项原文须进入最终绘图 prompt。以“桑榆主动挽温霜”为例，写明桑榆提袋之外的空臂如何弯起搭绕温霜靠近她的前臂，温霜不得反抓桑榆袖子；左右手以实际批准站位和道具占手情况确定，不猜。`repair_focus` 是执行层诊断，不改源剧本或已批准身份衣装。

每次从当前批准镜头、实际参考及本次修正目标编译一个最终 prompt。轮次、预算、待批准/禁止调用等流程状态仅留审计记录，不进入绘图文本。旧RV已冻结的历史包不强行补字段；新的人工补救在提交前运行 `scripts/repair_input_guard.py --packet <单格包或逐格JSON> --prompt-file <实际最终prompt.txt>`，必须核对实际文本与逐格JSON完全一致并补 `repair_focus`；当前新模式 `repair-authorize` 和完整调用前预检强制执行检查。预检只发现输入矛盾和缺项，不能替代返图后的实际手势/构图观察。

## 调用、快照与输出

按话并行每个 episode 仅一个写入者，独立输出根目录；总控只写调度记录，不与工作 agent 同时写本话状态。批内请求可返回乱序，输出按源格 ID 归档。批次模式的实图依赖以执行包根 dependency_outputs 冻结，并实际传入 reference_images；并行请求另冻结 dispatch_receipt，验收对应当前 epoch 的 COMPLETED 许可及实际输出哈希；换 worker/epoch 后复用旧合格图须按批次合同附带真实 carry_forward 报告，原回执保持不变。精确合同见 [批次文档](execution-compatibility.md)。每格每次尝试固定保存：最终 prompt、reference_images 清单与输入哈希、NOT_RUN 调用计划、实际请求证据、实际返回证据、候选图片、真实尺寸/格式/哈希、单格 QA，以及必要的返修关联。计划不能补写成调用完成日志，真实无图结果不造图片路径。实际证据规则沿用 codex-imagegen.md。

调用前运行阶段门禁与输入导出；batch5_v1 对每个请求分别检查，取得当前调度额度后才能提交。正式调用后登记真实 execution，再生成 QA；无依赖候选可汇总返回后逐张检查；同批依赖前置图一返回就先完成六项 QA，通过后才能提交依赖它的后格。整批返回并通过逐张及批次连续性检查后才进入下一批：

```text
python <总控>/scripts/staged_workflow.py --state <流程文件> --check generate --panel P001
python <总控>/scripts/codex_reference_contract.py --package-root <当前单格包> --output <新的调用计划.json>
python <总控>/scripts/check_control_inputs.py --package-root <当前单格包> --phase execution
python <总控>/scripts/make_generation_qa.py --package <当前单格包> --images <本次返回图目录> --output <新QA目录>
python <总控>/scripts/continuity_contract.py --manifest <当前单格包>/全话提示词索引.json --qa-report <新QA目录>/生成图QA报告.json
```

图片目录只放本次版本，以 `Pxxx.png/jpg` 或 `Pxxx/唯一图片` 供 QA 工具识别，不能让脚本从多版候选中按文件名选中错误版本。原始候选文件保留源话/格和 RV/尝试号。不得通过重命名源格绕过顺序检查。

原五维验收继续使用 dimension_review；另增加 style_review（未审默认 UNREVIEWED、固定参考文件及特征、reviewer、具体 evidence）。QA 工具自动生成风格样例/返回图对照，但不填 PASS。首次入画/换装/换景重点核对；普通格仍检查所有必审维度。必显内容不能事后改为 NOT_VISIBLE；失败时标对应 IMAGE_*_HOLD。

输出规格使用每格 `output_spec`：`formats`（如 PNG/JPEG，按批准交付选择）、`min_width`、`min_height`，如有精确尺寸加 `exact_size: [宽,高]`，无精确要求则 null。QA 检查实际尺寸/格式并记录 output_spec_check；规格未确定时 HOLD。图片比例沿用 frame_ratio/ratio_tolerance；不静默拉伸、裁掉必需内容或以降质转码凑规格。

若工具实际返回尺寸不足，先独立完成视觉验收。视觉通过且已有批准的等比插值方案时，按实际像素等比放大到同时满足宽、高下限及比例容差，保留原图和派生图哈希并重新跑输出规格QA；视觉失败图不能靠插值放行，也不因原生像素不足而重复生图。工具未提供硬尺寸参数时，提示词写了最小像素不等于服务承诺。

## 成品包

```text
E021_逐格成品包_RV_v001/
  01_成品图片/E021-P001.png ...
  02_审阅总览/按顺序排列的联系表
  03_图片索引/逐格成品索引.json
  04_验收记录/最终确认及必要差异说明
```

索引列出 book_id、episode_id、源 panel_id、包内相对路径、实际尺寸/格式/sha256、来源尝试和用户批准证据。图片数量/格序与源快照完全一致，只有当前明确接受版本，不混入旧候选和失败图；复制后复核哈希。自然保留批准比例，不统一强裁成同一尺寸。联系表仅用于检查，不是长条漫画成品。

交付前运行 staged_workflow.py --check deliver，并实际核对整个成品目录与索引。同一并行 control.jobs 超过一话时，还须完成绑定全部话当前图片及 QA 的 cross_episode_review；其合同见 [批次文档](execution-compatibility.md)。跨话报告和各话 D 批准都有效才可交付，报告不自动写 PASS。无用户最终确认只能称待审包，不能标成品已验收。图片不含后加气泡、对白/旁白和后期 SFX 字；保留剧情规定的招牌、屏幕等画内文字。不调用 finishing Skill。

## 规则记忆与可配置批次补充

第三来源与按阶段命中读取见 [规则记忆合同](rule-memory.md)，路径、子 agent 数和请求额度见 [使用配置](usage-configuration.md)。启用记忆的新任务在生产流程、批准镜头、冻结执行包绑定一致 memory_source；镜头 memory_tags 冻结传递，生成与图片验收分别留执行记录，不能删除来源绕过。实际人体在床上等命中条件要求适用站位图及实际提示词约束，未核对则 MEMORY_HOLD。

仅旧batch5_v1使用batch_size默认5，可配置1–5；文内“五格批次”指最多五格，批次计划 max_batch_size 取实际配置。首五格 C 范围保持不变；独立图片质量、依赖、新状态、批内/跨批及跨话检查不因调小批次或增减 agent 而省略。修改配置不会自动覆盖已有 RV 的冻结状态。

v2技术来源包括源格映射、上下文、忠实图集、校准第二轮与完整调用异常记录；当前整话执行也不更改批准源稿或输出规格。详细字段、命令和恢复规则见 [生产兼容与提速](execution-compatibility.md)。

当前新任务的画幅计划是固定输入：frame_ratio_policy/frame_ratio_plan/source_snapshot绑定本话根文件；每格ratio/reason与计划一致，比例执行块进入实际prompt及逐格JSON。每次生成和返修都保留批准画幅。QA命令传--episode-root，D验实际全话统计。 详见 [全话画幅计划](frame-ratio-plan.md)。

新RV增加visual_evidence_v1的冻结具体判据、派生上下文、visual_execution_block和返修repair_source；字段、实际编译、审阅局部及底图选择见 [具体视觉证据](visual-evidence.md)。技术PASS不能证明图像正确，实际原图/局部/连续性仍需看图。


新背景策略按[背景模式](background-treatment.md)实际编译；场景参考提供色调/光向/必要空间，保留本机位可见场景结构，不要求复现全套陈设，禁止纯色空背景。实际prompt及逐格JSON保持唯一一致，返修同样检查当前背景段和保留特征，最多五条参考不变。


新策略真实输入与返修分流见[实际执行质量与返修分流](execution-quality.md)。复用现有记录和人工停点，不静默升级旧RV。

## 定向肢体修复与正确区域保留

改手臂/持物姿态时使用repair_focus.structural_change={remove,replace,connect}，三个具体描述进入真实prompt并经repair_input_guard核对；它不代表工具已经执行蒙版或像素锁定。局部修复的可选preservation_regions及真实底图边界、返图比较见execution-quality.md。仅裁切继续零调用候选；空间/归属错误先修依据，不以局部手指修复掩盖。


新整话实际输入必须符合[服饰与单画面](appearance-and-single-frame.md)：每个panel携appearance_policy、frame_policy及frame_plan；当前入画衣装核心与可见细节实际随参考携带并编译进visual_execution_block。原源文保留，但双画面源只绘制已选一幅，不把忽略场面再次拼进prompt。身份/画风等原块不得被新约束块覆盖。

新任务最终交付必须执行[完整交付与容量门禁](delivery-contract.md)：前期交接单ZIP优先、超限自动连续分卷，每文件不超过900000000字节；成品ZIP无容量上限、不因体积自动分包，并必须包含图片问题总览.csv及问题明细.csv。前期内容release之后走publish，成品目录export之后走普通ZIP发布；统一交付验收.json通过后才能finish-check/100%。容量失败只修装配与容器，不重新生图或降质；旧冻结运行不热升级。

## 正式返回持久化

宿主将真实返回直接以文件或字节流保存，不把base64插入shell命令。使用`generation_host.py save-return --state <原状态> --job <原单job文件> --raw-result <真实返回JSON> --call-locator <实际调用定位> --result-locator <实际返回定位>`。该命令不调用图像服务，使用原冻结GENERATED转换，原始返回先保存，图片和证据原子落盘；视觉状态仍为未审。

image_return_io.py优先读取结构化本地artifact或data URL，hint解析兜底；多图要求明确`--selected-index`，HTTP-only准确报告没有可保存字节，不扫描“最近图片”猜结果。data URL与单一本地文件同时存在时比较完整字节摘要，长度及首尾不算完整证明。原JSON字节、原图及摘要保留，重复保存仅复用相同结果。

保存、QA或状态CAS失败时恢复同一返回，不重发生图。UNKNOWN需原协议查证，不能自行回退PENDING。迟到返回照常保留，但不冒充按时完成。规则地址问题通过本地执行副本解决；QA与交付绑定其实际SHA256，已批准输入原件保持原字节。
