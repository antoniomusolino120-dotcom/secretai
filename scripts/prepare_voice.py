"""Download public Italian TTS and multilingual STT assets; no account is needed."""
import argparse
from pathlib import Path
import subprocess
import sys

def prepare(destination):
    destination=Path(destination).resolve();destination.mkdir(parents=True,exist_ok=True)
    subprocess.run([sys.executable,'-m','piper.download_voices','it_IT-paola-medium','--data-dir',str(destination)],check=True)
    from faster_whisper import WhisperModel
    WhisperModel('small',device='cpu',compute_type='int8',download_root=str(destination/'whisper'))
    for name in ['it_IT-paola-medium.onnx','it_IT-paola-medium.onnx.json']:
        if not (destination/name).is_file():raise RuntimeError('Voice model preparation incomplete')
    print('Italian voice and Whisper assets prepared')

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--destination',default='/srv/models');args=p.parse_args();prepare(args.destination)
