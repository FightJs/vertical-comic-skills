# 参考用途、连续性合同与分项验收（第一轮）

本轮借鉴 CharaConsist（arXiv:2507.11533）的身份/动作/背景分离，以及 RaCig（arXiv:2506.12517）的姿态检索和角色区域分配。落地的是工作流约束，未接入论文的训练、注意力、特征缓存或 ControlNet 实现。原 CharaConsist 的已有身份图输入有限制；RaCig 的角色分配实现描述以两人为上限。这里的三人以上文字绑定不代表已获得相应模型控制能力。

## 在什么阶段使用

| 阶段 | 本轮动作 | 使用边界 |
|---|---|---|
| A 输入审计 | 登记角色身份/衣装状态、跨格空间关系、现有参考用途及一次出镜豁免 | 不补写事件；未知来源保留原 HOLD |
| B 镜头候选 | 在已有逐格 JSON 建立 `continuity_contract`，确定必显信息和允许变化 | 普通对话按原取景即可，不强制检索姿态图 |
| C 资产 | 将需要的参考分配用途，可让同一资产兼任身份和服装 | 优先复用；无需为字段新做一套资产板 |
| D 站位验证 | 核对位置/朝向、接触、遮挡与裁切；需要时复用或生成站位图、目标机位灰阶构图参考图；绑定实际可见角色与区域 | 两种图独立选做，已有证据够用则不补；画外角色留在记录，不加入 B 正文 |
| E B 包 | 完整复制批准合同与绑定，编译用途块进入逐格实际正文 | 只有真实图像/区域/骨架控制工具才能宣称执行相应控制 |
| F 返回图 | 分开记录身份、服装、动作互动、背景空间、构图验收 | 文件/字段 PASS 不能替代视觉审查或批准 |

拥抱、搀扶、递接物件等复杂互动可使用 `pose_interaction`，前提是姿态与本格动作、接触、裁切相容。参考姿态若让手机出画、换手或改变动作结果，放弃该参考。普通对话、单人反应或已有充分动作/接触依据时，不需要额外姿态图。不要把“缺姿态图”作为所有面板的 HOLD；真正缺失不可替代的身份、空间或接触依据时沿用既有 HOLD。

## 记录位置与迁移

新建镜头表和提示词索引的根节点声明 `continuity_policy: "reference_continuity_v1"`。每格增加 `reference_bindings`、`continuity_contract`；不创建第二套独立连续性台账。镜头表是批准依据，B manifest 和逐格 JSON 是其执行副本，内容必须一致。不要事后只改 B 合同来迁就生成错误。

旧包没有该声明时，新校验会明确报“未执行新门禁”。保留旧包；在新 RV 中依照真实脚本、资产和批准镜头补齐，再同时声明两份 manifest 的策略。不能从缺失值猜测状态、伪填批准或用移除策略绕过已启用门禁。旧修复工具不自动迁移这个扩展；修复后重新核对合同、正文用途块和新门禁。

### 参考绑定

`reference_images` 继续保存实际文件、`role`、版本、SHA256、来源和既有批准依据。身份/服装资产另登记 `subject_ids` 表示这张图属于谁，并按真实资产登记 `subject_states: {"CH-A":{"identity":"CH-A:v001","costume":"CH-A:常服v001"}}`。用途涉及的状态必须与本格合同一致，不能在换装后仍绑定旧衣装参考。允许同一别名有不同用途绑定，也允许组合板包含多个已明确归属的角色。不要仅依赖图片排列顺序判定人物归属。

每条 `reference_bindings` 使用：

```json
{
  "alias": "@甲定版",
  "purpose": "identity",
  "subject_ids": ["CH-A"],
  "allowed_transfer": ["face", "hair", "fixed_marks"],
  "forbidden_transfer": ["pose", "clothing", "background", "crop"]
}
```

