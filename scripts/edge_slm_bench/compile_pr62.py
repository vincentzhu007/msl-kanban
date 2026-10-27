import json,time,pathlib,logging
import mslite_llm_export as e
logging.basicConfig(level=logging.INFO)
w='/out/pr-validation/.msl_export_3uy811xi'
for _ in range(30):
 try: json.loads(pathlib.Path(w+'/qwen3_config.json').read_text());break
 except (FileNotFoundError,json.JSONDecodeError):print('WAIT_FOR_PR1362_QUANT',flush=True);time.sleep(30)
else:raise RuntimeError('PR1362 export did not complete')
a=e.build_parser().parse_args(['--model','/models/Qwen3-4B','--output','/out/pr-validation/qwen3-4b-pr1362-pr62-s16s4-9030-2048.msl','--target','kirin9030','--quant-type','s16s4','--max-length','2048','--chunk-size','64','--keep-artifacts'])
e.MODEL_TYPES['qwen3']['exporter']=lambda **kwargs:w+'/qwen3_config.json'
original=e.compile_omc
pathlib.Path('/out/pr-validation/pr62-compiled').mkdir(exist_ok=True)
def compile_separate(**kw):
 kw['omc_path']='/out/pr-validation/pr62-compiled/model'
 return original(**kw)
e.compile_omc=compile_separate
e.run_pipeline(a,w)
