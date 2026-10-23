# 坐标引导局部返修：coordinate_edit_v1

只在原QA确认局部结构问题、决定值得使用剩余返修额度时读取。通用视觉方法以当前MEM-004为准；动物结构命中MEM-012时另读其正文，不把动物专项装进每次返修。它是现有local_edit的一种方法，不新增生产动作、模型审核轮次、图像调用额度或人工停点。

## 在已有观察中判断范围

在原production_decision.issues逐问题补repair_scope：local_structure / global_space / uncertain。整间房布局不符、机位/整体透视错误、多处关系共同变化归global_space，交现有整体空间/输入修订方案；不能拆成多个局部框。局部弧边、重复肢体、部件连接可作为local_structure；分类按实际影响关系，不按景别或框面积。多手等原category=1不得降级。全图含未处理整体空间错误时，不选坐标法掩盖其余问题。

仅选择坐标法时，原决定设action=local_edit、method_key=coordinate_local_edit。保留原cause_key、原QA引用、fix_now/opportunistic/manual和保留约束。增加coordinate_assessment：
- evidence：原实图观察如何支持局部范围；不再进行一次独立看图。
- target_basis：批准动作/结构参考的准确来源。
- input_status：no_conflict_signal或resolved。前者仅表示本次相关输入没有发现疑点，不代表全包重新审过。
- input_evidence：引用已有前期审查及本问题相关的动作/场景描述；仅发现具体疑点时追查相关片段。
- resolution_evidence：input_status=resolved时必填，说明准确修订和原审查依据。

suspected或依据不足不直接提交；按原输入修订流程解决。前期原有PASS仍可复用，但与实际图/相关文字出现具体冲突时不能压过新证据。旧冻结流程继续旧分流，不给旧字段加例外。

## 最小坐标数据

本格repair_focus保留failed_transfers及structural_change.remove/replace/connect。增加coordinate_edit对象：

```json
{
  "policy": "coordinate_edit_v1",
  "coordinate_system": "percent_top_left",
  "source_image_sha256": "实际底图SHA256",
  "source_size": [1000, 1500],
  "issue_ids": ["edge"],
  "edit_regions": [{
    "id": "A", "issue_id": "edge", "object": "前景台面长边",
    "box": [0, 60, 100, 100],
    "instruction": "删除旧弧边，以指定直边重建同一硬平面"
  }],
  "anchors": [{
    "id": "edge_endpoints", "region_id": "A", "kind": "line",
    "points": [[0, 65], [100, 75]], "purpose": "唯一笔直长边，合理透视斜向保留"
  }],
  "expected_observations": {
    "old_edge_removed": "旧弧线及重复边缘消失",
    "plane": "长边笔直，厚度与台面共用透视关系"
  }
}
```

以上为合成格式示例，不得复制到具体图当作真实坐标。百分比以实际选用底图为准，左上原点、x向右、y向下。锚点kind=point/line/plane，分别1/2/至少3个不同点；无必要锚点可用空列表。编辑框覆盖旧错误、新位置及必要连接，不要求补画整个物体。参考子图选区不能冒充底图编辑坐标。

保护区域仍用repair_source.preservation_regions的原图整数xyxy。若与某edit_region相交，该区域增加preservation_overlap={保护区名:具体对象优先级与允许过渡}；文字解释不能自动证明两者物理可行，执行者须解决真实冲突。正确主体可用preserved_features具体保护，不强制为每个部位造框。

issue_ids必须与原决定fix_now+opportunistic完全一致；整主体检查仍沿原QA进行。底图选择沿原记录，允许选更清晰且保留有效修正的已记录版本；坐标绑定该版本，而非机械绑定最新失败图。若换图或裁切，重新定位并重编译。

## 编译与预检

scripts/coordinate_repair.py只做确定性校验及提示词段编译，不检测图像、不猜坐标、不提交生图。repair_prompt_package_v2.build_prompt由现有panel_derivation.render调用，将该段编入准确实际prompt。手工受控组包也调用同一execution_block(panel)，不能另写不一致的坐标段；实际prompt/JSON按原流程同步并完成最终输入审查。坐标段顺序：真实底图别名→区域/锚点→remove/replace/connect→保留特征→可观察目标。任何输入冲突应修具体来源，不保留相反段落再用坐标覆盖。

repair_input_guard验证实际prompt包含当前完整坐标段；input_quality核对生产决定与目标；visual_evidence.repair_basis打开哈希已校验的真实底图核对尺寸。坐标合法和文字完整不是模型像素锁定，也不代替适用批准参考。额度、未知结果、输入批准与相同问题停止条件继续由原门禁核验。

## 返回图复核

原visual_evidence_review.repair_comparison增加coordinate_observations，键与expected_observations相同，每项status和observed填写实际观察。模板一律UNREVIEWED，不能根据坐标字段自动PASS。沿whole_subject_recheck核对整个人/动物/物体，沿preserved_observations对比保护区。逐项目标可有PASS/FAIL；位置改善但指趾/连接失败须保留FAIL，采用与交付仍由原生产决定处理。原六项与连续性审查不删减、不再建立第二套整图QA。
