# Prompt compilation

当前新RV按 [全话准备、逐格放行](panel-readiness.md) 和 [整话异步生产](episode-async.md)：完整源序、资产/A、镜头/B、语义/比例和生图包保持一套全话依据；已就绪范围分别取得B与包批准。总控批量领取真实空闲许可后逐格完整预检，整话独立格持续提交。尚未生成的前格实图以准确依赖补齐方案锁定文字、参考槽、顺序和规格；补齐后仍完整预检。旧H001/H002、C与runtime_v1步骤只适用于原冻结旧RV。

> 阶段化五件套执行时，同时遵守 [固定流程](staged-workflow.md) 和 [生图输入输出合同](generation-io.md)。每次生成及返修必须实际传入批准画风样例，单独审查画风；最终交付逐格图片包，旧“进入排版/C阶段”只作历史术语，不启动排版。单格原编号快照由 staged_workflow.py 调用完整门禁校验，不能为通过旧完整话编号检查重编号。


### Phase E — B-stage prompt package

For incremental_runtime_v1, an immutable candidate shot/spatial version may be compiled for combined B/package review; this candidate never authorizes generation. Other tasks compile after shot approval as before. Actual generation always requires applicable shot and package user approvals.

For `physical_scene_priority_v1`, carry the policy unchanged from the approved shot manifest. The actual prompt must say that physical support/contact/perspective/occlusion and approved fixed scene geometry govern execution, while identity, current clothes, specified expression/action/target/outcome and approved style stay intact. If the shot has an approved `visual_resolution`, copy its exact solution into the executable content block and per-panel JSON. An unresolved conflict remains a HOLD; never paste contradictory raw shot prose after the resolved instruction. Keep raw script text only in `locked_script` and audit fields.

Also require the identity/state gate to pass. Carry the exact approved registry/bindings from the shot records, bind actual reference aliases to their asset IDs/owners/states/versions, and compile `identity_execution_block` into the actual prompt.txt. Do not export placeholders, assumed names or assumed clothes. A reference file/hash PASS does not prove it depicts the intended character.

For each panel:

1. create `Pxxx/参考图/`;
2. copy the actual references needed for this panel: directional scene view, character/current costume, necessary detail/style and the target-camera composition only when selected in Phase D; keep any annotated station maps in supporting review documents for the Codex route;
3. register each copied file with a unique `@asset_alias`, role, version, relative path and SHA256;
4. write a complete executable positive prompt and necessary negative constraints based on the approved camera, framing and per-person spatial records;
   the first block of every positive prompt must be an executable camera block containing, in literal text, all of: `机位角度`, `景别`, `画幅比例`, `摄影机位置/朝向`, and `可见面与遮挡逻辑`. Do not replace this block with “按 locked shot 执行” or a reference to another JSON file;
5. state screen positions globally: `画面左/中/右`, `上部/中部/下部`, `面对观众/背对观众`;
6. state actual visible face angle and occlusion rather than generic “侧脸”;
7. state background structure and important objects that are actually visible;
8. preserve fixed character-relative marks, injuries, hair ornaments and prop continuity;
9. check every character's expression, action, gaze and body state against adjacent panels;
10. include scene/diegetic text that belongs inside the generated image, while leaving dialogue, inner voice, narration and post-added SFX to layout.
11. include a second literal `画面内容锁定` block, not merely a list of reference files. It must state the scene, the actual visible region, each visible character's global screen position, body/head/gaze/expression/action, fixed props/background anchors, depth and occlusion, and the locked event beat. If a source field is unavailable, keep the issue in the ledger and leave the package at HOLD; do not leak `HOLD`, `待确认`, `按源画面内容` or similar placeholders into a B-facing prompt.

Carry the approved `framing` record into each panel JSON and the package manifest. State the exact body crop and the needed background detail in prompt.txt. Describe only occupants and objects actually visible through that crop; keep offscreen continuity facts in the audit records. Full-body identity boards and wide scene references are identity/space authorities, not instructions to expand the panel. Never add legs, an entire room, extra bystanders or extra background props just to reproduce a reference sheet.

For new packages, carry the approved `continuity_contract` and `reference_bindings` unchanged from the shot record and declare `continuity_policy: reference_continuity_v1` in both manifests. For Codex, compile `reference_usage_block(bindings, reference_images)` with numbered roles in the actual input-array order. Compile the literal `reference_usage_block` into the actual prompt after the content block; the B tool must receive each alias's purpose and permitted transfer. Check this extension with `validate_preproduction.py`; legacy packages require evidence-based migration, not guessed contracts or a silently removed policy.

New B manifests also declare `control_policy: structural_guidance_v1`, include `generation_backend`, and give each panel an explicit `control_inputs` array (empty when unused). Preserve the separation of ordinary references, review documents and actual structural inputs. Before B generation, run `check_control_inputs.py --package-root <B-package> --phase preflight`; the overall preproduction validator also checks this contract. Planned inputs never mean control was executed. For Codex, export a NOT_RUN input plan with `codex_reference_contract.py`; pass the real absolute image paths to the tool, not merely aliases. Merge necessary avoid constraints into the final prompt; there is no separate negative-prompt tool slot. After generation, preserve observable tool-call/result records (local `attempt_id` when no service request ID is exposed) and verify them with `--phase execution`; do not manufacture logs from the planned package. Image acceptance remains a separate Phase F decision.

The prompt manifest must also carry `camera_angle_family`, `shot_scale`, a numeric positive `frame_ratio`, `camera_execution_status`, `camera_execution_block`, and `content_execution_block` per panel. Check the ACTUAL prompt.txt against the manifest and panel JSON. There is no minimum character count: test concrete visible content, not verbosity. Do not duplicate the whole script paragraph into every character attribute. Never extract a ratio from negative instructions such as “不要3:2”. Unresolved camera/spatial/asset/script HOLDs must survive rebuilding; scoped later approval evidence can resolve an obsolete HOLD without reapproving unchanged work.

