# Codex 内置生图：逐格参考包

> 阶段化五件套执行时，同时遵守 [固定流程](staged-workflow.md) 和 [生图输入输出合同](generation-io.md)。每次生成及返修必须实际传入批准画风样例，单独审查画风；最终交付逐格图片包，旧“进入排版/C阶段”只作历史术语，不启动排版。单格原编号快照由 staged_workflow.py 调用完整门禁校验，不能为通过旧完整话编号检查重编号。


## 生图执行规则：画风、模式与源序

实际调用前读取本书已确认人物板、已确认条漫样张和当前画风规则，并目视核对。把具体线稿、五官比例、发束、色彩与阴影方式写入实际 `prompt`，不能仅以“精细都市条漫”代替画风约束。用现有参考用途绑定说明画风证据来源，不虚构后端的风格权重或新增不支持的工具参数。

构图参考只决定其获准的构图/动作/空间信息；场景、道具参考不得把不同的渲染风格带入人物或整张画面。旧错误图只能提供明确获准保留的内容，不能作为画风依据。二维动漫项目须保持二维线稿和动漫上色，禁止漂移成真人、半写实CG或三维建模质感；其他项目沿用各自已确认风格，不统一强制动漫化。

返回图验收必须单独记录 `style_review`（`status`、实际对照样张路径、目视证据）。风格未审保持 `UNREVIEWED`，风格失败标 `IMAGE_STYLE_HOLD`，撤销该图的总体视觉PASS；身份、衣装、动作、背景、裁切五维通过不抵消风格失败。输入检查或执行成功也不证明画风一致。此项是额外人工验收约束，不宣称现有脚本已经自动验证画风。

从不可变源脚本建立顺序。新任务显式 half_episode_async_v1，按 [半话合同](half-episode.md) 与 [异步执行](async-generation.md) 同时提交当前半话就绪独立格，逐张自审、必要第二轮并发修正后全半话复验，第一半话C确认后第二半话。先发下一条指令，不逐张await结果后再提交。保留真实依赖和新状态屏障；等待可整理输入，不能越过C。旧batch5_v1读原五格合同，旧未声明任务仍单格首三格。每格/轮次/attempt与实际参考路径明确绑定，不用“最近图片”，实际返回必须落盘，未完成Promise持续等待收尾。

用户取消返修后停止继续调用。已经返回的候选保留证据，但取消不是对旧错误图或新候选的验收；后续恢复时不得擅自重启已取消返修。

仅在使用 Codex 内置 `image_gen.imagegen` 时读取。此分支交付参考包与调用计划；导出脚本不执行生图，不把输入校验或调用完成当作图像批准。

## 能力与入口

当前可用接口支持 `prompt`、`referenced_image_paths`、`num_last_images_to_include`、`transparent_background`。以本次会话实际工具定义和真实调用反馈为准，将接口快照/拒绝证据保存为能力证据；接口变化后重核，不从其他API套用参数。当前本地入口已实证最多5条referenced_image_paths，按 [参考预算](reference-budget.md) 合并同图用途并在调用前检查；不能因公开定义未列上限而继续超限提交。

本地交付包使用 `referenced_image_paths`，实际解析为绝对路径。不要同时使用 `num_last_images_to_include`。后者只用于会话图片且须符合当前工具要求，其上限不代表本地参考图片总数上限。编辑本地目标之前按工具要求看图；无法覆盖实际目标时补齐输入，不能用文件名或 `@别名` 代替图片。

此入口没有单独暴露遮罩、ControlNet、骨架/深度控制、参考权重、独立负向词或输出尺寸参数。目标比例与像素规格属于提示和验收条件，不是假定已执行的参数。`camera_execution_block` 表达批准取景要求，不能证明模型执行了硬约束。

新镜头表与 B 索引声明 `reference_input_policy: codex_reference_v1`。B 索引同时保留 `control_policy: structural_guidance_v1`，登记：

