# 身份、外观状态与场景确认

适用于输入审计、镜头/资产设计、提示词生成及旧包修复。先确定对象，再确定本话状态，再绑定批准资产；参考用途合同不能替代称呼与身份的确认。

## 先区分待补状态与身份疑点

先按[grouped-review.md的脚本优先规则](grouped-review.md#脚本优先与补充状态免重复亲审)处理用户委托。明确脚本与旧资产的服装、鞋履等差异是状态制作缺口；已有脚本优先委托或用户已选择脚本时，直接记录采用依据、补最小增量状态、内部审图并继续，不询问裁决，也不要求补充候选亲审。不能用下文的APPEARANCE_HOLD禁止必要补图。身份锚点及配饰位置一致性仍须保留。

## 未解决身份疑点的处理

先查本书角色表、关系表、原作/批准脚本、当前资产索引和后续范围明确的用户确认。证据唯一且适用于当前版本/状态时直接复用。证据缺失、冲突、同称呼多人、身份与图不符、服装时期不明、场景归属或状态不明时，记录 `IDENTITY_HOLD`、`APPEARANCE_HOLD` 或 `SCENE_IDENTITY_HOLD`，暂停受影响对象及所有依赖它的设计、补图和提示词交付。

未获脚本优先或自主处理委托、确需用户裁决时，暂停期间读取材料、整理问题与依赖范围。给用户展示：疑点原文、证据/候选冲突、影响格号、需要明确的姓名/关系/状态/资产。不要边问边按猜测开发，不把沉默、概率、候选图片、文件名或制作授权当作确认。合并关联问题，询问具体疑点，不重复询问未变化且已确认的事项。

“傅妈”必须绑定具体角色与关系对象；不能仅按“某位母亲”选长相或服装。原脚本保留“傅妈”，映射层登记全名。原作没有全名时使用已确认角色名和唯一ID，不补造姓名。一次出镜只免独立资产板，不免身份/外观确认。画外说话人仍须明确身份；不要求为不可见、不会影响连续性的服装细节新增批准。

询问模板：`【IDENTITY_HOLD｜Pxxx–Pyyy】脚本原称呼为“傅妈”。已查依据：[实际路径及对应内容]；未决项：[具体冲突或缺失]。请确认她对应哪位人物（全名；原作无全名则明确角色名）、是谁的母亲，以及本话采用哪份已确认外观/服装状态。确认前暂停这些格子的资产、站位和提示词设计。` 只询问实际未决字段，已有有效确认不要重复问；不提供未经证实的姓名或人物图作为默认答案。

## 新记录契约

镜头表、提示词总索引和本话输入审计声明 `identity_policy=identity_confirmation_v1`、`book_id`、`episode_id`。它们携带同一份 `identity_registry` 快照：

- `book_id`：本书唯一身份；
- `characters`：角色ID → `canonical_name`、`name_kind=full_name/approved_role_name`、`relationships`、`confirmation`、`aliases`；
- `relationships`：数组，条目含 `relation` 与 `target_character_id`。确无适用关系时为空数组，不推测补全；
- `aliases`：原称呼 → `relationship_context`、`relationship_kind=kinship/nickname/title/other_confirmed`、`target_character_ids`、`confirmation`。亲属称呼必须有明确关系对象 ID；昵称/职称确无关系对象时才使用空数组。确认范围须包含具体原称呼与关系，不能把不明亲属称呼静默登记成昵称绕过确认；
- `appearance_states`：状态ID → `character_id`、简短且精确的已确认 `description`、`confirmation`。描述保留脸/发型等身份锚点，只增加获准服装、伤势或装备变化；
- `scene_states`：状态ID → `scene_id`、`canonical_name`、`ownership_context`、`description`、`confirmation`。公共场景可明确登记公共归属，不能强行认定个人所有；
- `assets`：资产ID → `book_id`、`subject_id`、`state_id`（状态资产必填）、`purposes`、`version`、`sha256`、`status=APPROVED`、`confirmation`。用途采用 `identity`、`costume_state`、`scene_view`；一张批准板可有多个用途；
- `issues`：当前受影响范围的疑点数组，条目记录原文、问题类型、对象、格号、问题及状态。未解决项保留 OPEN；`RESOLVED_WITH_EVIDENCE` 必须有 `resolution_evidence` 文件/哈希，不能直接清空历史疑点。

确认对象的公共结构如下；`*` 只用于实际批准了全书/全话范围的情况，不从局部确认扩大：

```json
{
  "confirmation": {
    "status": "CONFIRMED",
    "scope": {
      "book_id": "本书ID",
      "subject_id": "CH-001",
      "episode_ids": ["E001"],
      "panel_ids": ["P005", "P006"],
      "state_id": "AS-001"
    },
    "facets": ["appearance"],
    "evidence": [{"path": "00_输入审计/确认依据.md", "sha256": "实际文件SHA256"}]
  }
}
```

身份使用 `facets=[identity]`；别名使用 `[alias, relationship]` 且 scope 含 `source_label`；外观使用 `[appearance]`；场景使用 `[scene_identity, scene_state]`；资产归属使用 `[asset_binding]`。状态确认须带相应 `state_id`。依据路径相对校验器 `--root` 所指本话根目录，必须是真实文件并匹配哈希。若打包移机，复制审计依据并调整到新根目录，不能保留不可达绝对路径。

每格新增：

- `script_character_labels`：本格原脚本中的角色称呼，不改原文；
- `character_bindings`：逐称呼登记 `source_label`、`character_id`、`canonical_name`、`on_screen`；入画角色另有 `appearance_state_id`、`identity_asset_alias`、`costume_asset_alias`；
- `characters_visible`：使用唯一角色ID，与 `on_screen=true` 的绑定一致；
- `scene_binding`：`scene_id`、`scene_state_id`、`background_visible`、`asset_alias`；
- 镜头候选的 `planned_identity_assets` 与提示词包的 `reference_images` 条目含 `alias`、`asset_id`、`version`、`sha256`，用于绑定索引的批准资产；实际参考路径仍按原包契约填写；
- 提示词包增加 `identity_execution_block`。先校验绑定，再用 `identity_confirmation.execution_block(panel, registry)` 编译到实际 prompt.txt，不能手填未知姓名或外观。

单次出镜可用 `asset_exemption` 免独立资产引用，须明确 `status=ONE_OFF_ASSET_EXEMPT`、整数 `appearance_count=1`、`book_id`、`episode_id`、唯一 `panel_ids` 与源脚本/扫描 `basis`。身份、状态和关系确认仍然必需。

## 阶段执行与旧包

A 阶段先完成称呼/身份/关系、状态和场景绑定；依赖未决项的 B/C/D/E 停止。身份与外观确认后，沿用 ID 和状态，不根据亲属称呼、年龄或参考图的相似性重新推测。更换样貌、服装或场景状态时完成相应证据核对；确认点不等于用户亲审点。适用委托内的状态补充由执行者内部审核，不重复请求用户确认；身份确认不能替代状态确认。

```text
python scripts/identity_confirmation.py --root <本话根目录> --manifest <身份审计或镜头表>
python scripts/identity_confirmation.py --root <本话根目录> --manifest <身份审计> --identity-only
python scripts/identity_confirmation.py --root <本话根目录> --manifest <提示词索引> --prompt
```

`--identity-only` 仅供 A/B/C 设计前检查身份、关系、外观设计状态和场景状态，不要求此时已补完资产，不授权生成提示词包；资产缺口继续记录 `ASSET_HOLD`。E 阶段、完整 `validate_preproduction.py` 和两版修复器必须执行严格资产绑定检查，不能使用该选项或省略实际图哈希。

`validate_preproduction.py` 同时执行此门禁。旧包缺失 policy 或绑定时保持 HOLD，先以实际证据迁移。修复脚本不得生成看似确定的下游包或删除身份/外观/场景 HOLD。`PASS` 只证明声明、范围、文件哈希和绑定的一致性，不证明证据内容确有用户批准；必须实际阅读确认记录并打开人物/场景参考图核对。

F 阶段用确认的身份和状态参考验收实际像素。首次出现、新服装/伤势状态、跨场景后重现须重点核对。错误图片保持 `IMAGE_CONTINUITY_HOLD`，不要用气泡、裁切或模糊提示词掩盖，不自动修改源资产。

批准复用核对原图、原身份/衣装状态及用途范围，不因路径迁移重复提问；无法证明同一范围时仍保留真实缺口。

委托下的confirmation.status=CONFIRMED表示依据已核实，并非用户亲审；evidence须包含真实脚本依据、适用用户委托/选择及执行者实际审图记录。资产status=APPROVED表示已完成适用审查，A阶段仍用AGENT_DECIDED_UNDER_USER_AUTHORITY保存决定来源，不伪造用户批准。未完成的补图不可提前标记通过；issues在修复后以RESOLVED_WITH_EVIDENCE闭环并保留历史。
