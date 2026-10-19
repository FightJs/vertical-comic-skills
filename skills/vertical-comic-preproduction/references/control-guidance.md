# 第一轮：生图能力、控制输入与实际执行

管理参考输入与控制链路，保留原脚本、批准取景、参考绑定和空间门禁。不调用生图、不训练模型、不承诺逐像素或人物细节一致。

## A：登记真实生图能力

新 B 索引声明 `control_policy: structural_guidance_v1`，根节点携带 `generation_backend`：

- `backend_id`：实际服务/工作流标识。
- `mode`：`text_only`、`reference_guided` 或 `structural_control`。未知能力保持 HOLD；普通上传选择参考路线，不能推断后台已执行 ControlNet。
- `evidence`：包内能力说明/工具接口快照的 `path`、`sha256`。记录实际可调用接口，通用论文或产品宣传不证明本次接口支持。
- `structural_controls`：无结构接口时为 `[]`；有时逐项登记 `type`（`pose/edges/depth/segmentation`）、`input_slot`、`control_model`（`id/revision`），另登记 `base_model`，核对模型兼容性。

无需为每格强行做控制图。选择参考路线仍可以制作和交付有效提示词包，控制执行状态必须为未使用；现有脚本/空间/资产 HOLD 不因选择路线而解除。

## D：审阅材料、干净构图参考和控制图分别交付

站位图与目标机位灰阶构图参考图在 D 阶段独立按需复用或生成，启用条件及样例见 [visual-continuity.md](visual-continuity.md)；现有空间证据充分可都不做。标注站位图用于空间讨论，使用时放 `supporting_documents`。Codex 选用构图参考时将核对过的干净摄影机视角图片放 `reference_images`，不用带文字/箭头的俯视站位图代替；NOT_REQUIRED 不留空槽，也不要求站位图作为替代。其核对合同见 [codex-imagegen.md](codex-imagegen.md)。其他后端按实际用途选择输入。上传普通参考图不自动成为结构控制。

只有真实结构接口需要时才另做 `control_inputs`：按本格批准摄影机、身体裁切和实际输出尺寸生成模型要求的纯姿态/边缘/深度等输入，不混入姓名、说明文字和审阅箭头。不要对带字平面站位卡估深度来冒充实际场景深度。来源错误不能靠提高强度修复。

每项控制记录：

- `control_id`、`type`、`path`、`sha256`。
- `source_kind`：`camera_view_render/pose_extraction/edge_extraction/depth_estimation/segmentation`；`source_camera_view_id` 必须对应本格 `camera_view_id`。
- `contains_annotations: false`、`view_check: PASS`、`view_review_evidence`（包内实际审查记录路径/哈希）。这些字段须来自真实审查，不得预填。
- `preprocessor`：`id/revision/parameters`；手工规范结构图也记录 `manual`、编码格式及参数。
- `control_model`：`id/revision`；`input_slot` 须匹配能力登记。
- `target_size: [宽, 高]`、`strength`。逐格 `generation_size`、控制图真实像素和批准 `frame_ratio` 应一致。

强度按后端/控制类型试验，不能全书套一个万能数值。姿态不负责人物身份，深度不负责服装，边缘不证明遮挡语义；继续使用原连续性合同和视觉验收。

## E：把计划和执行分开

每格必须显式包含 `control_inputs`，不使用时为 `[]`。新包可记录 `generation_execution: {"status": "NOT_RUN"}`，有效控制输入不等于已执行。

有服务请求 ID 的结构控制后端，生图完成后记录 `generation_execution.status: COMPLETED`、`request_id`、`request_evidence`、`response_evidence`；后两者都是包内 JSON 文件路径/哈希。Codex 普通参考分支使用实际工具参数和结果的可追溯证据、本地 `attempt_id`，不编造未暴露的服务请求 ID；还要核对真正送入的提示词和图片顺序。

结构控制后端的标准化请求记录至少含 `backend_id`、`panel_id`、`request_id`、`controls`。`controls` 逐项保留实际送出的 `control_id/path/sha256/type/input_slot/control_model/strength`，与索引完全一致。响应记录至少含同一 `request_id`、`status: COMPLETED`、非空 `outputs`（输出文件路径/哈希）。外部原始日志另行保留来源；不能根据待执行包补造调用记录。

```text
python <skill-dir>/scripts/check_control_inputs.py --package-root <B包目录> --phase preflight --report <新报告>
python <skill-dir>/scripts/check_control_inputs.py --package-root <B包目录> --phase execution --report <新报告>
```

`preflight` 核对计划与文件；`execution` 额外要求实际请求/响应证据。报告分别给出输入有效、未运行/有记录完成、结构控制是否有匹配执行记录；图片验收永远为 `NOT_ASSESSED`。它验证本地记录的一致性，不能认证供应商内部实际行为，也不能证明控制图语义或空间正确。

旧包缺策略且无控制声明时，预检返回 `LEGACY_NOT_ASSESSED`，执行核验返回 HOLD，不得改写成已通过新增门禁。存在控制声明却删除策略返回 HOLD。总前期校验自动调用此检查；旧包兼容不授予新增控制能力。

## Codex 分支

选择 `backend_id=codex_builtin_imagegen` 时必须为 `reference_guided`，根节点声明 `reference_input_policy=codex_reference_v1`，`structural_controls=[]` 且每格 `control_inputs=[]`。详细调用、构图字段与证据见 [codex-imagegen.md](codex-imagegen.md)。预检同时核对实际栅格参考、哈希、用途、构图核对记录和最终提示词。导出器只产生计划，执行核验不证明看图或供应商内部行为。

## 后续 F 的边界

这一轮未实现姿态/深度自动评分，也没有引入真实 ControlNet 执行后端。现有返回图验收继续逐格核对关键动作、遮挡、身份、裁切和画内文字。技术检查 PASS、记录完成和图像批准分别记录。

机制依据：[Diffusers ControlNet](https://huggingface.co/docs/diffusers/main/en/using-diffusers/controlnet)。控制一致性仍需验收，反馈闭环可参考 [ControlNet++](https://arxiv.org/abs/2404.07987)，该论文的训练算法并未通过增加本文件而实现。