```json
{
  "backend_id": "codex_builtin_imagegen",
  "mode": "reference_guided",
  "structural_controls": [],
  "evidence": {"path": "审计/当前工具接口.json", "sha256": "实际文件哈希"}
}
```

每格 `control_inputs: []`。不可声明结构控制已执行；尚未生图保持 `generation_execution.status: NOT_RUN`。

## D：按需生成目标机位灰阶构图参考图

在 D 站位验证阶段决定新建、复用或无需额外构图参考，并在需要时于本阶段生成；B 镜头设计阶段只记录机位、裁切和待核对问题。站位图与灰阶构图稿分别选做，触发条件和样式图片统一见 [visual-continuity.md](visual-continuity.md)。每格先使用足够的批准资料，再复用匹配机位与裁切的已核对图片，最后才补做；不按格数强制新增，也不因室内、多人或换机位直接要求图片。已有正式批准画面足够时可直接复用，无需为灰阶形式再做一遍。

多人遮挡、复杂接触或显著换机位，且现有资料仍无法表达目标、确实需要构图参考时，登记 `composition_required: true`；缺图或未核对保持 HOLD。无需额外构图时写明已有批准依据如何覆盖本格，缺少选做图本身不造成 HOLD；没有图片也必须保留逐格空间、遮挡、接触和裁切核对。真实空间关系未知时继续 HOLD，不借 NOT_REQUIRED 放行。

新建构图图统一称“目标机位灰阶构图参考图”，按目标比例展示最终摄影机看到的画面：身体裁切、朝向、动作接触点、背景透视和前后遮挡。可用灰阶绘图、简化无五官人物或有空间依据的简易几何场景导出，以看清关系为限，不要求最终画风、细致发丝和材质完成度。五官留空时，表情与视线仍按已批准逐格记录核对，空白脸不能证明视线正确。干净版本没有生产标注、箭头或文字；剧情中的必需画内文字另按脚本处理。俯视站位图与标注版放审阅资料。文字截图、圆圈站位图或未经核对的旧可见卡不能冒充新参考。

在现有逐格记录中增加：

```json
{
  "composition_reference": {
    "mode": "REUSE",
    "reason": "现有构图匹配本格批准机位、裁切和接触关系",
    "alias": "@COMP_P012",
    "review_evidence": {"path": "P012/审阅/构图核对.json", "sha256": "实际文件哈希"}
  },
  "ratio_tolerance": 0,
  "transparent_background": false
}
```

`mode` 为 `CREATE/REUSE/NOT_REQUIRED`，在 D 完成选择并写回现有镜头记录；前两者在 B 交付时都必须有真实图片与核对证据。`NOT_REQUIRED` 表示无需额外图片，不填图片别名或审阅文件、不留空图片槽，不能豁免已登记必须提供构图的格。站位图是否制作在已有站位记录中说明，不添加第二套构图合同。`ratio_tolerance` 是返回图相对比例误差容差，0 表示精确比例，按实际交付规格确定，不一律沿用旧 5%。

核对 JSON 含本格原有 `panel_id/camera_view_id/camera_view_signature/framing/frame_ratio` 的准确值，以及 `status: REVIEWED`、`reviewer`、具体 `evidence`、`reference_sha256` 和 `clean_camera_view: true`。这是核对记录；文件一致性不证明看图、空间正确或用户批准。新机位仍按既有批准规则处理，原空间 HOLD 不因填字段而解除。

构图图在 `reference_images` 中注册一次路径/版本/哈希，用 `reference_bindings` 绑定本格 `framing`，需要时同图再绑定 `spatial_layout` 或可见人物的 `pose_interaction`。不新建第二套图片清单。核对 JSON 保持包内相对路径，实际参考复制到 B 包后同步核对文件。

## E：四类参考与真实调用

按需要组织 `reference_images`；数组顺序就是实际输入顺序：

1. D 阶段选用的干净摄影机视角构图图（可选）：位置、动作、裁切、接触和遮挡。
2. 批准的方向场景独立视图：门窗、家具、材质和世界光向。
3. 每位可见角色的批准参考：身份及当前衣装；明确角色归属。只露局部时按实际可见信息选择参考。
4. 必需细节：手势、道具、固定标记；缺需求不补图。

