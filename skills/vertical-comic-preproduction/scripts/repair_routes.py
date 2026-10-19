"""Deterministic repair triage and lossless crop candidates; never grants image acceptance."""
from __future__ import annotations
import argparse,json,hashlib
from pathlib import Path

SPATIAL={'seat','support','reflection','limb_ownership','camera','scene_reference','action_stage','action_target','prop_state'}
LOCAL={'accessory','eyelid','finger','local_clarity','costume_detail','expression'}
ALL=SPATIAL|LOCAL|{'crop'}
def text(v):return isinstance(v,str) and bool(v.strip())
def plan(d,record):
    if not isinstance(d,dict) or not text(d.get('reviewer')) or not text(d.get('evidence')):raise ValueError('缺实际诊断者与证据')
    if d.get('source_image_sha256')!=record.get('output',{}).get('sha256') or not text(d.get('source_image_sha256')):raise ValueError('诊断未绑定本格真实底图')
    defects=d.get('defects')
    if not isinstance(defects,list) or not defects or any(not isinstance(v,str) or v not in ALL for v in defects):raise ValueError('缺合法具体缺陷分类')
    if record.get('round_id',1)>=2 or d.get('same_problem_persists') is True:route='stop_diagnose'
    elif set(defects)&SPATIAL:route='rebuild_inputs'
    elif set(defects)=={'crop'}:route='crop_candidate'
    else:route='local_edit'
    return {'route':route,'image_call_allowed':route=='local_edit','required_next':{
        'stop_diagnose':'停止自动尝试，检查底图固化或预算；不创建新attempt',
        'rebuild_inputs':'先修受影响镜头/参考/动作并取得原准确范围批准，再按剩余预算编译',
        'crop_candidate':'先验证裁切范围、原比例、必显区域与有效像素，导出待审候选，不调用生图',
        'local_edit':'合并本格局部问题，使用真实清晰底图与全部适用依据，核对此前正确内容'}[route],
        'source_image_sha256':d['source_image_sha256'],'defects':defects,'production_approved':False}

def export_crop(source,output,design):
    from PIL import Image
    source=Path(source).resolve();output=Path(output).resolve()
    if output.exists() or output.with_suffix('.crop.json').exists() or source==output or output.suffix.lower()!='.png':raise ValueError('原图保留，输出必须为不存在的新文件')
    actual=hashlib.sha256(source.read_bytes()).hexdigest()
    if design.get('source_image_sha256')!=actual or not text(design.get('reviewer')) or not text(design.get('evidence')):raise ValueError('缺真实底图或具体裁切核对')
    box=design.get('crop');required=design.get('required_visible');regions=design.get('required_regions')
    if not isinstance(required,list) or not required or any(not text(v) for v in required) or not isinstance(regions,dict) or set(regions)!=set(required):raise ValueError('全部批准必显内容须逐项对应实际原图区域')
    with Image.open(source) as im:
        w,h=im.size
        def valid(b):return isinstance(b,list) and len(b)==4 and all(type(n) is int for n in b) and 0<=b[0]<b[2]<=w and 0<=b[1]<b[3]<=h
        if not valid(box):raise ValueError('裁切框超出原图')
        for r in regions.values():
            if not valid(r) or not (box[0]<=r[0]<r[2]<=box[2] and box[1]<=r[1]<r[3]<=box[3]):raise ValueError('裁切丢失必显区域')
        num,den=[int(x) for x in design['target_ratio'].split(':')]
        if num<=0 or den<=0 or (box[2]-box[0])*den!=(box[3]-box[1])*num:raise ValueError('裁切改变批准比例')
        minimum=design.get('min_short_edge')
        if type(minimum) is not int or minimum<=0 or min(box[2]-box[0],box[3]-box[1])<minimum:raise ValueError('有效像素不足，不插值冒充清晰')
        output.parent.mkdir(parents=True,exist_ok=True)
        with output.open('xb') as f:im.crop(box).save(f,format='PNG')
    report={'status':'CANDIDATE_REQUIRES_ACTUAL_QA','source_image':str(source),'source_image_sha256':actual,'output':str(output),'output_sha256':hashlib.sha256(output.read_bytes()).hexdigest(),'design':design,'image_calls':0,'production_approved':False}
    with output.with_suffix('.crop.json').open('x') as f:json.dump(report,f,ensure_ascii=False,indent=2)
    return report

def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--diagnosis');p.add_argument('--record');p.add_argument('--crop-source');p.add_argument('--crop-design');p.add_argument('--output');a=p.parse_args()
    if a.crop_source:
        if not a.crop_design or not a.output or a.diagnosis or a.record:p.error('裁切仅用crop-source/crop-design/output')
        value=export_crop(a.crop_source,a.output,json.loads(Path(a.crop_design).read_text()))
    else:
        if not a.diagnosis or not a.record or a.output:p.error('诊断仅用diagnosis/record，只读输出')
        value=plan(json.loads(Path(a.diagnosis).read_text()),json.loads(Path(a.record).read_text()))
    print(json.dumps(value,ensure_ascii=False,indent=2))
if __name__=='__main__':main()
