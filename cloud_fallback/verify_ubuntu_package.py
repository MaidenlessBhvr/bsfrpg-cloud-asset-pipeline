"""Validate source/version/archive provenance; remote apt commands only in main."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess

VERSION='4.0.2+dfsg-1ubuntu8'
KEYRING='/usr/share/keyrings/ubuntu-archive-keyring.gpg'


def deb822(text):
    stanzas=[]
    for block in text.strip().split('\n\n'):
        fields={}
        for line in block.splitlines():
            if not line or line.startswith('#') or line[0].isspace():continue
            key,value=line.split(':',1)
            assert key not in fields,'Duplicate field'
            fields[key]=value.strip()
        if fields:stanzas.append(fields)
    return stanzas


def validate_sources(text):
    stanzas=deb822(text)
    expected=[('https://archive.ubuntu.com/ubuntu','noble noble-updates'),
              ('https://security.ubuntu.com/ubuntu','noble-security')]
    assert len(stanzas)==2
    for fields,(uri,suites) in zip(stanzas,expected):
        assert fields=={'Types':'deb','URIs':uri,'Suites':suites,'Components':'main universe',
                        'Architectures':'amd64','Signed-By':KEYRING},'Unapproved repository/trust configuration'


def validate_apt_config(text):
    pairs=[]
    for line in text.splitlines():
        if not line.strip():continue
        match=re.fullmatch(r'([A-Za-z:.-]+) "([^"\n]*)";',line.strip())
        assert match,'Unreviewed APT config syntax/directive'
        pairs.append((match.group(1).lower(),match.group(2)))
    assert len(pairs)==len(dict(pairs)),'Duplicate case-insensitive APT configuration key'
    fields=dict(pairs)
    required={'Dir::Etc::main':'/dev/null','Dir::Etc::preferences':'/dev/null',
              'Dir::Cache::pkgcache':'','Dir::Cache::srcpkgcache':'','Acquire::Retries':'0',
              'Acquire::AllowInsecureRepositories':'false','Acquire::AllowWeakRepositories':'false',
              'Acquire::AllowDowngradeToInsecureRepositories':'false','APT::Get::AllowUnauthenticated':'false',
              'Acquire::Check-Valid-Until':'true','Acquire::Check-Date':'true',
              'Acquire::https::Verify-Peer':'true','Acquire::https::Verify-Host':'true',
              'APT::Update::Error-Mode':'any','Acquire::http::Timeout':'30',
              'Acquire::https::Timeout':'30','Debug::Acquire::gpgv':'true'}
    required={k.lower():v for k,v in required.items()}
    assert all(fields.get(k)==v for k,v in required.items()),'APT authentication policy weakened'
    dynamic={k.lower() for k in ['Dir::Etc::parts','Dir::Etc::sourceparts','Dir::Etc::trustedparts',
        'Dir::Etc::trusted','Dir::Etc::sourcelist','Dir::State::lists','Dir::Cache::archives','Dir::Etc::preferencesparts']}
    assert set(fields)==set(required)|dynamic,'Unreviewed APT override/config hook'
    empty=fields['dir::etc::parts'];assert empty.endswith('/empty')
    for key in ['dir::etc::sourceparts','dir::etc::trustedparts','dir::etc::preferencesparts']:
        assert fields[key]==empty
    assert fields['dir::etc::trusted']==empty+'/no-global-keyring'
    assert fields['dir::etc::sourcelist'].endswith('/ubuntu.sources')
    return fields


def validate_metadata(text,policy):
    match=re.search(r'^\s*Candidate:\s*(\S+)',policy,re.M)
    assert match and match.group(1)==VERSION,'Candidate version changed or unavailable'
    records=[r for r in deb822(text) if r.get('Package')=='blender' and r.get('Version')==VERSION]
    assert records,'Pinned Ubuntu package missing from authenticated indices'
    record=records[0]
    assert record['Architecture']=='amd64'
    assert record.get('Filename','').startswith('pool/universe/b/blender/')
    assert re.fullmatch('[0-9a-f]{64}',record.get('SHA256',''))
    assert int(record['Size'])>0
    assert all(r.get('SHA256')==record['SHA256'] for r in records),'Conflicting archive metadata'
    return record


def validate_archive(record,path):
    data=Path(path).read_bytes()
    assert len(data)==int(record['Size']),'Package size mismatch'
    digest=hashlib.sha256(data).hexdigest()
    assert digest==record['SHA256'],'Package SHA-256 mismatch'
    return digest


def command(*args):
    return subprocess.check_output(args,text=True)


def main():
    if os.environ.get('GITHUB_ACTIONS')!='true' or os.environ.get('AURELIA_REMOTE_EXPERIMENT')!='approved_v4_pilot':
        raise RuntimeError('Remote-only Ubuntu installation audit; no local apt execution.')
    parser=argparse.ArgumentParser()
    parser.add_argument('--stage',choices=['sources','candidate','download','installed'],required=True)
    parser.add_argument('--audit-dir',type=Path,required=True)
    parser.add_argument('--archives',type=Path)
    args=parser.parse_args();audit=args.audit_dir
    validate_sources((audit/'ubuntu.sources').read_text())
    fields=validate_apt_config((audit/'apt.conf').read_text())
    assert Path(fields['dir::etc::sourcelist']).read_text()==(audit/'ubuntu.sources').read_text()
    assert not any(Path(fields['dir::etc::parts']).iterdir()),'APT config/source isolation directory not empty'
    assert Path(os.environ['APT_CONFIG']).read_text()==(audit/'apt.conf').read_text()
    if args.stage=='sources':return
    policy=command('apt-cache','policy','blender')
    metadata=command('apt-cache','show','blender='+VERSION)
    record=validate_metadata(metadata,policy)
    (audit/'apt_candidate_policy.txt').write_text(policy)
    (audit/'apt_authenticated_package_metadata.txt').write_text(metadata)
    path=audit/'package_provenance.json'
    result=json.loads(path.read_text()) if path.exists() else {}
    result.update({'selected_package':'blender','resolved_candidate_version':VERSION,
                   'upstream_version':'4.0.2','architecture':'amd64','repository_component':'universe',
                   'repository_uris':['https://archive.ubuntu.com/ubuntu','https://security.ubuntu.com/ubuntu'],
                   'verification':'APT signed InRelease -> Packages hashes -> .deb SHA256',
                   'signed_by':KEYRING,'authenticated_index_sha256':record['SHA256'],
                   'authenticated_index_size':int(record['Size']),'authenticated_index_filename':record['Filename'],
                   'ubuntu_keyring_package_version':command('dpkg-query','-W','-f=${Version}','ubuntu-keyring'),
                   'ubuntu_keyring_sha256':hashlib.sha256(Path(KEYRING).read_bytes()).hexdigest(),
                   'installed_version':None if args.stage!='installed' else VERSION})
    if args.stage=='download':
        archives=list(args.archives.glob('blender_*.deb'))
        assert len(archives)==1,'Ambiguous/missing downloaded Blender package'
        result['downloaded_deb_sha256']=validate_archive(record,archives[0])
        result['download_verified']=True
    if args.stage=='installed':
        assert result.get('download_verified'),'Download verification was skipped'
        installed=command('dpkg-query','-W','-f=${Version}','blender')
        assert installed==VERSION,'Installed package differs from pinned Ubuntu version'
        assert command('dpkg','--verify','blender').strip()=='','Installed package files changed'
        version=command('/usr/bin/blender','--version')
        assert version.splitlines()[0]=='Blender 4.0.2','Unexpected runtime binary'
        result['blender_version_output']=version
        result['installed_binary_sha256']=hashlib.sha256(Path('/usr/bin/blender').read_bytes()).hexdigest()
        result['installed_version']=installed
    path.write_text(json.dumps(result,indent=2)+'\n')


if __name__=='__main__':main()
