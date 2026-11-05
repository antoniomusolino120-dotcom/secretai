"""Download public Italian TTS and multilingual STT assets; no account is needed."""
import argparse
from pathlib import Path
import subprocess
import sys
import os

os.environ['ORT_DISABLE_TELEMETRY']='1'
os.environ['HF_HUB_DISABLE_TELEMETRY']='1'
os.environ['DO_NOT_TRACK']='1'

def prepare(destination):
    import onnxruntime
    onnxruntime.disable_telemetry_events()
    destination=Path(destination).resolve();destination.mkdir(parents=True,exist_ok=True)
    subprocess.run([sys.executable,'-m','piper.download_voices','it_IT-paola-medium','--data-dir',str(destination)],check=True)
    from piper.voice import PiperVoice
    try:PiperVoice.load(str(destination/'it_IT-paola-medium.onnx'))
    except Exception:
        subprocess.run([sys.executable,'-m','piper.download_voices','it_IT-paola-medium','--data-dir',str(destination),'--force-redownload'],check=True)
        PiperVoice.load(str(destination/'it_IT-paola-medium.onnx'))
    from faster_whisper import WhisperModel
    WhisperModel('small',device='cpu',compute_type='int8',download_root=str(destination/'whisper'))
    for name in ['it_IT-paola-medium.onnx','it_IT-paola-medium.onnx.json']:
        if not (destination/name).is_file():raise RuntimeError('Voice model preparation incomplete')
    print('Italian voice and Whisper assets prepared')

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--destination',default='/srv/models');args=p.parse_args();prepare(args.destination)