四类不是固定四张。一张角色图可同时提供身份、当前衣装及其已批准画风；同图只登记一个路径/别名，多条用途绑定保留，实际路径总数不得超过5。优先独立场景视图，资产联系图留作选图审阅。确需压缩不同必需来源时按参考预算准备适用候选，不截断原输入。参考板的全身或宽景不得扩大本格裁切。

使用 `reference_usage_block(bindings, references)` 按实际顺序编译职责，例如“参考图1 @COMP_P012：构图；仅迁移构图和裁切；不迁移人物身份和衣装”。无五官构图图仍可能带有发型、衣服和体型，不作为正式身份/衣装来源；动作/接触另绑定 pose_interaction、布局/遮挡另绑定 spatial_layout，不扩展 framing 的允许字段。同一图可出现多个用途条目，序号保持相同；NOT_REQUIRED 不生成构图用途条目，后续参考从实际数组第一张正常编号。身份、衣装、场景和动作绑定沿用 [reference-continuity.md](reference-continuity.md)，不新增混合用途枚举。

最终 `prompt.txt` 包含机位、画面内容、参考用途、身份状态及本格必要避免事项。`negative_prompt.txt` 可保留兼容资料，Codex 调用只接收已合并的 `prompt`。manifest 与逐格 JSON 的 `prompt` 必须与实际文件一致。

```text
python <skill-dir>/scripts/check_control_inputs.py --package-root <B包> --phase preflight
python <skill-dir>/scripts/codex_reference_contract.py --package-root <B包> --output <新的调用计划.json>
```

导出器核对文件后输出 `tool/arguments/reference_order/reference_files`，其中 `arguments` 只有当前本地路线的 `prompt/referenced_image_paths/transparent_background`；`reference_files` 保存别名、包内路径和输入哈希，不作为工具参数。导出结果仍是计划；移走包或更改文件后重新导出核对。正式生图仍须通过完整身份、剧本、空间与包门禁。

## 实际执行证据与 F

实际执行后才登记 `generation_execution: {status: COMPLETED, attempt_id, request_evidence, response_evidence}`。`attempt_id` 是本地关联编号，不能称为服务端请求 ID；真实服务端 ID 若可见，可额外保留。

请求证据保存实际观察到的 `backend_id/panel_id/attempt_id/tool/arguments/reference_order/reference_files`，其中输入文件哈希必须在调用时冻结，不能事后用当前文件补写。登记 `source_kind: observed_tool_call` 和真实 `source_locator`（会话、调用或可追溯记录）。响应证据保存同一 `attempt_id`、`status: COMPLETED`、非空 `outputs`（包内图片路径/实际哈希），以及 `source_kind: observed_tool_result` 和真实来源。不得把调用计划补写成已执行日志。本地脚本只能验证记录与文件一致，不能认证模型后台行为或来源真实性。

修复器重建提示词或图片路径后，将旧执行记录移至历史审计并恢复 NOT_RUN；已使用的构图核对与能力证据原样复制，失效或缺失继续 HOLD，不自动生成批准记录。NOT_REQUIRED 无需补造构图图片和核对证据。

返回图逐格核对身份、衣装、手/道具接触、遮挡、背景投影、裁切及实际像素比例。CREATE/REUSE 与已核对构图并排对照；NOT_REQUIRED 依据批准镜头、空间记录与相关资产审查，仅额外的构图图片对照标 NOT_APPLICABLE，framing 等必审维度保持 UNREVIEWED 直至实际看图。`make_generation_qa.py` 按需生成构图对照图，并保留比例误差及五维未审记录。另完成画风检查；半话模式额外记录轮次与全半话连续性、第一半话C；旧batch5_v1仍首五格，旧单格模式仍首三格。参考输入有效、调用记录完成和图像验收分别报告，未审或失败不能进入排版。