| purpose | 可迁移的字段编码 | 绑定对象 | 不能顺带迁移的例子 |
|---|---|---|---|
| identity | face、hair、fixed_marks、body_proportions | 可见角色 ID | 板上姿态、服装状态、全身裁切 |
| costume_state | clothing、accessories、injury_state | 可见角色 ID | 板上人物脸、动作、机位 |
| pose_interaction | pose、contact、gaze | 一个或多个可见角色 ID | 检索图的人脸、服装、背景、裁切 |
| scene_view | geometry、materials、lighting | 当前 scene_id | 板上人物、板上完整宽景构图 |
| framing | composition、crop | 本格 panel_id | 图中人物身份、衣装、场景几何 |
| spatial_layout | screen_region、depth、occlusion | 本格 panel_id | 示意符号的人脸、服装和画风 |
| prop_state | prop_shape、prop_state | 相关道具 ID | 持物人的脸、动作或完整背景 |
| style | linework、palette、shading | 本格 panel_id | 示例图的剧情、身份和空间 |

前五项对应本轮优化重点；后三项承接已有空间布局、道具和风格参考。每张实际 B 参考都要有用途；不为凑角色参考而新增人物。`allowed_transfer` 只能取该用途对应字段；`forbidden_transfer` 写明本格最易混入的内容且不能与允许项冲突。角色的 `screen_region` 在合同里登记，实际动作/遮挡以已有 `characters_visible`、批准空间记录及实际选用的已核对构图参考为依据；构图参考可以不使用。灰阶无五官图中的发型、衣装和体型也不能自动作为身份来源，framing 不顺带迁移动作或场景几何；需要时另绑定相应用途。文本绑定不会自动生成区域 mask。两种辅助图的启用条件与样例见 [visual-continuity.md](visual-continuity.md)。

### 连续性合同

```json
{
  "scene": {
    "scene_id": "SC-01",
    "mode": "new_scene",
    "previous_panel_id": null,
    "basis": "批准SC-01空间底账及本格镜头"
  },
  "subjects": {
    "CH-A": {
      "identity_state": "CH-A:v001",
      "costume_state": "CH-A:常服v001",
      "screen_region": "画面左，中景，胸部以上",
      "identity_visible": true,
      "costume_visible": true
    }
  },
  "invariants": {
    "CH-A.identity": "CH-A:v001",
    "CH-A.costume": "CH-A:常服v001",
    "SC-01.background_space": "SC-01批准空间底账v001"
  },
  "allowed_changes": {"CH-A.pose": "本格locked_script.event_text已有动作"},
  "required_visible": ["逐项复制本格批准framing.required_visible"],
  "offscreen_entities": ["CH-B"],
  "qa_requirements": {
    "identity": {"applicability": "REQUIRED", "subject_ids": ["CH-A"], "criterion": "甲的可见脸、发型、固定标记与定版一致"},
    "costume": {"applicability": "REQUIRED", "subject_ids": ["CH-A"], "criterion": "本格可见衣领和上衣与常服状态一致"},
    "action_interaction": {"applicability": "REQUIRED", "subject_ids": ["CH-A"], "criterion": "本格已有动作、表情和视线按批准方案呈现"},
    "background_space": {"applicability": "REQUIRED", "subject_ids": ["SC-01"], "criterion": "可见窗与桌沿符合批准空间及本格投影"},
    "framing": {"applicability": "REQUIRED", "subject_ids": ["P001"], "criterion": "批准焦点、胸部以上裁切、画幅及全部必显信息入画，不补画外角色"}
  }
}
```

示例只解释字段，不是可直接宣称已批准的素材。`subjects` 与本格 `characters_visible` 的唯一角色 ID 完全对应（人物对象使用 `character_id/subject_id/id/asset_id`）。身份/衣装状态使用真实资产/连续性版本 ID；一次出镜对象可以依据输入审计的出镜统计和源脚本描述记录 `asset_exemption: {"status":"ONE_OFF_ASSET_EXEMPT", "appearance_count":1, "basis":"实际统计与描述出处"}`，不强制独立资产。