Before delivery, run a semantic contradiction check in addition to the structural check. It must fail on null/placeholder camera coordinates, unresolved spatial markers in the executable prompt, generic per-person screen-position fallbacks, or mutually exclusive visible-face instructions. A prompt package that passes file/hash/reference checks but fails this semantic check is not ready for B.

`reference_images` contains decodable raster images supported by the B tool. SVG and JSON belong in `supporting_documents`; a genuine vector station map may be exported as PNG for review or a backend that actually needs it; Codex uses a selected clean target-camera reference, never an annotated top-down map as its substitute. NOT_REQUIRED needs no composition alias, image, empty slot or review file. Keep structured shot/visibility facts as JSON and prompt text; never manufacture an image from JSON or text to fill a missing reference. Unproved geometry remains CANDIDATE. Keep one authoritative prompt and one per-panel JSON; rebuild delivery documents instead of copying stale READMEs and prompt variants wholesale.

Read `repair-contract-v2.md` before repairing legacy packages. Use a coverage ledger: every original issue is RESOLVED_WITH_EVIDENCE, SUPERSEDED_WITH_EVIDENCE, ONE_OFF_ASSET_EXEMPT, or OPEN; never silently drop an issue. Place unresolved drafts outside a clearly identified B-ready selection. Preserve script-lock source cells including phone dialogue and punctuation exactly.

Before writing each prompt, copy the locked script text into the panel record and compare it character-for-character with the source. If the comparison fails, mark `SCRIPT_LOCK_HOLD`; do not “fix” it by paraphrasing.

The prompt must not explain the production theory. It must tell the image tool what is in the frame, where it is, and what state it is in. It may be concise, but it cannot omit the executable content contract. A prompt that only says “参考资产、按锁定镜头生成” is incomplete even when the JSON is detailed. The package must also include the detailed shot/spatial records for audit; the prompt is not a substitute for those records.

Run the workspace `check_prompt_package.py` when the manifest follows its schema. Also run this skill's `validate_preproduction.py`. If an external legacy checker still forces adjacent angle AND scale changes, report the policy conflict and adapt its check before release; do not widen the approved composition to make that checker pass. A structural PASS is not image approval.


v2编译保留source_panel_id、原锁定文字、获批镜头与真实前格context。多人超限优先同图多用途，再用忠实图集。校准修正只追加准确原失败图编辑用途，仍用真实第二轮；完整批量预检后只调度就绪格。 详细字段、命令和恢复规则见 [生产兼容与提速](execution-compatibility.md)。

已选择复杂空间两阶段路线时读取 [空景编辑与控制变量实验](background-first.md)。先冻结目标机位空景，静态道具绑定原家具；空景通过后实际作为编辑底图加人物，人物/当前衣装/批准样例仍携带，底图占一条参考路径。先审真实空间类别及结构覆盖，不能将校园外景当教室桌排依据。空景/实验图不自动纳入获批资产，正式正文仍走现有完整门禁；只在隔离实验目录试验未集成的来源，不更改已冻结生产状态。

## 构图扩展的实际注入

按prompt-package.md选本格模块；旧策略沿用framing.background_treatment=clear_limited，新narrative_background_v1按background-treatment.md逐格选择。用visual_evidence.framing_execution_block编译并合入实际prompt.txt及同版JSON的prompt；visual_evidence_v1的execution_block已有该块，不重复追加。特殊景深须有本格批准设计依据。

手部、首饰、视线、连续动作复用批准逐人物记录和visual_evidence.checks/appearance_details；模板不得补剧情或把画外人变生成目标。修复提示词包时保留新增framing字段与当前具体视觉块，缺依据HOLD，不能复制旧PASS。旧包不自动补字段，新候选仍走原准确范围批准。

候选包交审前逐格比对原源、获批B和最终实际prompt/参考：湿斑、道具类型、动作对象、画面下缘及必要可见性不得漏编译，不能同时保留互相冲突的旧裁切文字。机器检查只证明显式字段和文字一致；自然语言可实现性由执行者实际核对。B和包按[合并审查](grouped-review.md)一次展示、一次回复分别批准。

启用grouped_review_v1的新任务，semantic_template自动加入framing_feasibility未审项，绑定本格裁切、必显信息和机位；执行者实际核对后填PASS及具体依据。模板和机器字段不能证明空间语义正确；缺项或镜头变化后旧判据不再适用时，仅阻塞受影响格。


新背景策略从批准镜头及A的profile编译[背景执行段](background-treatment.md)，不得在生成时自行选择模式。对照真实prompt.txt核对保留、承托、接触、清晰重点和参考职责，清除矛盾旧句。


从冻结检查项编译真实执行文本见[实际执行质量与返修分流](execution-quality.md)。复用现有记录和人工停点，不静默升级旧RV。

当前execution_quality_v1正文编译以prompt-package.md的完整具体内容分支为准。实际附件仍由codex_reference_contract导出并核对场景视图、关键细节和原批准用途；候选默认镜头不自动获得放行。编译/文件问题不记成视觉失败，修输入后走原门禁，不重发未知请求。

新整话采用[最终输入收敛v2](final-input-semantics.md#前期收敛按包执行v2)：完整保留必要绘图信息，不为“简短”截断内容。原generation规则约束由build_prompt去重编入，具体事实、规则和审核判据在前期核对完毕。前期正式交付覆盖全部指定格的静态输入，未来实图只按准确补齐方案处理。
