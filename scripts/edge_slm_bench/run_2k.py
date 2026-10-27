"""On dog: run five consecutive generations and sample hidumper for that PID."""
import json, pathlib, subprocess, threading, time, sys
ROOT=pathlib.Path('/home/zhugd/llm_validation/20261026-qwen25-05b-w4a16-9020/context2048-input1024-output128')
BR='/home/zhugd/code/ohos/BinRunner'
count=int(sys.argv[1]) if len(sys.argv)>1 else 5
label='pilot' if count==1 else 'five-aligned'
stop=threading.Event()
def shell(command):
    return subprocess.run(['hdc','-t','127.0.0.1:2000','shell',command],capture_output=True,text=True,timeout=8).stdout
def memory():
    idx=0
    while not stop.is_set():
        try:
            processes=[line.split() for line in shell('ps -A -o PID,PPID,NAME').splitlines()]
            app=[r for r in processes if len(r)==3 and r[2]=='com.example.binrunner']
            children=[r[0] for r in app if r[1] in {a[0] for a in app}]
            pid=children[0] if len(children)==1 else ''
            if pid.isdigit():
                data=shell(f'date +%s%N; hidumper --mem {pid}; date +%s%N')
                (ROOT/f'{label}-memory-{idx:03d}.txt').write_text(f'PID {pid}\n'+data)
                idx+=1
        except subprocess.TimeoutExpired:
            pass
        stop.wait(.2)
thread=threading.Thread(target=memory);thread.start()
try:
    cmd=['python3','-m','binrunner','-t','127.0.0.1:2000','-p','18888','run',f'bench2k @/bin/qwen25-05b-w4a16-9020-2048-compatible.msl {count}','--timeout','90']
    result=subprocess.run(cmd,cwd=BR,capture_output=True,text=True,timeout=110)
    output=result.stdout+'\n'+result.stderr
    (ROOT/f'{label}.log').write_text(output)
    rows=[json.loads(line[7:]) for line in output.splitlines() if line.startswith('RESULT ')]
    (ROOT/f'{label}-samples.json').write_text(json.dumps(rows,indent=2))
    print(output,flush=True)
    assert result.returncode==0 and 'DESTROY status=0' in output and len(rows)==count
    assert all(r['status']==0 and r['output_callbacks']==128 and r['finish_reason']==3 for r in rows)
finally:
    stop.set();thread.join()
