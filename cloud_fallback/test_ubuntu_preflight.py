"""Trust-policy fixtures only: no apt, binary download or render."""
import hashlib
from pathlib import Path
import unittest
from unittest.mock import patch
import verify_ubuntu_package as v
ROOT=Path(__file__).resolve().parent
SCRIPT=(ROOT/'install_ubuntu_blender.sh').read_text()
SOURCES=SCRIPT.split("<<'SOURCES'\n",1)[1].split('\nSOURCES',1)[0]
CONFIG=SCRIPT.split('<<CONFIG\n',1)[1].split('\nCONFIG',1)[0].replace('$apt_root','/runner/tmp/aurelia')
PAYLOAD=b'synthetic validator fixture; not a Blender package'
META='\n'.join(['Package: blender','Version: '+v.VERSION,'Architecture: amd64',
    'Filename: pool/universe/b/blender/fixture.deb','Size: '+str(len(PAYLOAD)),
    'SHA256: '+hashlib.sha256(PAYLOAD).hexdigest()])
POLICY='blender:\n  Candidate: '+v.VERSION
class PackagePreflightTests(unittest.TestCase):
    def test_only_official_signed_sources_accepted(self):v.validate_sources(SOURCES)
    def test_third_party_and_unsigned_options_rejected(self):
        for bad in [SOURCES.replace('archive.ubuntu.com','ppa.launchpadcontent.net'),
                    SOURCES+'\n\nTypes: deb\nURIs: https://third.party.invalid',
                    SOURCES.replace('https://','http://'),SOURCES+'\nTrusted: yes',
                    SOURCES.replace(v.KEYRING,'/etc/apt/trusted.gpg')]:
            with self.subTest(bad=bad),self.assertRaises(AssertionError):v.validate_sources(bad)
    def test_apt_authentication_and_source_isolation(self):v.validate_apt_config(CONFIG)
    def test_weakened_or_duplicate_apt_flags_rejected(self):
        for key,value in [('Acquire::AllowInsecureRepositories','true'),('APT::Get::AllowUnauthenticated','true'),
                          ('Acquire::AllowWeakRepositories','true'),('Acquire::Check-Valid-Until','false'),
                          ('Acquire::Retries','1'),('Acquire::https::Verify-Peer','false')]:
            old='"false"' if value=='true' else '"true"' if value=='false' else '"0"'
            bad=CONFIG.replace(key+' '+old,key+' "'+value+'"')
            with self.subTest(key=key),self.assertRaises(AssertionError):v.validate_apt_config(bad)
        for extra in ['\nAPT::Get::AllowUnauthenticated "true";', '\napt::get::allowunauthenticated "true";', '\nBinary::apt-get::APT::Get::AllowUnauthenticated "true";']:
            with self.assertRaises(AssertionError):v.validate_apt_config(CONFIG+extra)
    def test_pinned_metadata_is_accepted(self):self.assertEqual(v.validate_metadata(META,POLICY)['Version'],v.VERSION)
    def test_version_architecture_filename_hash_drift_rejected(self):
        cases=[(META,POLICY.replace(v.VERSION,'4.5.14')),(META.replace('amd64','arm64'),POLICY),
               (META.replace('pool/universe/b/blender/','pool/thirdparty/'),POLICY),
               (META.replace(hashlib.sha256(PAYLOAD).hexdigest(),'invalid'),POLICY)]
        for metadata,policy in cases:
            with self.subTest(metadata=metadata),self.assertRaises(AssertionError):v.validate_metadata(metadata,policy)
    def test_archive_size_and_sha256_required(self):
        record=v.validate_metadata(META,POLICY)
        with patch.object(Path,'read_bytes',return_value=PAYLOAD):self.assertEqual(v.validate_archive(record,'fixture.deb'),record['SHA256'])
        for payload in [PAYLOAD+b'changed',bytes([PAYLOAD[0]^1])+PAYLOAD[1:]]:
            with patch.object(Path,'read_bytes',return_value=payload),self.assertRaises(AssertionError):v.validate_archive(record,'fixture.deb')
if __name__=='__main__':unittest.main(verbosity=2)
