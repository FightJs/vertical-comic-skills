"""Synthetic observations for tests only; no image QA."""
import asset_format as fmt
def reviewed(image_sha):
    value=fmt.review_template(image_sha)
    value['reviewer']='SYNTHETIC_FORMAT_TEST'
    for name,row in value['views'].items():
        row.update(status='PASS',full_body=True,evidence='SYNTHETIC view observation')
        if name!='main_full_body':row['angle_degrees']={'front':0,'side':90,'back':180}[name]
    for row in value['checks'].values():row.update(status='PASS',evidence='SYNTHETIC consistency observation')
    return value