`invariants` 使用 `对象ID.属性` → 锁定状态/依据；`allowed_changes` 使用同类键 → 本格已存在的脚本变化依据。同一属性不能同时固定和允许变化。重现角色即使跨场景，身份/服装版本改变也必须有对应 `角色ID.identity/costume` 变化依据。正常动作、表情、视线改变可以只登记实际变化；不能由“固定身份”推导成冻结姿态。服装状态变化只释放该状态，不能顺带改脸。

四种场景模式：

- `same_scene_same_view`：指向前序格；核对同一视图的可见锚点和投影，人物动作可以改变。
- `same_scene_new_view`：指向同场景前序格且 camera_view_id 不同；允许构图、遮挡、背景投影变化，核对几何与物体位置，不要求像素复制。
- `new_scene`：首格或切至另一 scene_id；使用当前场景依据，不拿上一场景的窗/家具做相似度要求。
- `scene_state_change`：指向同场景前序格；在 `场景ID.background_space` 登记脚本支持的明确变化，保留未改变的锚点。

`required_visible` 必须与批准 `framing.required_visible` 完全一致。不得删去必要的手机、接触点、画内文字或同时反应。必要道具可按 `PROP-PHONE：手机与双方手指接触点` 登记，便于明确实体冲突；沿用旧纯文本时仍须人工核对，校验器不假称理解所有文字与物体关系。`offscreen_entities` 只登记画外实体 ID，不能与可见角色/已标明ID的必显实体重叠，也不能送入需要画出的正面内容块。

## 编译与验收

Phase E 用 `scripts/continuity_contract.py` 的 `reference_usage_block(bindings)` 编译用途块；Codex 分支传入第二参数 `reference_images`，按实际输入顺序加图片编号，存入同名字段并逐字写进实际 `prompt.txt` 的内容块之后。先用 `validate_manifest(shot_manifest, prompt=False)` 检查候选字段，再核实/复制参考、编译已完整的绑定，最后运行全包门禁；不要把未经核实的合同整体倾倒进正文。既有复制/哈希、实际 prompt 与 manifest 一致性检查继续适用。

Phase F 的五个维度都在生图前选定 `REQUIRED/NOT_VISIBLE/NOT_APPLICABLE` 及具体判据。只露手时，不可见脸部/衣装维度可标 `NOT_VISIBLE`；完全无人时用 `NOT_APPLICABLE`。可见头发仍有身份信息，不能仅因背面看不到脸就豁免身份。背景只有在批准裁切完全无空间信息时可不验；必要锚点仍须验收。构图总是 `REQUIRED`，即使 composition_reference 为 NOT_REQUIRED 也须依据批准镜头/空间记录与资产核对；只把额外构图图片对照标为 NOT_APPLICABLE。

`make_generation_qa.py` 复制判据、记录 manifest/返回图片哈希，必审维度为 `UNREVIEWED`，预先豁免项仅沿用计划状态。这些豁免是计划声明，不代表已确认生成器没有扩大裁切；构图复核必须检查实际越界。人工看图后填写每个必审维度的 `PASS/FAIL`、`reviewer` 和具体 `evidence`，失败写明哪位人物、什么部位或哪处接触错误。

```text
python scripts/continuity_contract.py --manifest <B包>/全话提示词索引.json
python scripts/continuity_contract.py --manifest <B包>/全话提示词索引.json --qa-report <QA目录>/生成图QA报告.json
```

第二条只确认分项记录与冻结来源相符，成功状态为 `DIMENSION_REVIEW_RECORDED`；`layout_release` 始终为 false。试产并排（batch5_v1 为首五格，旧模式首三格）、相邻机位、既有 HOLD 和用户批准仍按 Phase F 执行；批次模式另按 [batch-parallel.md](batch-parallel.md) 审查批内/跨批连续性。字段检查不能证明复核者确实看图，也不能自动批准底图。身份 PASS、衣装 PASS 但递手机接触 FAIL 时整体继续 HOLD，不能平均打分放行。

visual_evidence_v1补充本格具体预期和实际观察，继续使用本文件五维度及独立画风审查，不另建替代总分。人物状态、可见首饰原参考及跨切场连续性按 [具体视觉证据](visual-evidence.md) 校验。
