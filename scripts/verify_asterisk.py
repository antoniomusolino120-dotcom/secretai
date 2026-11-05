"""CI check: start Asterisk with no network, verify AudioSocket and the dialplan."""
import subprocess,time,uuid
name='secretai-asterisk-check-'+uuid.uuid4().hex[:10]
try:
    subprocess.run(['docker','run','-d','--network','none','--name',name,'secretai-asterisk:verify'],check=True,capture_output=True)
    ready=False
    for _ in range(30):
        result=subprocess.run(['docker','exec',name,'asterisk','-rx','core show application AudioSocket'],capture_output=True,text=True)
        if result.returncode==0 and 'AudioSocket' in result.stdout and 'not registered' not in result.stdout:
            ready=True;break
        time.sleep(.5)
    if not ready:
        print(subprocess.run(['docker','logs',name],capture_output=True,text=True).stdout)
        raise RuntimeError('AudioSocket did not start')
    dialplan=subprocess.check_output(['docker','exec',name,'asterisk','-rx','dialplan show secretai-inbound'],text=True)
    assert 'AudioSocket(' in dialplan and 'AGI(' in dialplan
    print('Asterisk started without network: AudioSocket module and inbound dialplan verified')
finally:
    subprocess.run(['docker','rm','-f',name],capture_output=True)
