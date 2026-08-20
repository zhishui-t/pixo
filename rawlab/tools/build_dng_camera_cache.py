import argparse, json, re, sys
from pathlib import Path
import exifread, rawpy
ROOT=Path(__file__).resolve().parent.parent.parent
sys.path.insert(0,str(ROOT))
from rawlab.engine.decode import _read_dng_opcode_list
from rawlab.tools.dng_stage3_replicate import parse_color_math, run_engine

def dng_meta(path):
    with open(path,'rb') as f:
        tags=exifread.process_file(f,details=False)
    model=str(tags.get('Image Model','')).strip()
    lens=str(tags.get('EXIF LensModel','')).strip()
    focal=str(tags.get('EXIF FocalLength','')).strip()
    raw=rawpy.imread(str(path)); white=int(raw.white_level); raw.close()
    return model,lens,focal,white

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument('--dng-dir',default=r'K:\dsh-share\dng_verify')
    ap.add_argument('--dcp',default=r'C:\ProgramData\Adobe\CameraRaw\CameraProfiles\Camera\Nikon Z 5 2\Nikon Z 5 2 Camera Standard v2.dcp')
    ap.add_argument('--out',default=str(ROOT/'rawlab/calibration/dng_camera_cache.json'))
    args=ap.parse_args()
    dng_dir=Path(args.dng_dir); out=Path(args.out); out.parent.mkdir(parents=True,exist_ok=True)
    cache={'entries':{}}
    for dng in sorted(dng_dir.glob('*.dng')):
        stem=dng.stem
        cache_dir=dng_dir/'rawflow_dng_cache'
        try:
            stage_raw,ref,tone,text=run_engine(str(dng),args.dcp,cache_dir,stem)
        except Exception as e:
            print('skip',stem,e); continue
        info=parse_color_math(text)
        model,lens,focal,white=dng_meta(dng)
        ops=_read_dng_opcode_list(str(dng))
        # convert tuples to lists for json
        def conv(x):
            if isinstance(x,tuple): return list(x)
            if isinstance(x,list): return [conv(v) for v in x]
            if isinstance(x,dict): return {k:conv(v) for k,v in x.items()}
            return x
        key=f'{model}|{lens}|{focal}'
        entry={'model':model,'lens':lens,'focal':focal,'white_level':white,
               'opcodes':conv(ops),
               'src_bounds':list(info['src_bounds']),'dst_size':list(info['dst_size']),
               'total_baseline':info['total_baseline'],'stage3_gain':info['stage3_gain'],
               'tone_table':str(tone),'engine_log':str(cache_dir/f'{stem}.engine.log')}
        cache['entries'][key]=entry
        print(key,'->',white,'baseline',info['total_baseline'])
    out.write_text(json.dumps(cache,ensure_ascii=False,indent=2),encoding='utf-8')
    print('wrote',out)
if __name__=='__main__': sys.exit(main())
