# Asset production

新运行优先按[第一批前期提速](preparation-efficiency.md)执行最小充分设计、代表格接线、单次B/包展示及问题分级处理。可选润饰不产生HOLD；真实缺口在现有委托内修复，局部问题只影响真实依赖，其他工作继续。正式输入与接包要求仍按原合同。

脚本优先委托或用户已选定脚本时，鞋履/衣装差异按[grouped-review.md](grouped-review.md#脚本优先与补充状态免重复亲审)自动补充并内部审核，不新增A前置裁决或候选亲审。

前期询问策略先按[明确委托的最少询问规则](grouped-review.md#前期仅询问无法消解的剧本资产冲突)判断；适用时，本页前期亲审/确认均改为执行者实际审查和委托决定，导出沿条件授权执行，不增加人工停点。生产阶段及旧冻结合同不因此改变。

在 `episode_preparation_v1` 中，本阶段一次审计并补齐当前整话所需人物、衣装、场景与适用视角，再提交一份全话A视觉基准。H001/H002是后续生图与图片审查范围，不各自重复制作资产；生产期间出现真实新增状态时只修订受影响依据并保留原批准来源。

### Phase C — scene and missing-asset production plan

In the existing per-panel records, maintain `continuity_contract` and `reference_bindings` under `reference_continuity_v1` as described in [references/reference-continuity.md](reference-continuity.md). Establish required visible information and permitted changes during shot design; bind references as assets become available. Reuse the same approved board for identity and costume when suitable, with separate purposes. Preserve one-off asset exemptions; do not create new boards merely to fill fields.

Check the current book's canonical comprehensive asset package before proposing scene generation:

Check character identity and the required episode appearance separately against the actual approved image; the correct person in the wrong clothing/state remains `APPEARANCE_HOLD`. Bind scenes by confirmed place, ownership and state. Do not substitute a similar character/room, infer clothing from a family relationship, or generate a missing state while its identity is unresolved.

- If an approved scene matches the required place, state and views, reuse it without regenerating the environment. Per-panel blocking and actual visible-content records are still required.
- If the scene exists but lacks a required view or script-supported state, preserve the approved structure and generate only the missing view or state extension as a separate candidate.
- If a recurring scene is absent, register the asset gap and create a new candidate using the same book's approved scene-board system. Do not substitute a similar room or retrieve an unapproved historical asset.
- A scene visible only once may use a panel-specific composition record without a standalone asset board. Apply the occurrence-count rule in the core principles; several panels in one scene are recurring use.

For any new or supplementary scene board, open an applicable same-book approved scene-board sample and record its asset ID, version, path/hash and template role. The approved template takes precedence over the generic nine-grid format. Match its canvas size/aspect ratio, panel layout, view count/types, title and view labels, typography and borders. A top-down-plus-three-views template remains that format; do not force every scene into nine cells. Treat the template as layout/label authority, while the scene ledger defines the actual geometry. The current book's approved comic style sample is the rendering authority and must actually accompany every asset-generation and repair request. A CG scene template must not override the approved 2D linework, face proportions, coloring or shading. Record these reference roles separately. If no applicable approved template exists, record that absence and use the generic nine-grid only as a candidate proposal.

For each recurring scene requiring assets, establish or reconcile a relative-coordinate scene ledger before generating views. Reuse proved spatial facts from approved assets and keep uncertain parts explicit:

- scene boundary and scale;
- fixed building/terrain silhouette;
- doors, windows, walls, roads, vehicles, vegetation, furniture, and props with stable coordinates, dimensions, height, and orientation;
- camera coordinate convention and north/clockwise orientation;
- light direction in scene coordinates, color temperature, softness, and shadow direction;
- existing source assets and confidence level;
- missing or uncertain parts.

When the approved template or candidate proposal uses a nine-grid, it is a continuity asset, not nine independent inventions:

- center cell: top-down scene plan;
- eight surrounding cells: eight azimuth views with explicit camera positions and facing directions;
- shared scale, stable structure, coherent perspective and physically consistent lighting;
- independent high-resolution view exports in addition to the contact sheet. Other approved board formats likewise retain the required views as independent usable references.

If using an image-generation tool, use only the current book's authorized visual references and the scene ledger. If no authorized image tool is available, create an `ASSET_HOLD` brief and do not claim the missing asset was generated. New assets remain `CANDIDATE` until user approval.

Review form and visual/spatial continuity separately before proposing acceptance:

- Form: verify canvas dimensions, subdivisions, required views, title/view-label text and their placement, typography and borders against the actual template. Use deterministic composition and exact text placement when needed; blank or garbled labels are not a match.
- Visual/spatial continuity: compare style, materials, lighting and the same doors, windows, furniture and props across the views against the scene ledger. State extensions may change only the supported delta; views cannot move fixed objects for convenience. A matching board layout does not prove correct space.

Record the template comparison, generation scope, form result, continuity result, unresolved differences and user acceptance evidence. Do not promise that one image-generation pass will satisfy both reviews. Failed or unresolved candidates remain HOLD and cannot be used as approved B references or promoted into the canonical package. Candidate approval and book-package publication follow the current book's asset rules; a technical PASS alone does not authorize either.

Before promoting a new scene or state board, reconcile the addition with the current book-wide canonical index and allowed evidence, preserving known gaps. Do not claim whole-book completeness from this incremental publication. A separately requested full-book inventory includes all provided episode references and user attachments; a fresh batch does not search unrelated old production folders. See [task origin](task-origin.md).

For recurring character states, use the matching approved character board as the base evidence before generating a state board. Retain the book-specific card system and add only the script-supported or explicitly authorized state delta. For every state board, record the approved character reference actually opened, unchanged identity anchors (face, hair, body proportions, fixed marks, base palette), the state delta, and inferred fields. A visual mismatch in the base character is a blocker even when the new prop or state itself is present.


## Character board invariants

17. Character state boards must be made as a strict visual extension of the same book's approved character-board samples. A “complete” board is not a loose collage or a vertical 3×3 portrait sheet: it is a horizontal information card with readable identity/state information, standard head portrait, half-body/state view, one coherent full-body front/side/back group, nine core expressions, and a bottom state/clothing/equipment/detail strip when needed. Use the actual approved board image as the visual authority; do not let stale audit prose override it.

18. Keep the central front/side/back group on one coherent base or one explicitly named target state. Alternate clothes, disaster-period gear, injuries, talismans, luggage, treatment changes, and other increments belong in the bottom state/detail area. They must not silently replace the approved face, hair, body proportions, base clothing structure, linework, palette, or lighting.

19. A generated board with blank or garbled section labels is not visually complete. If the image model cannot render Chinese labels reliably, preserve the candidate image as evidence but create a separate candidate revision with deterministic text overlay using the exact labels from the audit record. Never treat an empty colored title box as a successful match to an approved board that has readable labels.

20. A recurring state asset is one character's state asset. Do not combine two people into one character board merely because they share a scene or treatment event. If two recurring characters need the same scene-state reference, create one approved-style board per character and link the shared scene separately.

Technical faithful_atlas_v1 crops are separate from recurring character assets: preserve each original approved owner/state, verify pixels and readability, and use only identity/costume purposes. See [execution-compatibility.md](execution-compatibility.md). Asset candidate calls use the shared asynchronous runner and complete error logging; independent missing states/views can overlap within confirmed capacity. Prepare exact board labels deterministically as needed, retaining raw candidates.

## 本批补充参考与资产入库

发现缺项后执行下表，不以ASSET_HOLD代替补充工作。用户已授权前期和缺资产补充时，可准备并生成对应候选；“停在正文生图前”不禁止已授权资产生图。身份/剧情事实不明仍先确认，新增资产与整体A按最新有效委托完成审查；用户后续已取消A人工停点时，由执行者内部审查并继续，不沿用最初保留的A亲审。

| 本批实际需求 | 处理 |
| --- | --- |
| 当前批准资产覆盖 | 复用并实际看图核对，不重复生成 |
| 已有资产缺必要视角/状态 | 保留身份和布局，只补视角/状态 |
| 重要且需持续复用、确需完整板或用户指定入库 | 按本书规范生成并优化候选；形式/画风/空间/细节检查及A批准后发布增量索引 |
| 仅服务本批/特定镜头 | 制作临时补充参考，限定身份/状态/格号；不自动入库 |
| 真正一次性且逐格描述足够 | 直接描述，不强制独立资产板 |
| 旧索引缺项但本批不使用 | 记录库追溯限制，不阻塞本批、不生成无关资产 |

在唯一visual_basis.asset_tasks登记asset_id、episode_id、panel_ids、visible_occurrences（实际扫描范围内次数）、source_basis、当前reference（资产根相对path/sha256）及处理决定。publication_required标明确需入库；existing_asset_requires_extension标明仅缺视角/状态；inline_sufficient只用于确实单次、描述足够的对象。这些是执行者基于实际源稿/看图作出的判断，脚本不推测重要性或批准。

可运行scripts/asset_tasks.py --asset-root <当前全面资产根> --visual-basis <本话基准>只核选定需求的文件/哈希并返回补充路线；不扫描旧目录、不代表视觉PASS、不授予入库批准。补充调用/失败/未知与优化过程进入A原有记录，正文调用账另记。候选获批后更新当前基准；正式资产追加版本、文件哈希和准确范围，不覆盖旧资产；临时参考只进入本批包。发布前对当前全书索引和允许证据做增量对账，已知无关缺口保留，不要求重建无关全书资产。

新runtime生产审计限本批实际需求。已有批准场景/状态可用时复用，只补实际缺少的目标视角或状态细节；每次调用仍实际带批准画风及适用身份衣装。仅供本批的补充参考在A审查中明确范围，不要求重建与本批无关的整套视图。完整人物卡/场景板仍按本书规范制作于确有完整资产需求或用户要求入库时；临时补充参考不得宣称全库完备或自动发布到资产库。局部缺口只阻塞受影响格及真实依赖。

新RV的固定场景布局、重要首饰可读性与批准来源写入现有visual_basis的scene_layouts/appearance_details，遵守 [具体视觉证据](visual-evidence.md)。只登记源板确实能证明的关系；场景布局与人物站位分开。

## 关键首饰的独立清晰依据

对反复出现、当前可见且易错的耳饰、项链、戒指，优先从批准原板忠实提取清晰细节。复用appearance_details，记人物、当前衣装、形状/层数/连接结构/颜色、人物自身佩戴侧或手指，以及原图sha256和source_region。细节不替代身份依据。

看不清则登记缺口；放大插值不证明细节，生成补充设计在A批准前仍为候选。已有清晰原板可用就不另生图。每请求最多五路径；单图多用途先去重，忠实图集须覆盖真实细节且可辨认，不给每格无条件添加首饰参考。


A阶段按[背景模式](background-treatment.md)从原批准参考一次记录scene_background_profiles，按场景/子空间/连续状态复用。不强制新色板生图；身份/首饰细节仍引用原appearance_details。

## 易混入的服饰与场景

沿execution-quality.md维护scene_views和appearance_details，不另建逐格饰品台账。优先选择能清楚证明当前状态且不易带入相反发型/耳饰的适用参考；画风绑定只声明用途，不保证模型不会复制内容，仍须实际看图。饰品有无须清晰来源，遮挡或低清不证明不存在。场景选到真实子空间及方向；本格需要的车/家具等已有资产必须进入实际参考，不能以资产库中存在代替上传。
